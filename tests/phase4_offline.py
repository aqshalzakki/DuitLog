"""Phase 4 offline vault in real Chrome: setup, Soft/Hard Lock, restart, offline boot, Recovery Key,
rotation, corruption, 7-day expiry, clock rollback, quota, two tabs and account isolation."""
from contextlib import contextmanager
import json
import urllib.request

import websocket

from phase1_auth import PASSWORD, ROOT, Client, check, mail_token, process, wait_for

PASSPHRASE = "synthetic offline passphrase"
PIN, NEW_PIN = "246810", "135790"
DESKTOP = {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False}
MOBILE = {"width": 390, "height": 840, "deviceScaleFactor": 1, "mobile": True}
MARKER = "PLAINTEXT-MARKER-7f3a"
MINUTE, DAY = 60_000, 24 * 60 * 60_000
# Test-only clock: the app reads Date.now(), so shifting it here needs no hook in app code.
CLOCK = "(() => { const real = Date.now.bind(Date); Date.now = () => real() + Number(localStorage.getItem('__clock') || 0) })()"


class Page:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, suppress_origin=True, timeout=30)
        self.step = 0
        self.errors = []
        self.paused = []  # Fetch.requestPaused events, for interception tests
        self.sent = []  # bodies of every /sync/items request this page sent

    def cdp(self, method, **params):
        self.step += 1
        self.ws.send(json.dumps({"id": self.step, "method": method, "params": params}))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("method") == "Fetch.requestPaused":
                self.paused.append(reply["params"])
            elif reply.get("method") == "Network.requestWillBeSent" and reply["params"]["request"]["url"].endswith("/sync/items"):
                self.sent.append(json.loads(reply["params"]["request"].get("postData") or "{}"))
            elif reply.get("method") == "Log.entryAdded" and reply["params"]["entry"]["level"] == "error":
                entry = reply["params"]["entry"]
                self.errors.append(f"{entry.get('source')}: {entry.get('text')} {entry.get('url', '')}")
            elif reply.get("method") == "Runtime.exceptionThrown":
                self.errors.append(reply["params"]["exceptionDetails"].get("exception", {}).get("description"))
            elif reply.get("method") == "Runtime.consoleAPICalled" and reply["params"]["type"] == "error":
                self.errors.append(" ".join(str(a.get("value", a.get("description"))) for a in reply["params"]["args"]))
            if reply.get("id") == self.step:
                if "error" in reply:
                    raise RuntimeError(f"Chrome command failed: {method} {reply['error']}")
                return reply["result"]

    def js(self, expression):
        result = self.cdp("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"Browser expression failed: {result['exceptionDetails'].get('exception', {}).get('description')}")
        return result["result"].get("value")

    def see(self, expression, timeout=20):
        try:
            wait_for(lambda: True if self.js(expression) else None, timeout)
        except TimeoutError:
            state = self.js("({ path: location.pathname, ready: document.readyState, status: document.querySelector('[data-vault-status]')?.dataset.vaultStatus,"
                            " text: document.querySelector('main')?.innerText.slice(0, 400) ?? null,"
                            " app: document.querySelector('#app')?.innerHTML.length ?? null })")
            probe = self.js("""indexedDB.databases().then(list => Promise.all(list.map(d => new Promise(done => {
              const r = indexedDB.open(d.name); const t = setTimeout(() => done(d.name + ': open hangs'), 3000);
              r.onblocked = () => done(d.name + ': blocked');
              r.onsuccess = () => { const db = r.result; const q = db.transaction(db.objectStoreNames[0]).objectStore(db.objectStoreNames[0]).count();
                q.onsuccess = () => { clearTimeout(t); db.close(); done(d.name + ': ok v' + db.version + ' stores ' + [...db.objectStoreNames]) } };
              r.onerror = () => { clearTimeout(t); done(d.name + ': error ' + r.error) } }))))""")
            raise TimeoutError(f"Waited for {expression!r}; page: {state}; errors: {self.errors[-5:]}; idb: {probe}")

    def status(self, value):
        self.see(f"document.querySelector('[data-vault-status]')?.dataset.vaultStatus === {json.dumps(value)}")

    def fill(self, selector, value):
        self.js(f"""(() => {{ const input = document.querySelector({json.dumps(selector)});
            input.value = {json.dumps(value)}; input.dispatchEvent(new Event('input', {{ bubbles: true }})) }})()""")

    def submit(self, selector):
        # The page ignores a submit while a previous action is still busy; wait it out first.
        self.see("!Array.from(document.querySelectorAll('button')).some(b => b.disabled)")
        self.js(f"document.querySelector({json.dumps(selector)}).form.requestSubmit()")

    def click(self, text):
        self.js(f"Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === {json.dumps(text)}).click()")

    def go(self, url):
        self.cdp("Page.navigate", url=url)

    def error(self):
        return self.js("document.querySelector('[data-vault-status] [role=alert]')?.textContent.trim() || ''")

    def vault(self, call):
        """Run a DEV test-hook call; returns the value or the VaultError code."""
        return self.js(f"window.__duitVault.{call}.then(v => ({{ ok: v ?? null }}), e => ({{ error: e.message }}))")

    def shift(self, ms):
        self.js(f"localStorage.setItem('__clock', String(Number(localStorage.getItem('__clock') || 0) + {ms})); window.dispatchEvent(new Event('focus'))")

    def close(self):
        self.ws.close()


class Chrome:
    def __init__(self, browser, env, work, origin):
        self.browser, self.env, self.work, self.origin = browser, env, work, origin
        self.profile = work / "offline-profile"

    @contextmanager
    def run(self, blocked=False):
        port_file = self.profile / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        with process([str(self.browser), "--headless=new", "--no-first-run", "--disable-background-networking",
                      "--remote-debugging-port=0", f"--user-data-dir={self.profile}", "about:blank"],
                     self.env, self.work / "offline-chrome.log") as proc:
            self.port = wait_for(lambda: port_file.read_text().splitlines()[0] if port_file.exists() else None)
            page = self.attach(next(t for t in self.targets() if t["type"] == "page"), blocked)
            try:
                yield page
            finally:
                page.close()
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=5) as reply:
                    browser_ws = json.load(reply)["webSocketDebuggerUrl"]
                root = websocket.create_connection(browser_ws, suppress_origin=True, timeout=10)
                root.send(json.dumps({"id": 1, "method": "Browser.close"}))  # clean shutdown flushes IndexedDB
                root.close()
                proc.wait(timeout=20)

    def targets(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=5) as reply:
            return json.load(reply)

    def attach(self, target, blocked=False):
        page = Page(target["webSocketDebuggerUrl"])
        page.cdp("Page.enable")
        page.cdp("Runtime.enable")
        page.cdp("Log.enable")
        page.cdp("Page.addScriptToEvaluateOnNewDocument", source=CLOCK)
        page.cdp("Network.enable")
        page.cdp("Network.setBlockedURLs", urls=["*/api/v1/*"] if blocked else [])
        page.cdp("Emulation.setDeviceMetricsOverride", **MOBILE)  # journeys run on a phone-sized viewport
        return page

    def new_tab(self, url):
        with urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{self.port}/json/new?{url}", method="PUT"), timeout=5) as reply:
            return self.attach(json.load(reply))


