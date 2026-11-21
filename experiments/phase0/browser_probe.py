"""Run browser storage probe in two clean processes sharing one disposable profile."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading


PAGE = Path(__file__).with_name("offline.html")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path not in ("/?seed", "/?restore", "/prf"):
            self.send_error(404)
            return
        if self.path == "/prf":
            port = self.server.server_port
            host = self.headers.get("Host")
            if host == f"127.0.0.1:{port}":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{port}/prf")
                self.end_headers()
                return
            if host != f"localhost:{port}":
                self.send_error(400, "Use localhost for the WebAuthn probe")
                return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        page = PAGE.with_name("prf.html") if self.path == "/prf" else PAGE
        self.wfile.write(page.read_bytes())

    def do_POST(self):
        if self.path != "/result":
            self.send_error(404)
            return
        result = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()
        self.server.results.put(result)


def main(browser):
    with tempfile.TemporaryDirectory(prefix="duit-phase0-browser-", dir=Path.cwd()) as folder:
        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            server.results = queue.Queue()
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                for phase in ("seed", "restore"):
                    address = f"http://127.0.0.1:{server.server_port}/?{phase}"
                    with (Path(folder) / "browser.log").open("wb") as log:
                        process = subprocess.Popen([
                            browser, "--headless=new", "--no-first-run", "--disable-background-networking",
                            f"--user-data-dir={folder}/profile", address,
                        ], stdout=log, stderr=subprocess.STDOUT)
                        try:
                            result = server.results.get(timeout=20)
                        except queue.Empty as error:
                            raise RuntimeError((Path(folder) / "browser.log").read_text(errors="replace")) from error
                        finally:
                            process.terminate()
                            process.wait(timeout=10)
                    if "error" in result:
                        raise RuntimeError(result)
                    print(phase, result, flush=True)
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    if sys.argv[1:] == ["--manual-prf"]:
        with HTTPServer(("127.0.0.1", 8765), Handler) as manual_server:
            print("Open http://localhost:8765/prf in a disposable browser profile.", flush=True)
            try:
                manual_server.serve_forever()
            except KeyboardInterrupt:
                pass
    else:
        main(str(Path(sys.argv[1]).resolve(strict=True)))
