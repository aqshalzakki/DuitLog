"""Run Duit Log locally for manual testing in a browser: a private MySQL in .dev-local/ (kept between
runs, bound to 127.0.0.1 only), S3 storage for evidence (SeaweedFS in Docker, data in .dev-local/s3),
a fake SMTP relay that prints verification/reset codes to this terminal, the API, the worker and Vite at
http://localhost:5173. Ctrl+C stops everything. Development only:
the MySQL root account has no password and must never hold real data.

    python tests/dev_local.py          start (first run initializes the database)
    python tests/dev_local.py --reset  delete .dev-local/ and start from an empty database
    python tests/dev_local.py --smoke  self-check: start, register one account, wait for its code, stop
"""
import argparse
import base64
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import re
import shutil
import socket
import socketserver
import subprocess
import sys
from threading import Thread
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".dev-local"
MYSQL_PORT, API_PORT, WEB_PORT, S3_PORT = 3307, 3000, 5173, 8333
S3_IMAGE, S3_CONTAINER = "chrislusf/seaweedfs:4.53", "duitlog-dev-s3"
DB = "duitlog"
MAILS = []


class Mailbox(socketserver.StreamRequestHandler):
    """Accepts every message and prints its subject and code; nothing leaves this machine."""

    def reply(self, line):
        self.wfile.write(line + b"\r\n")
        self.wfile.flush()

    def handle(self):
        self.reply(b"220 dev-local ESMTP")
        while command := self.rfile.readline():
            verb = command.split(maxsplit=1)[0].upper() if command.strip() else b""
            if verb == b"EHLO":
                self.reply(b"250-dev-local\r\n250 8BITMIME")
            elif verb == b"DATA":
                self.reply(b"354 End of message")
                lines = []
                for line in self.rfile:
                    if line == b".\r\n":
                        break
                    lines.append(line)
                show(BytesParser(policy=policy.default).parsebytes(b"".join(lines)))
                self.reply(b"250 accepted")
            elif verb == b"QUIT":
                self.reply(b"221 closing")
                return
            else:
                self.reply(b"250 ok")


def show(message):
    body = message.get_body(preferencelist=("plain",)).get_content()
    code = next((line for line in body.splitlines() if re.fullmatch(r"[A-Za-z0-9_-]{43}", line)), None)
    MAILS.append(code)
    print(f"\n[email] To: {message['To']} | {message['Subject']}\n[email] Kode: {code or '(lihat isi)'}\n", flush=True)
    with (DATA / "mail.log").open("a", encoding="utf8") as log:
        log.write(f"To: {message['To']}\nSubject: {message['Subject']}\n{body}\n---\n")


def free(port, host="127.0.0.1"):
    """No listener on host:port; "localhost" tries every address it resolves to (Vite may bind ::1 only)."""
    try:
        socket.create_connection((host, port), timeout=1).close()
        return False
    except OSError:
        return True