def login(page, origin, email):
    page.go(origin + "/login")
    page.see("!!document.querySelector('#email')")
    page.fill("#email", email)
    page.fill("#password", PASSWORD)
    page.submit("#password")
    page.see("['/', '/onboarding'].includes(location.pathname)")  # login lands on Beranda


def logout(page, origin):
    page.go(origin + "/account")
    page.see("Array.from(document.querySelectorAll('button')).some(b => b.textContent.trim() === 'Keluar')")
    page.click("Keluar")
    # PR-OFF-10: a device with a vault (locked after the full load, or holding pending) warns first.
    page.see("location.pathname === '/login' || !!document.querySelector('[data-logout-warning]')")
    if page.js("!!document.querySelector('[data-logout-warning]')"):
        page.click("Tetap keluar")
    page.see("location.pathname === '/login'")


def enroll(page, origin):
    page.go(origin + "/offline")
    page.see("!!document.querySelector('#pin')")
    page.status("none")
    # Offline Access is opt-in: no vault database exists before enrollment.
    owner = page.js("fetch('/api/v1/me').then(r => r.json()).then(me => me.id)")
    check(page.js(f"indexedDB.databases().then(list => list.some(d => d.name === 'duitlog-vault-{owner}'))"), False)
    page.fill("#pin", PIN)
    page.fill("#passphrase", PASSPHRASE)
    page.fill("#passphrase-confirm", PASSPHRASE)
    page.submit("#pin")
    page.see("!!document.querySelector('#recovery-key')?.textContent")
    key = page.js("document.querySelector('#recovery-key').textContent.trim()")
    page.fill("#recovery-confirm", key.replace("-", " ").lower())  # typing is forgiving, the key is not
    page.submit("#recovery-confirm")
    page.status("unlocked")
    return key


