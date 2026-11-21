"""HTTP and email regression against a disposable Windows MySQL 8.0 server."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
import http.client
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
from threading import Thread
import time
from urllib.parse import urlencode
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/phase0"))
import mysql_probe

PASSWORD = "synthetic-password-1"
NEW_PASSWORD = "synthetic-password-2"
DB = "duit_phase1_fixture"
ALICE = "alice@example.test"
BOB = "bob@example.test"


def check(actual, expected):
    if actual != expected:
        raise AssertionError(f"Expected {expected!r}, got {actual!r}")


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(action, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = action()
        if result is not None:
            return result
        time.sleep(0.1)
    raise TimeoutError("Expected fixture state did not arrive")


class MailCapture(socketserver.StreamRequestHandler):
    def reply(self, response):
        self.wfile.write(response + b"\r\n")
        self.wfile.flush()

    def handle(self):
        self.reply(b"220 local.test ESMTP")
        while command := self.rfile.readline():
            verb = command.split(maxsplit=1)[0].upper()
            if verb == b"EHLO":
                self.reply(b"250-local.test\r\n250 8BITMIME")
            elif verb == b"DATA":
                self.reply(b"354 End of message")
                lines = []
                for line in self.rfile:
                    if line == b".\r\n":
                        break
                    lines.append(line)
                if self.server.fail_first:
                    self.server.fail_first = False
                    self.reply(b"451 temporary fixture error")
                else:
                    self.server.mail.append(BytesParser(policy=policy.default).parsebytes(b"".join(lines)))
                    self.reply(b"250 accepted")
            elif verb == b"QUIT":
                self.reply(b"221 closing")
                return
            else:
                self.reply(b"250 ok")


@contextmanager
def smtp():
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), MailCapture) as server:
        server.mail = []
        server.fail_first = True
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def mail_token(server, address, subject, index=0):
    def find():
        matches = [msg for msg in server.mail if address in msg["To"] and subject in msg["Subject"]]
        if len(matches) <= index:
            return None
        body = matches[index].get_body(preferencelist=("plain",)).get_content()
        token = next((line for line in body.splitlines() if re.fullmatch(r"[A-Za-z0-9_-]{43}", line)), None)
        if token is None or "token=" in body:
            raise AssertionError("Expected a separate code and URL")
        return token
    return wait_for(find)


@contextmanager
def process(args, env, logfile):
    with logfile.open("wb") as output:
        proc = subprocess.Popen(args, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            yield proc
        except Exception:
            print(logfile.read_text(errors="replace"))
            raise
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)


class Client:
    def __init__(self, port, origin):
        self.port, self.origin = port, origin
        self.cookies = {}
        self.set_cookies = []

    def request(self, method, path, status, *, data=None, csrf=True, origin=None):
        headers = {"Cookie": "; ".join(f"{key}={value}" for key, value in self.cookies.items())}
        if csrf:
            headers.update({"Origin": origin or self.origin, "X-Duit-CSRF": "1"})
        if data is not None:
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, "/api/v1" + path, json.dumps(data) if data is not None else None, headers)
            response = conn.getresponse()
            raw = response.read()
            if isinstance(status, tuple):
                assert response.status in status
            else:
                check(response.status, status)
            check(response.headers["Cache-Control"], "no-store")
            self.set_cookies = response.headers.get_all("Set-Cookie", [])
            for header in self.set_cookies:
                for key, cookie in SimpleCookie(header).items():
                    if cookie["max-age"] == "0":
                        self.cookies.pop(key, None)
                    else:
                        self.cookies[key] = cookie.value
            value = json.loads(raw) if raw else None
            if response.status >= 400:
                assert set(("code", "message", "requestId")).issubset(value)
                assert PASSWORD not in raw.decode()
            return response.status if isinstance(status, tuple) else value
        finally:
            conn.close()

    def login(self, address, password=PASSWORD, device="Browser", status=204):
        return self.request("POST", "/auth/login", status,
                            data={"email": address, "password": password, "deviceName": device})


def verify_api(database, env, smtp_server, client, work):
    user = {"name": "Alice", "email": ALICE, "password": PASSWORD}
    check(client.request("POST", "/auth/register", 403, data=user, csrf=False)["code"], "CSRF_REJECTED")
    check(client.request("POST", "/auth/register", 403, data=user, origin="https://other.invalid")["code"], "CSRF_REJECTED")
    check(client.request("POST", "/auth/register", 400, data={**user, "password": "short"})["fieldErrors"].keys(),
          {"password"})
    check(client.request("POST", "/auth/register", 202, data=user), None)
    check(client.request("POST", "/auth/register", 202, data={**user, "name": "Other"}), None)
    check(client.set_cookies, [])
    check(database.rows(f"USE {DB}; SELECT COUNT(*) FROM mail_jobs;"), ["1"])
    check(len(smtp_server.mail), 0)
    client.login(ALICE, device="Laptop")
    assert len(client.set_cookies) == 2
    assert all(all(flag in header for flag in ("__Host-", "HttpOnly", "Secure", "Path=/", "SameSite=Strict"))
               for header in client.set_cookies)
    first = client.request("GET", "/me", 200)
    check((first["name"], first["emailVerified"]), ("Alice", False))
    check(client.request("GET", "/account/verified", 403)["code"], "EMAIL_VERIFICATION_REQUIRED")
    check(database.rows(f"USE {DB}; SELECT expires_at-created_at FROM device_sessions;"), ["2592000"])

    worker = ROOT / "target/debug/worker.exe"
    with process([worker], env, work / "worker.log"):
        wait_for(lambda: True if database.rows(
            f"USE {DB}; SELECT COUNT(*) FROM mail_jobs WHERE attempts=1 AND lease_token IS NULL;") == ["1"] else None)
        database.query(f"USE {DB}; UPDATE mail_jobs SET next_run_at=UNIX_TIMESTAMP();")
        first_code = mail_token(smtp_server, ALICE, "Verifikasi")
        check(database.rows(f"USE {DB}; SELECT attempts FROM mail_jobs;"), ["2"])
        check(database.rows(f"""USE {DB}; SELECT COUNT(*) FROM auth_challenges
            WHERE digest=UNHEX(SHA2('{first_code}',256));"""), ["1"])
        client.request("POST", "/auth/resend-verification", 202)
        second_code = mail_token(smtp_server, ALICE, "Verifikasi", index=1)
        assert first_code != second_code

        other = Client(client.port, client.origin)
        other.request("POST", "/auth/register", 202, data={**user, "name": "Bob", "email": BOB})
        other.login(BOB)
        check(other.request("GET", "/me", 200)["email"], BOB)
        expired_code = mail_token(smtp_server, BOB, "Verifikasi")
        database.query(f"""USE {DB}; UPDATE auth_challenges c JOIN accounts a ON a.id=c.owner_id
            SET c.expires_at=UNIX_TIMESTAMP()-1 WHERE a.email='{BOB}';""")
        other.request("POST", "/auth/verify-email", 400, data={"token": expired_code})
        for _ in range(3):
            other.request("POST", "/auth/resend-verification", 202)
        check(other.request("POST", "/auth/resend-verification", 429)["code"], "RATE_LIMITED")
        check(other.request("POST", "/auth/verify-email", 400, data={"token": second_code})["code"], "INVALID_CODE")
        client.request("POST", "/auth/verify-email", 204, data={"token": second_code})
        client.request("POST", "/auth/verify-email", 400, data={"token": first_code})
        client.request("POST", "/auth/verify-email", 400, data={"token": second_code})
        client.request("GET", "/account/verified", 204)
        other_id = other.request("GET", "/sessions", 200)[0]["id"]
        check(client.request("DELETE", "/sessions/" + other_id, 404)["code"], "NOT_FOUND")
        check(client.request("DELETE", "/sessions/" + str(uuid.uuid4()), 404)["code"], "NOT_FOUND")

        phone = Client(client.port, client.origin)
        phone.login(ALICE, device="HP")
        check({item["label"] for item in client.request("GET", "/sessions", 200)}, {"Laptop", "HP"})
        expiry = database.rows(f"USE {DB}; SELECT expires_at FROM device_sessions WHERE label='HP';")
        old = Client(client.port, client.origin)
        old.cookies = dict(phone.cookies)
        database.query(f"USE {DB}; UPDATE device_sessions SET access_expires_at=UNIX_TIMESTAMP()-1 WHERE label='HP';")
        phone.request("GET", "/me", 401)
        phone.request("POST", "/auth/refresh", 204)
        check(database.rows(f"USE {DB}; SELECT expires_at FROM device_sessions WHERE label='HP';"), expiry)
        check(phone.request("GET", "/me", 200)["id"], first["id"])
        reused = old.request("POST", "/auth/refresh", 401)
        check(reused["code"], "UNAUTHORIZED")
        phone.request("GET", "/me", 401)
        client.request("GET", "/me", 200)

        phone.login(ALICE, device="Parallel")
        replicas = [Client(client.port, client.origin) for _ in range(2)]
        for replica in replicas:
            replica.cookies = dict(phone.cookies)

        def rotate(replica):
            return replica.request("POST", "/auth/refresh", (204, 401))

        with ThreadPoolExecutor(max_workers=2) as threads:
            check(sorted(threads.map(rotate, replicas)), [204, 401])
        for replica in replicas:
            replica.request("GET", "/me", 401)

        phone.login(ALICE, device="Tablet")
        tablet = next(item for item in client.request("GET", "/sessions", 200) if item["label"] == "Tablet")
        client.request("DELETE", "/sessions/" + tablet["id"], 204)
        phone.request("GET", "/me", 401)
        phone.request("POST", "/auth/refresh", 401)
        phone.login(ALICE, device="Expired")
        database.query(f"USE {DB}; UPDATE device_sessions SET expires_at=UNIX_TIMESTAMP()-1 WHERE label='Expired';")
        phone.request("GET", "/me", 401)
        phone.request("POST", "/auth/refresh", 401)

        phone.login(ALICE, device="Reset")
        check(client.request("POST", "/auth/forgot-password", 202, data={"email": ALICE}), None)
        check(client.request("POST", "/auth/forgot-password", 202, data={"email": "unknown@example.test"}), None)
        reset = {"token": mail_token(smtp_server, ALICE, "Atur ulang"), "password": NEW_PASSWORD}
        client.request("POST", "/auth/reset-password", 204, data=reset)
        client.request("POST", "/auth/reset-password", 400, data=reset)
        client.request("GET", "/me", 401)
        phone.request("POST", "/auth/refresh", 401)
        client.login(ALICE, status=401)
        client.login(ALICE, password=NEW_PASSWORD)
        client.request("GET", "/account/verified", 204)
        client.request("POST", "/auth/logout-all", 204)
        client.request("GET", "/me", 401)
        check(other.request("GET", "/me", 200)["email"], BOB)
        other.request("POST", "/auth/logout", 204)
        other.request("GET", "/me", 401)
        print("HTTP auth, cookies, CSRF, SMTP failure/retry, verification, cross-tenant access, expiry and revocation OK", flush=True)
        yield


def main(browser, finance=False):
    with tempfile.TemporaryDirectory(prefix="duit-phase1-", dir=ROOT) as workdir:
        work = Path(workdir)
        mysql_probe.WORK = work
        with mysql_probe.Instance(work / "data", 121, available_port()).start() as database, smtp() as mail:
            password = uuid.uuid4().hex
            database.query(f"""CREATE DATABASE {DB}; CREATE USER 'duit_fixture'@'127.0.0.1'
                IDENTIFIED BY '{password}' REQUIRE SSL; GRANT ALL ON {DB}.* TO 'duit_fixture'@'127.0.0.1';""")
            tls = urlencode({"ssl-mode": "verify_ca", "ssl-ca": (database.folder / "ca.pem").as_posix()})
            api_port, web_port = available_port(), available_port()
            origin = f"http://localhost:{web_port}"
            env = dict(os.environ,
                       DATABASE_URL=f"mysql://duit_fixture:{password}@127.0.0.1:{database.port}/{DB}?{tls}",
                       DUIT_MAIL_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="),
                       DUIT_APP_ORIGIN=origin, DUIT_API_ADDR=f"127.0.0.1:{api_port}",
                       DUIT_SMTP_MODE="local", DUIT_SMTP_HOST="127.0.0.1", DUIT_MAIL_FROM="duit@example.test",
                       DUIT_SMTP_PORT=str(mail.server_address[1]))
            api = ROOT / "target/debug/api.exe"
            for _ in range(2):
                subprocess.run([api, "migrate"], env=env, check=True, timeout=30)
            check(database.rows(f"USE {DB}; SELECT version FROM _sqlx_migrations WHERE success=1 ORDER BY version;"), ["1", "2"])
            print("MySQL migration and repeat application OK", flush=True)
            client = Client(api_port, origin)
            with process([api], env, work / "api.log"):
                def ready():
                    try:
                        client.request("GET", "/readyz", 204)
                        return True
                    except OSError:
                        return None
                wait_for(ready)
                if shutil.which("postman"):
                    subprocess.run(["postman", "request", f"http://127.0.0.1:{api_port}/api/v1/healthz",
                                    "--no-report-events", "--script-post-request",
                                    'pm.test("healthz responds 204", () => pm.response.to.have.status(204));'],
                                   check=True, timeout=30)
                with contextmanager(verify_api)(database, env, mail, client, work):
                    if finance:
                        from phase2_financial import financial_test
                        financial_test(database, env, mail, api_port, origin)
                    if browser:
                        from phase1_browser import browser_test
                        browser_test(browser, env, origin, api_port, work, mail)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, help="Optional path to Chrome for browser E2E")
    parser.add_argument("--financial", action="store_true", help="Also run Financial Core regression")
    args = parser.parse_args()
    main(args.browser, args.financial)