def wait(check, what, seconds=60):
    for _ in range(seconds * 4):
        if check():
            return
        time.sleep(0.25)
    raise SystemExit(f"{what} tidak siap. Lihat log di {DATA}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="hapus .dev-local/ lalu mulai dari database kosong")
    parser.add_argument("--smoke", action="store_true", help="cek mandiri: daftar satu akun, tunggu kodenya, berhenti")
    args = parser.parse_args()
    mysqld = shutil.which("mysqld")
    if not mysqld:
        raise SystemExit("mysqld tidak ditemukan di PATH (MySQL 8.x).")
    mysqld = Path(mysqld).resolve()
    for port, name, host in ((MYSQL_PORT, "MySQL", "127.0.0.1"), (API_PORT, "API", "127.0.0.1"), (WEB_PORT, "Vite", "localhost"),
                             (S3_PORT, "S3", "127.0.0.1")):
        if not free(port, host):
            raise SystemExit(f"Port {port} ({name}) sedang dipakai. Hentikan proses itu dulu.")
    if args.reset and DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(exist_ok=True)

    secrets_file = DATA / "secrets.json"
    secrets = json.loads(secrets_file.read_text()) if secrets_file.exists() else {}
    # One mail key per data folder, so codes stay valid across restarts; same for the storage keys.
    secrets.setdefault("mailKey", base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="))
    secrets.setdefault("s3Access", "dev" + uuid.uuid4().hex[:16])
    secrets.setdefault("s3Secret", uuid.uuid4().hex + uuid.uuid4().hex)
    secrets_file.write_text(json.dumps(secrets))
    mail_key = secrets["mailKey"]
    (DATA / "s3").mkdir(exist_ok=True)
    (DATA / "s3.json").write_text(json.dumps({"identities": [{"name": "dev", "credentials": [
        {"accessKey": secrets["s3Access"], "secretKey": secrets["s3Secret"]}], "actions": ["Admin", "Read", "Write", "List"]}]}))

    datadir = DATA / "mysql"
    if not datadir.exists():
        print("Menyiapkan database baru...", flush=True)
        subprocess.run([mysqld, "--no-defaults", f"--datadir={datadir}", "--initialize-insecure"], check=True,
                       capture_output=True, timeout=120)

    print("Membangun backend...", flush=True)
    subprocess.run(["cargo", "build", "--locked", "--bin", "api", "--bin", "worker"], cwd=ROOT, check=True)
    if not (ROOT / "frontend/node_modules").exists():
        subprocess.run(["npm.cmd", "ci"], cwd=ROOT / "frontend", check=True)

    procs = []
    started_s3 = False

    def start(args, log, env=None):
        output = (DATA / log).open("wb")
        procs.append(subprocess.Popen(args, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT))

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Mailbox) as smtp:
        Thread(target=smtp.serve_forever, daemon=True).start()
        try:
            start([mysqld, "--no-defaults", f"--datadir={datadir}", "--bind-address=127.0.0.1", f"--port={MYSQL_PORT}",
                   "--mysqlx=OFF", "--console"], "mysql.log")
            mysql = mysqld.with_name("mysql.exe")
            query = lambda sql: subprocess.run([mysql, "--no-defaults", "-h127.0.0.1", f"-P{MYSQL_PORT}", "-uroot",
                                                "-N", "-e", sql], capture_output=True, timeout=10)
            wait(lambda: query("SELECT 1").returncode == 0, "MySQL")
            subprocess.run(["docker", "rm", "-f", S3_CONTAINER], capture_output=True, timeout=60)
            subprocess.run(["docker", "run", "-d", "--rm", "--name", S3_CONTAINER, "-p", f"127.0.0.1:{S3_PORT}:8333",
                            "-v", f"{DATA / 's3'}:/data", "-v", f"{DATA / 's3.json'}:/etc/duit-s3.json:ro", S3_IMAGE,
                            "server", "-dir=/data", "-s3", "-s3.config=/etc/duit-s3.json"],
                           check=True, capture_output=True, timeout=120)
            started_s3 = True
            query(f"CREATE DATABASE IF NOT EXISTS {DB}")

            env = dict(os.environ, DATABASE_URL=f"mysql://root@127.0.0.1:{MYSQL_PORT}/{DB}",
                       DUIT_MAIL_KEY=mail_key, DUIT_APP_ORIGIN=f"http://localhost:{WEB_PORT}",
                       DUIT_API_ADDR=f"127.0.0.1:{API_PORT}", DUIT_SMTP_MODE="local", DUIT_SMTP_HOST="127.0.0.1",
                       DUIT_SMTP_PORT=str(smtp.server_address[1]), DUIT_MAIL_FROM="duit@dev.local",
                       DUIT_DEV_API=f"http://127.0.0.1:{API_PORT}", DUIT_S3_ENDPOINT=f"http://127.0.0.1:{S3_PORT}",
                       DUIT_S3_BUCKET="duit-evidence", DUIT_S3_ACCESS_KEY=secrets["s3Access"],
                       DUIT_S3_SECRET_KEY=secrets["s3Secret"])
            subprocess.run([ROOT / "target/debug/api.exe", "migrate"], env=env, check=True, timeout=60)
            # The S3 gateway answers before its filer is ready; retry the bucket setup for a while.
            wait(lambda: subprocess.run([ROOT / "target/debug/api.exe", "init-storage"], env=env,
                                        capture_output=True, timeout=30).returncode == 0, "S3", 90)
            start([ROOT / "target/debug/api.exe"], "api.log", env)
            start([ROOT / "target/debug/worker.exe"], "worker.log", env)
            start(["node", ROOT / "frontend/node_modules/vite/bin/vite.js", "--host", "localhost", "--port",
                   str(WEB_PORT), "--strictPort", ROOT / "frontend"], "vite.log", env)
            wait(lambda: not free(API_PORT) and not free(WEB_PORT, "localhost"), "API/Vite")
            print(f"\nSiap: buka http://localhost:{WEB_PORT}\n"
                  "Daftar akun baru; kode verifikasi muncul di terminal ini (juga di .dev-local/mail.log).\n"
                  "Ctrl+C untuk berhenti. Data tetap ada untuk run berikutnya (--reset untuk mengosongkan).\n",
                  flush=True)
            if args.smoke:
                origin = f"http://localhost:{WEB_PORT}"
                body = json.dumps({"name": "Smoke", "email": f"smoke-{uuid.uuid4().hex[:8]}@dev.local",
                                   "password": "smoke password 12345"}).encode()
                request = urllib.request.Request(origin + "/api/v1/auth/register", body, method="POST", headers={
                    "Content-Type": "application/json", "Origin": origin, "X-Duit-CSRF": "1"})
                with urllib.request.urlopen(request, timeout=15) as reply:  # through the Vite proxy
                    if reply.status != 202:
                        raise SystemExit(f"Register gagal: {reply.status}")
                wait(lambda: any(MAILS), "Email verifikasi", 30)
                print("Smoke OK: Vite -> API -> MySQL -> worker -> SMTP", flush=True)
                return 0
            while all(p.poll() is None for p in procs):
                time.sleep(1)
            raise SystemExit("Salah satu proses berhenti. Lihat log di .dev-local/.")
        except KeyboardInterrupt:
            print("\nMenghentikan...", flush=True)
        finally:
            query_ok = procs and procs[0].poll() is None
            for p in reversed(procs[1:]):
                p.terminate()
            if query_ok:
                subprocess.run([mysqld.with_name("mysqladmin.exe"), "--no-defaults", "-h127.0.0.1",
                                f"-P{MYSQL_PORT}", "-uroot", "shutdown"], capture_output=True, timeout=30)
            for p in procs:
                try:
                    p.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    p.kill()
            if started_s3:
                subprocess.run(["docker", "stop", "-t", "5", S3_CONTAINER], capture_output=True, timeout=60)
            smtp.shutdown()


if __name__ == "__main__":
    sys.exit(main())