def unlock(page, method, secret, expect="unlocked"):
    page.status("hard")
    page.js(f"document.querySelector('input[value={method}]').click()")
    page.fill("#unlock-secret", secret)
    page.submit("#unlock-secret")
    if expect == "unlocked":
        page.status("unlocked")
        # Strong unlock also revalidates online; let that finish before the test moves the clock.
        page.see("!Array.from(document.querySelectorAll('button')).some(b => b.disabled)")
    else:
        page.js("new Promise(r => setTimeout(r, 300))")  # let the KDF finish so the alert is this attempt's
        page.see("!document.querySelector('#unlock-secret').form.querySelector('button').disabled && "
                 "document.querySelector('[data-vault-status] [role=alert]')?.textContent.includes('tidak cocok')")
        page.status("hard")


PENDING = {"kind": "DEDUCT", "amount": "9007199254740993", "note": MARKER}
DRAFT = {"title": MARKER + " draft"}


def records_intact(page):
    check(page.vault("read('p1')"), {"ok": PENDING})
    check(page.vault("read('d1')"), {"ok": DRAFT})
    check(page.vault("read('e1').then(b => new TextDecoder().decode(b))"), {"ok": MARKER + " evidence"})


RAW_SCAN = """(async (owner, marker) => {
  const db = await new Promise((ok, no) => { const r = indexedDB.open('duitlog-vault-' + owner); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error) });
  const all = (name) => new Promise(ok => { const r = db.transaction(name).objectStore(name).getAll(); r.onsuccess = () => ok(r.result) });
  const rows = [...await all('meta'), ...await all('records')];
  db.close();
  let keys = 0, text = '';
  const walk = (v) => {
    if (v instanceof CryptoKey) keys++;
    else if (v instanceof ArrayBuffer || ArrayBuffer.isView(v)) text += String.fromCharCode(...new Uint8Array(v.buffer ?? v));
    else if (typeof v === 'string') text += v;
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  rows.forEach(walk);
  const storage = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
  return { rows: rows.length, keys, plaintext: text.includes(marker) || storage.includes(marker),
           localKeys: Object.keys(localStorage).sort() };
})"""


def raw(page, owner):
    return page.js(f"{RAW_SCAN}({json.dumps(owner)}, {json.dumps(MARKER)})")


def corrupt(page, owner, record_id):
    page.js(f"""(async () => {{
      const db = await new Promise(ok => {{ const r = indexedDB.open('duitlog-vault-{owner}'); r.onsuccess = () => ok(r.result) }});
      const store = db.transaction('records', 'readwrite').objectStore('records');
      const row = await new Promise(ok => {{ const r = store.get({json.dumps(record_id)}); r.onsuccess = () => ok(r.result) }});
      const bytes = new Uint8Array(row.ct); bytes[0] ^= 1; row.ct = bytes.buffer;
      await new Promise(ok => {{ const r = db.transaction('records', 'readwrite').objectStore('records').put(row); r.transaction.oncomplete = ok }});
      db.close();
    }})()""")


def register(api_port, origin, mail, label):
    client = Client(api_port, origin)
    email = f"{label}@example.test"
    client.request("POST", "/auth/register", 202, data={"name": label, "email": email, "password": PASSWORD})
    client.login(email)
    client.request("POST", "/auth/verify-email", 204, data={"token": mail_token(mail, email, "Verifikasi")})
    return email, client.request("GET", "/me", 200)["id"]


