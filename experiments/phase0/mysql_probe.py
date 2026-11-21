"""MySQL 8.0 Windows probe. Creates two disposable instances on unique local pipes."""
import concurrent.futures
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
import uuid


SERVER = Path(shutil.which("mysqld") or "mysqld").resolve(strict=True)
DB = "duit_probe"


def run(tool, *args, data=None, check=True):
    env = dict(os.environ)
    env.pop("MYSQL_PWD", None)
    env["MYSQL_TEST_LOGIN_FILE"] = str(WORK / "absent-login-file")
    return subprocess.run(
        [str(SERVER.with_name(tool + ".exe")), "--no-defaults", *args],
        input=data, capture_output=True, check=check, timeout=90, env=env,
    )


class Instance:
    def __init__(self, folder, server_id, port=None):
        self.folder = folder
        self.pipe = "duit-probe-" + uuid.uuid4().hex
        self.flags = (f"--datadir={folder}",)
        self.server_id = server_id
        self.port = port

    @contextlib.contextmanager
    def start(self):
        run("mysqld", "--initialize-insecure", "--console", *self.flags)
        network = ("--skip-networking",) if self.port is None else (
            "--bind-address=127.0.0.1", f"--port={self.port}")
        with (self.folder / "console.txt").open("wb") as console:
            proc = subprocess.Popen(
                [str(SERVER), "--no-defaults", *self.flags, *network,
                 "--enable-named-pipe", f"--socket={self.pipe}", "--log-bin=probe-bin", "--mysqlx=OFF",
                 f"--server-id={self.server_id}", "--console"],
                stdout=console, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                last_error = b""
                for _ in range(30):
                    if proc.poll() is not None:
                        break
                    result = self.query("SELECT 1", check=False)
                    if result.returncode == 0 and result.stdout.strip() == b"1":
                        yield self
                        return
                    last_error = result.stderr
                    time.sleep(0.25)
                raise RuntimeError(last_error.decode(errors="replace") +
                                   (self.folder / "console.txt").read_text(errors="replace"))
            finally:
                if proc.poll() is None:
                    shutdown = self.query("SHUTDOWN", check=False)
                    if shutdown.returncode:
                        proc.kill()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()

    def client(self, tool, *args, **kwargs):
        return run(tool, "--protocol=PIPE", "--host=.", f"--socket={self.pipe}",
                   "--user=root", *args, **kwargs)

    def query(self, sql, check=True):
        return self.client("mysql", "-N", "-B", "--binary-mode", data=sql.encode(), check=check)

    def rows(self, sql):
        return self.query(sql).stdout.decode().strip().splitlines()


def check(actual, expected):
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


def deduct(amount, attempt, hold=0):
    return f"""USE {DB};
    START TRANSACTION;
    SELECT balance, next_seq INTO @balance,@seq FROM account WHERE id=1 FOR UPDATE;
    DO SLEEP({hold});
    INSERT INTO activity VALUES (1,'2026-01-01 12:00:00.000000',@seq,-{amount},NULL);
    UPDATE account SET balance=@balance-{amount}, next_seq=@seq+1 WHERE id=1;
    INSERT INTO audit VALUES (1,@seq);
    INSERT INTO outcome VALUES (1,'{attempt}',@seq);
    COMMIT;"""


def prepare_prisma():
    folder = WORK / "prisma"
    folder.mkdir()
    for filename in ("prisma_probe.mjs", "schema.prisma"):
        shutil.copyfile(Path(__file__).with_name(filename), folder / filename)
    (folder / "package.json").write_text('{"private":true}', encoding="utf-8")
    npm = shutil.which("npm.cmd")
    subprocess.run([npm, "install", "--save-exact", "--no-fund", "--no-audit", "prisma@6.19.3",
                    "@prisma/client@6.19.3"], cwd=folder, check=True, timeout=180)
    audit = subprocess.run([npm, "audit", "--json"], cwd=folder, capture_output=True, timeout=45)
    vulnerabilities = json.loads(audit.stdout).get("vulnerabilities")
    if vulnerabilities is None:
        print("npm audit did not return vulnerability data", flush=True)
    else:
        print("npm audit:", {name: entry["severity"] for name, entry in vulnerabilities.items()}, flush=True)
    subprocess.run([npm, "exec", "--offline", "--", "prisma", "generate"], cwd=folder,
                   check=True, timeout=90)
    return folder


def probe_prisma(folder, source):
    password = uuid.uuid4().hex
    source.query(f"""USE {DB}; INSERT INTO account VALUES (4,9007199254740993,1);
        CREATE USER 'duit_probe'@'127.0.0.1' IDENTIFIED BY '{password}';
        GRANT SELECT, UPDATE ON {DB}.account TO 'duit_probe'@'127.0.0.1';
        GRANT SELECT, INSERT ON {DB}.audit TO 'duit_probe'@'127.0.0.1';""")
    env = dict(os.environ, DUIT_PROBE_URL=f"mysql://duit_probe:{password}@127.0.0.1:{source.port}/{DB}")
    subprocess.run(["node", "prisma_probe.mjs"], cwd=folder, env=env, check=True, timeout=30)


def probe_sqlx(source):
    password = uuid.uuid4().hex
    source.query(f"""USE {DB};
        INSERT INTO account VALUES (4,9007199254740993,1),(5,0,1),(6,0,1),(7,0,1),(8,0,1);
        CREATE USER 'duit_sqlx'@'127.0.0.1' IDENTIFIED BY '{password}' REQUIRE SSL;
        GRANT SELECT, UPDATE ON {DB}.account TO 'duit_sqlx'@'127.0.0.1';
        GRANT SELECT, INSERT ON {DB}.activity TO 'duit_sqlx'@'127.0.0.1';
        GRANT SELECT, INSERT ON {DB}.audit TO 'duit_sqlx'@'127.0.0.1';
        GRANT SELECT, INSERT ON {DB}.outcome TO 'duit_sqlx'@'127.0.0.1';""")
    tls = urlencode({"ssl-mode": "verify_ca", "ssl-ca": (source.folder / "ca.pem").as_posix()})
    url = f"mysql://duit_sqlx:{password}@127.0.0.1:{source.port}/{DB}?{tls}"
    env = dict(os.environ, DUIT_PROBE_URL=url, DATABASE_URL=url, SQLX_OFFLINE="false")
    cargo = shutil.which("cargo")
    crate = Path(__file__).resolve().with_name("sqlx-probe")
    subprocess.run([cargo, "run", "--locked"], cwd=crate, env=env, check=True, timeout=360)


def main(prisma=None, sqlx=False):
    port = None
    if prisma or sqlx:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
    with Instance(WORK / "source", 101, port).start() as source:
        print("MySQL", source.rows("SELECT VERSION()")[0], flush=True)
        source.query(f"""CREATE DATABASE {DB}; USE {DB};
        CREATE TABLE account (id INT PRIMARY KEY, balance BIGINT, next_seq BIGINT) ENGINE=InnoDB;
        CREATE TABLE activity (owner INT, effective_at DATETIME(6), seq BIGINT, delta BIGINT,
          target BIGINT, PRIMARY KEY (owner,effective_at,seq), UNIQUE KEY (owner,seq)) ENGINE=InnoDB;
        CREATE TABLE audit (owner INT, seq BIGINT, PRIMARY KEY(owner,seq)) ENGINE=InnoDB;
        CREATE TABLE outcome (owner INT, attempt VARCHAR(30), seq BIGINT,
          PRIMARY KEY(owner,attempt)) ENGINE=InnoDB;
        INSERT INTO account VALUES (1,0,2),(2,0,1);
        INSERT INTO activity VALUES (1,'2026-01-01 12:00:00.000000',1,0,0);""")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(source.rows, deduct(10, "first", 0.4))
            second = pool.submit(source.rows, deduct(20, "second"))
            first.result()
            second.result()
        invariant = f"""USE {DB}; SELECT balance,next_seq FROM account WHERE id=1;
            SELECT COUNT(*) FROM activity WHERE owner=1;
            SELECT COUNT(*) FROM audit WHERE owner=1;
            SELECT COUNT(*) FROM outcome WHERE owner=1;"""
        check(source.rows(invariant), ["-30\t4", "3", "2", "2"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(source.rows, f"""USE {DB}; START TRANSACTION;
                SELECT id FROM account WHERE id=1 FOR UPDATE; DO SLEEP(4); COMMIT;""")
            for _ in range(50):
                if source.rows("SELECT COUNT(*) FROM information_schema.processlist WHERE STATE='User sleep'") == ["1"]:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("lock holder did not enter sleep")
            blocked = source.query(f"""USE {DB}; SET innodb_lock_wait_timeout=1;
                START TRANSACTION; INSERT INTO audit VALUES (1,999);
                SELECT id FROM account WHERE id=1 FOR UPDATE; COMMIT;""", check=False)
            check(b"ERROR 1205" in blocked.stderr, True)
            source.query(f"USE {DB}; UPDATE account SET balance=1 WHERE id=2;")
            holder.result()
        check(source.rows(invariant), ["-30\t4", "3", "2", "2"])
        def lock_pair(first, second):
            return source.query(f"""USE {DB}; START TRANSACTION;
                SELECT id FROM account WHERE id={first} FOR UPDATE;
                INSERT INTO audit VALUES ({first},998);
                DO SLEEP(1);
                SELECT id FROM account WHERE id={second} FOR UPDATE;
                ROLLBACK;""", check=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: lock_pair(*pair), [(1, 2), (2, 1)]))
        check(sorted(result.returncode for result in results), [0, 1])
        check(sum(b"ERROR 1213" in result.stderr for result in results), 1)
        check(source.rows(f"USE {DB}; SELECT COUNT(*) FROM audit WHERE seq=998;"), ["0"])
        duplicate = source.query(deduct(10, "first"), check=False)
        check(b"ERROR 1062" in duplicate.stderr, True)
        check(source.rows(invariant), ["-30\t4", "3", "2", "2"])
        source.query(f"""USE {DB};
            SET SESSION cte_max_recursion_depth=10001;
            INSERT INTO activity (owner,effective_at,seq,delta,target)
            WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM numbers WHERE n<10000)
            SELECT 3,'2026-01-02',n,1,NULL FROM numbers; ANALYZE TABLE activity;""")
        sql = f"""USE {DB}; EXPLAIN FORMAT=JSON
            SELECT effective_at,seq,delta,target FROM activity WHERE owner=1 ORDER BY effective_at,seq;"""
        plan = json.loads(source.rows(sql)[0].replace(r"\n", "\n"))["query_block"]
        ordered_plan = plan.get("ordering_operation", plan)
        print("Chronology query plan:", ordered_plan["table"].get("key"),
              "filesort:", ordered_plan.get("using_filesort", False))
        check(source.rows(f"USE {DB}; SELECT seq FROM activity WHERE owner=1 ORDER BY effective_at,seq;"),
              ["1", "2", "3"])
        print("Lock, timeout and deadlock rollback, independent owner and duplicate rollback OK")
        if prisma:
            probe_prisma(prisma, source)
        if sqlx:
            probe_sqlx(source)

        backup = source.client("mysqldump", "--single-transaction", "--source-data=2",
                               "--set-gtid-purged=OFF", "--databases", DB).stdout
        coordinates = re.search(
            rb"(?:SOURCE|MASTER)_LOG_FILE\s*=\s*'([^']+)',\s*(?:SOURCE|MASTER)_LOG_POS\s*=\s*(\d+)",
            backup,
        )
        if coordinates is None:
            raise RuntimeError("mysqldump did not emit usable binary-log coordinates")
        filename, start = (part.decode() for part in coordinates.groups())
        source.query(deduct(5, "archived"))
        head, stop, *_ = source.rows("SHOW MASTER STATUS")[0].split("\t")
        check(head, filename)
        source.query("FLUSH BINARY LOGS")
        check(source.rows("SHOW MASTER STATUS")[0].split("\t")[0] != filename, True)
        source.query(deduct(7, "acknowledged-missing"))
        check(source.rows(invariant), ["-42\t6", "5", "4", "4"])
        log_copy = WORK / filename
        shutil.copyfile(source.folder / filename, log_copy)
        with log_copy.open("rb") as copy, (source.folder / filename).open("rb") as original:
            check(hashlib.file_digest(copy, "sha256").digest(),
                  hashlib.file_digest(original, "sha256").digest())

    started = time.monotonic()
    with Instance(WORK / "restore", 102).start() as restored:
        restored.client("mysql", "--binary-mode", data=backup)
        check(restored.rows(invariant), ["-30\t4", "3", "2", "2"])
        replay = run("mysqlbinlog", f"--start-position={start}", f"--stop-position={stop}",
                     "--verify-binlog-checksum", str(log_copy)).stdout
        restored.client("mysql", "--binary-mode", data=replay)
        check(restored.rows(invariant), ["-35\t5", "4", "3", "3"])
        check(restored.rows(f"""USE {DB}; SELECT attempt FROM outcome
            WHERE attempt IN ('archived','acknowledged-missing');"""), ["archived"])
        check(restored.rows(f"""USE {DB}; SELECT SUM(delta),SUM(target IS NOT NULL)
            FROM activity WHERE owner=1;"""), ["-35\t1"])
        print(f"PITR {filename}:{start}..{stop}, restore plus data checks {time.monotonic()-started:.2f}s")


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="duit-phase0-mysql-", dir=Path.cwd()) as work:
            WORK = Path(work)
            if sys.argv[1:] not in ([], ["--prisma"], ["--sqlx"]):
                raise SystemExit("usage: mysql_probe.py [--prisma|--sqlx]")
            main(prepare_prisma() if sys.argv[1:] == ["--prisma"] else None,
                 sqlx=sys.argv[1:] == ["--sqlx"])
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.stderr.decode(errors="replace") or str(error)) from error
