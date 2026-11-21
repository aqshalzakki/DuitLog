"""Measure three disposable containers and validate the synthetic export."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import math
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Event
import time
import uuid
from xml.etree import ElementTree
from zipfile import ZipFile


FOLDER = Path(__file__).resolve().parent
ROWS = 150_000
BASE_AMOUNT = 9_007_199_254_740_992
SERVICES = {"db": 1024, "api": 256, "worker": 256}


def wait_for(operation, timeout=90):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = operation()
        if result is not None:
            return result
        time.sleep(0.25)
    raise TimeoutError("probe service did not become ready")


def request(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        started = time.perf_counter()
        connection.request("GET", "/report")
        result = connection.getresponse()
        body = result.read()
        if result.status != 200 or body != str(ROWS).encode():
            raise RuntimeError(f"unexpected report response {result.status} {body!r}")
        return (time.perf_counter() - started) * 1000
    finally:
        connection.close()


def load(port, duration, started=None, stopped=None):
    deadline = time.monotonic() + duration

    def client():
        samples = []
        while time.monotonic() < deadline and (stopped is None or not stopped.is_set()):
            samples.append(request(port))
        return samples

    with ThreadPoolExecutor(max_workers=8) as pool:
        requests = [pool.submit(client) for _ in range(8)]
        if started is not None:
            started.set()
        samples = sorted(sample for result in requests for sample in result.result())
    p95 = samples[math.ceil(len(samples) * .95) - 1]
    return f"{len(samples)} responses, p95 {p95:.2f} ms"


def check_export(path):
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(path) as archive, archive.open("xl/worksheets/sheet1.xml") as sheet:
        rows = 0
        for _, row in ElementTree.iterparse(sheet, events=("end",)):
            if row.tag != namespace + "row":
                continue
            cells = list(row)
            if rows == 0:
                assert [cell.findtext(f".//{namespace}t") for cell in cells] == ["Sequence", "IDR"]
            else:
                assert cells[0].findtext(namespace + "v") == str(rows)
                assert cells[1].findtext(f".//{namespace}t") == str(BASE_AMOUNT + rows)
            rows += 1
            row.clear()
    assert rows == ROWS + 1
    return path.stat().st_size


def main():
    name = "duit-val04-" + uuid.uuid4().hex[:10]
    env = dict(os.environ, DUIT_RESOURCE_PASSWORD=uuid.uuid4().hex,
               DUIT_RESOURCE_IMAGE="duit-phase0-resource:val04")

    def compose(*args, data=None, check=True):
        return subprocess.run(
            ["docker", "compose", "-p", name, "-f", str(FOLDER / "compose.yaml"), *args],
            env=env, input=data, text=True, capture_output=True, check=check, timeout=120,
        )

    def db(sql, check=True):
        return compose("exec", "-T", "db", "sh", "-ec",
                       'MYSQL_PWD="$MYSQL_PASSWORD" mysql --protocol=TCP -h127.0.0.1 -u "$MYSQL_USER" "$MYSQL_DATABASE" -N',
                       data=sql, check=check)

    def metrics(service):
        script = """
        awk '/^VmRSS:|^VmHWM:/{print}' /proc/1/status
        for f in memory.current memory.peak memory.max memory.swap.max; do
          printf '%s ' "$f"
          cat "/sys/fs/cgroup/$f"
        done
        awk '$1=="oom_kill"{print}' /sys/fs/cgroup/memory.events
        """
        output = compose("exec", "-T", service, "sh", "-ec", script).stdout
        assert f"memory.max {SERVICES[service] * 1024**2}" in output
        assert "memory.swap.max 0" in output and "oom_kill 0" in output
        print(f"{service}: {', '.join(output.splitlines())}", flush=True)

    try:
        compose("up", "-d", "db")
        wait_for(lambda: True if db("SELECT 1;", check=False).returncode == 0 else None)
        print("MySQL", db("SELECT VERSION();").stdout.strip(), flush=True)
        db(f"""CREATE TABLE ledger (
            owner INT UNSIGNED, seq INT UNSIGNED, amount BIGINT NOT NULL,
            PRIMARY KEY(owner,seq)) ENGINE=InnoDB;
            SET SESSION cte_max_recursion_depth={ROWS+1};
            INSERT INTO ledger
            WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<{ROWS})
            SELECT 1,i,{BASE_AMOUNT}+i FROM n;
            INSERT INTO ledger VALUES (2,1,-999);""")
        compose("up", "-d", "api", "worker")
        port = int(compose("port", "api", "8080").stdout.strip().rsplit(":", 1)[1])

        def ready():
            try:
                request(port)
            except (OSError, RuntimeError):
                return None
            return True if compose("exec", "-T", "worker", "test", "-f", "/tmp/ready",
                                   check=False).returncode == 0 else None

        wait_for(ready)
        print("Idle after seed", flush=True)
        for service in SERVICES:
            metrics(service)
        print("API only:", load(port, 3), flush=True)

        def exported():
            result = compose("exec", "-T", "worker", "cat", "/tmp/done", check=False)
            return result.stdout.strip() if result.returncode == 0 else None

        started, stopped = Event(), Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(load, port, 10, started, stopped)
            if not started.wait(timeout=5):
                raise TimeoutError("API load did not start")
            export_start = time.monotonic()
            compose("exec", "-T", "worker", "touch", "/tmp/start")
            assert wait_for(exported, timeout=45) == str(ROWS)
            assert not active.done(), "increase load duration to cover the entire export"
            stopped.set()
            print(f"Export ready after {time.monotonic() - export_start:.2f}s", flush=True)
            print("API during export:", active.result(), flush=True)
        print("After load and export", flush=True)
        for service in SERVICES:
            metrics(service)
        with tempfile.TemporaryDirectory(prefix="duit-val04-", dir=FOLDER) as folder:
            path = Path(folder) / "probe.xlsx"
            compose("cp", "worker:/tmp/probe.xlsx", str(path))
            print(f"XLSX verified: {ROWS} ordered rows, exact IDR strings, {check_export(path)} bytes")
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.stderr or error.stdout or "Docker command failed") from error
    finally:
        compose("down", "--volumes", "--timeout", "5")


if __name__ == "__main__":
    main()