def offline_test(browser, env, origin, api_port, work, mail):
    env = dict(env, DUIT_DEV_API=f"http://127.0.0.1:{api_port}")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    with process(["node", vite, "--host", "localhost", "--port", origin.rsplit(":", 1)[1], str(ROOT / "frontend")],
                 env, work / "offline-vite.log"):
        def ready():
            try:
                with urllib.request.urlopen(origin, timeout=1) as reply:
                    return True if reply.status == 200 else None
            except OSError:
                return None
        wait_for(ready)
        chrome = Chrome(browser, env, work, origin)
        run(chrome, origin, api_port, mail)
        from phase4_sync_client import sync_client_test
        sync_client_test(chrome, origin, api_port, mail)
        from phase5_ui import ui_test
        ui_test(chrome, origin, api_port, mail)
        from phase5_manage import manage_test
        manage_test(chrome, origin, api_port, mail)
        from phase5_slice3 import slice3_test
        slice3_test(chrome, origin, api_port, mail)
        from phase5_reports import reports_test, settings_test
        reports_test(chrome, origin, api_port, mail)
        settings_test(chrome, origin, api_port, mail)
        from phase5_slice6 import slice6_test
        slice6_test(chrome, origin, api_port, mail)
        from phase5_slice7 import slice7_test
        slice7_test(chrome, origin, api_port, mail)
        from phase6_evidence import evidence_ui_test
        evidence_ui_test(chrome, origin, api_port, mail)


def run(chrome, origin, api_port, mail):
    a_email, aid = register(api_port, origin, mail, "offline-a")
    b_email, bid = register(api_port, origin, mail, "offline-b")

    with chrome.run() as page:
        login(page, origin, a_email)
        recovery = enroll(page, origin)
        check(page.vault("save('pending', 'p1', " + json.dumps(PENDING) + ")"), {"ok": None})
        check(page.vault("save('draft', 'd1', " + json.dumps(DRAFT) + ")"), {"ok": None})
        check(page.vault(f"save('evidence', 'e1', new TextEncoder().encode({json.dumps(MARKER + ' evidence')}))"), {"ok": None})
        records_intact(page)
        scan = raw(page, aid)
        check((scan["keys"], scan["plaintext"], [k for k in scan["localKeys"] if k != "__clock"]),
              (0, False, ["duitlog.offline.owner"]))
        check(page.js("localStorage.getItem('duitlog.offline.owner')"), aid)
        print("Setup: PIN + passphrase + confirmed Recovery Key; raw IndexedDB/localStorage hold no plaintext or CryptoKey", flush=True)

        # Soft Lock after 5 idle minutes: the page is unmounted, PIN only reopens the in-memory key.
        page.shift(5 * MINUTE + 1000)
        page.see("!!document.querySelector('[data-soft-lock]') && !document.querySelector('[data-vault-status]')")
        check(page.js(f"document.body.innerText.includes({json.dumps(MARKER)})"), False)
        check(page.vault("read('p1')"), {"error": "LOCKED"})
        page.fill("#soft-pin", "000000")
        page.submit("#soft-pin")
        page.see("document.querySelector('#soft-error')?.textContent === 'PIN salah.'")
        page.fill("#soft-pin", PIN)
        page.submit("#soft-pin")
        page.status("unlocked")
        records_intact(page)
        page.shift(5 * MINUTE + 1000)
        page.see("!!document.querySelector('[data-soft-lock]')")
        for _ in range(5):
            page.fill("#soft-pin", "111111")
            page.submit("#soft-pin")
            page.js("new Promise(r => setTimeout(r, 400))")
        page.status("hard")
        check(page.vault("read('p1')"), {"error": "LOCKED"})
        unlock(page, "passphrase", "wrong passphrase value", expect="error")
        unlock(page, "passphrase", PASSPHRASE)
        records_intact(page)
        print("Soft Lock: unmounted at 5 min idle, wrong PIN refused, PIN reopens; 5 failures drop to Hard Lock", flush=True)

        # Two tabs: each tab holds its own key; logout in one hard-locks the other.
        other = chrome.new_tab(origin + "/offline")
        other.status("hard")  # a new tab never inherits the key
        logout(other, origin)
        page.status("hard")
        check(page.vault("read('p1')"), {"error": "LOCKED"})
        other.close()
        print("Two tabs: new tab starts Hard Locked; logout in another tab hard-locks this one", flush=True)
        login(page, origin, a_email)

    # Restart with the API unreachable: offline boot reaches the Hard Lock, PIN is not offered.
    with chrome.run(blocked=True) as page:
        page.go(origin + "/offline")
        page.status("hard")
        check(page.js("!!document.querySelector('#soft-pin') || !!document.querySelector('#pin')"), False)
        check(page.vault("read('p1')"), {"error": "LOCKED"})
        unlock(page, "recovery", "0000-" * 12 + "0000", expect="error")
        unlock(page, "recovery", recovery)
        records_intact(page)
        print("Restart offline (API blocked): Hard Lock, PIN unavailable, wrong key refused, Recovery Key opens all records", flush=True)

    with chrome.run() as page:
        page.go(origin + "/offline")
        unlock(page, "recovery", recovery)  # forgot PIN: strong unlock, then a new PIN
        page.fill("#new-pin", NEW_PIN)
        page.submit("#new-pin")
        page.see("document.querySelector('[role=status]')?.textContent.includes('PIN baru')")
        page.shift(5 * MINUTE + 1000)
        page.see("!!document.querySelector('[data-soft-lock]')")
        page.fill("#soft-pin", PIN)
        page.submit("#soft-pin")
        page.see("document.querySelector('#soft-error')?.textContent === 'PIN salah.'")
        page.fill("#soft-pin", NEW_PIN)
        page.submit("#soft-pin")
        page.status("unlocked")
        records_intact(page)

        new_passphrase = PASSPHRASE + " rotated"
        page.fill("#current-passphrase", PASSPHRASE)
        page.fill("#new-passphrase", new_passphrase)
        page.submit("#new-passphrase")
        page.see("document.querySelector('[role=status]')?.textContent.includes('Passphrase diganti')")
        page.click("Buat Recovery Key baru")
        page.see("!!document.querySelector('#recovery-key')?.textContent")
        new_recovery = page.js("document.querySelector('#recovery-key').textContent.trim()")
        page.fill("#recovery-confirm", new_recovery)
        page.fill("#rotate-current", new_passphrase)
        page.submit("#recovery-confirm")
        page.see("document.querySelector('[role=status]')?.textContent.includes('Recovery Key baru aktif')")
        page.click("Kunci sekarang")
        unlock(page, "passphrase", PASSPHRASE, expect="error")
        unlock(page, "recovery", recovery, expect="error")
        unlock(page, "passphrase", new_passphrase)
        page.click("Kunci sekarang")
        unlock(page, "recovery", new_recovery)
        records_intact(page)
        print("Forgot PIN via Recovery Key, PIN reset; passphrase and Recovery Key rotation: old fail, new open, records intact", flush=True)

        # 7-day validation: data is held, not deleted; only a live server answer renews it.
        rows = raw(page, aid)["rows"]
        page.shift(7 * DAY + MINUTE)  # also an idle period, so Soft Lock comes first
        page.see("!!document.querySelector('[data-soft-lock]')")
        page.fill("#soft-pin", NEW_PIN)
        page.submit("#soft-pin")
        page.see("document.body.innerText.includes('lebih dari 7 hari')")
        check(page.vault("read('p1')"), {"error": "EXPIRED"})
        check(page.vault("save('pending', 'p2', {})"), {"error": "EXPIRED"})
        check(raw(page, aid)["rows"], rows)
        page.click("Validasi sekarang")
        page.see("document.querySelector('[role=status]')?.textContent.includes('Validasi online berhasil')")
        records_intact(page)
        page.shift(-(7 * DAY + MINUTE) - 10 * MINUTE)  # device clock set back past the trusted reference
        page.see("document.body.innerText.includes('jam perangkat mundur')")
        check(page.vault("read('p1')"), {"error": "EXPIRED"})
        page.click("Validasi sekarang")
        page.see("document.querySelector('[role=status]')?.textContent.includes('Validasi online berhasil')")
        records_intact(page)
        print("7-day expiry and clock rollback hold reads and writes, keep ciphertext, clear only after server validation", flush=True)

        corrupt(page, aid, "p1")
        check(page.vault("read('p1')"), {"error": "CORRUPTED"})
        check(page.vault("list('pending')"), {"error": "CORRUPTED"})
        check(page.vault("read('d1')"), {"ok": DRAFT})
        # Same vault, same key: moving d1's ciphertext under another id must fail on the AAD alone.
        page.js(f"""(async () => {{
          const db = await new Promise(ok => {{ const r = indexedDB.open('duitlog-vault-{aid}'); r.onsuccess = () => ok(r.result) }});
          const row = await new Promise(ok => {{ const r = db.transaction('records').objectStore('records').get('d1'); r.onsuccess = () => ok(r.result) }});
          await new Promise(ok => {{ const r = db.transaction('records', 'readwrite').objectStore('records').put({{ ...row, id: 'swap' }}); r.transaction.oncomplete = ok }});
          db.close();
        }})()""")
        check(page.vault("read('swap')"), {"error": "CORRUPTED"})

        page.cdp("Storage.overrideQuotaForOrigin", origin=origin, quotaSize=1024 * 1024)
        big = page.vault("save('evidence', 'big', new Uint8Array(8 * 1024 * 1024))")
        page.cdp("Storage.overrideQuotaForOrigin", origin=origin)
        quota = "STORAGE refused, nothing saved" if big == {"error": "STORAGE"} else f"NOT RUN (override gave {big})"
        if big == {"error": "STORAGE"}:
            check(page.vault("read('big')"), {"ok": None})
        print(f"Corrupted ciphertext reports CORRUPTED (not empty); quota: {quota}", flush=True)

        # Account isolation: B gets its own vault; A's ciphertext does not open under B.
        logout(page, origin)
        login(page, origin, b_email)
        enroll(page, origin)
        foreign = page.js(f"""(async () => {{
          const open = (name) => new Promise(ok => {{ const r = indexedDB.open(name); r.onsuccess = () => ok(r.result) }});
          const a = await open('duitlog-vault-{aid}'), b = await open('duitlog-vault-{bid}');
          const row = await new Promise(ok => {{ const r = a.transaction('records').objectStore('records').get('d1'); r.onsuccess = () => ok(r.result) }});
          await new Promise(ok => {{ const r = b.transaction('records', 'readwrite').objectStore('records').put(row); r.transaction.oncomplete = ok }});
          a.close(); b.close();
        }})()""")
        check(foreign, None)
        check(page.vault("read('d1')"), {"error": "CORRUPTED"})
        # Wrappers gone but records left: report corrupt, never offer a setup that would replace it.
        records_before = raw(page, bid)["rows"] - 1
        page.js(f"""(async () => {{
          const db = await new Promise(ok => {{ const r = indexedDB.open('duitlog-vault-{bid}'); r.onsuccess = () => ok(r.result) }});
          await new Promise(ok => {{ const r = db.transaction('meta', 'readwrite').objectStore('meta').delete('vault'); r.transaction.oncomplete = ok }});
          db.close();
        }})()""")
        page.cdp("Page.reload")
        page.status("corrupt")
        check(page.js("!!document.querySelector('#pin') || !!document.querySelector('#unlock-secret')"), False)
        check(raw(page, bid)["rows"], records_before)
        # Erasing while another tab holds the database open must not hang.
        second = chrome.new_tab(origin + "/offline")
        second.status("corrupt")
        page.fill("#erase-confirm", "hapus")
        page.submit("#erase-confirm")
        page.see("document.querySelector('[data-vault-status] [role=alert]')?.textContent.includes('Periksa isian')")
        page.fill("#erase-confirm", "HAPUS")
        page.submit("#erase-confirm")
        page.status("none")
        second.status("none")
        second.close()
        names = page.js("indexedDB.databases().then(list => list.map(d => d.name))")
        check((f"duitlog-vault-{bid}" in names, f"duitlog-vault-{aid}" in names), (False, True))
        logout(page, origin)
        login(page, origin, a_email)
        page.go(origin + "/offline")
        unlock(page, "passphrase", new_passphrase)
        check(page.vault("read('d1')"), {"ok": DRAFT})
        print("Account isolation: B's vault separate, A's ciphertext refused under B or under another id; meta loss shows "
              "corrupt without setup; erase needs HAPUS, works with a second tab open, removes only B", flush=True)

        # A real 401 (all sessions revoked elsewhere) drops the key.
        revoker = Client(api_port, origin)
        revoker.login(a_email)
        revoker.request("POST", "/auth/logout-all", 204)
        page.click("Validasi sekarang")
        page.status("hard")
        check(page.vault("read('d1')"), {"error": "LOCKED"})
        print("Server 401 (sessions revoked elsewhere) hard-locks the open vault", flush=True)

    # A was opened last, so an offline boot after restart finds A's vault again.
    with chrome.run(blocked=True) as page:
        page.go(origin + "/offline")
        page.status("hard")
        unlock(page, "passphrase", new_passphrase)
        check(page.vault("read('d1')"), {"ok": DRAFT})
        print("Offline boot after another account erased its vault still reaches A's data", flush=True)
