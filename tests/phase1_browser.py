"""Chrome DevTools smoke of the Vue forms, cookies and capability guard."""
import json
import urllib.request

import websocket

from phase1_auth import PASSWORD, ROOT, check, mail_token, process, wait_for


def browser_test(browser, env, origin, api_port, work, mail):
    env = dict(env, DUIT_DEV_API=f"http://127.0.0.1:{api_port}")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    with process(["node", vite, "--host", "localhost", "--port", origin.rsplit(":", 1)[1],
                  str(ROOT / "frontend")], env, work / "vite.log"):
        def ready():
            try:
                with urllib.request.urlopen(origin, timeout=1) as reply:
                    return True if reply.status == 200 else None
            except OSError:
                return None
        wait_for(ready)
        return run_chrome(browser, env, origin, work, mail)


def run_chrome(browser, env, origin, work, mail):
    profile = work / "browser"
    with process([str(browser), "--headless=new", "--no-first-run", "--disable-background-networking",
                  "--remote-debugging-port=0", f"--user-data-dir={profile}", origin + "/account"],
                 env, work / "chrome.log"):
        port_file = profile / "DevToolsActivePort"
        port = wait_for(lambda: port_file.read_text().splitlines()[0] if port_file.exists() else None)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as reply:
            page = next(item for item in json.load(reply) if item["type"] == "page")
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], suppress_origin=True, timeout=5)
        try:
            step = 0

            def cdp(method, **params):
                nonlocal step
                step += 1
                ws.send(json.dumps({"id": step, "method": method, "params": params}))
                while True:
                    reply = json.loads(ws.recv())
                    if reply.get("id") == step:
                        if "error" in reply:
                            raise RuntimeError(f"Chrome command failed: {method}")
                        return reply["result"]

            def js(expression):
                result = cdp("Runtime.evaluate", expression=expression,
                             returnByValue=True, awaitPromise=True)
                if "exceptionDetails" in result:
                    raise RuntimeError("Browser expression failed")
                return result["result"].get("value")

            def see(expression):
                wait_for(lambda: True if js(expression) else None)

            def fill(selector, value):
                js(f"""(() => {{
                    const input = document.querySelector({json.dumps(selector)});
                    input.value = {json.dumps(value)};
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }})()""")

            def submit():
                js("document.querySelector('form').requestSubmit()")

            cdp("Page.navigate", url=origin + "/account")
            cdp("Emulation.setDeviceMetricsOverride", width=390, height=840, deviceScaleFactor=1, mobile=True)
            see("location.pathname === '/login' && !!document.querySelector('#email')")
            cdp("Input.dispatchKeyEvent", type="rawKeyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9)
            cdp("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
            check(js("document.activeElement.classList.contains('skip-link')"), True)
            check(js("document.documentElement.scrollWidth <= innerWidth"), True)
            check(js("document.querySelector('label[for=email]').textContent.trim()"), "Email")

            js("""document.querySelector('a[href="/register"]').click()""")
            see("location.pathname === '/register' && !!document.querySelector('#name')")
            address = "browser@example.test"
            fill("#name", "Browser test")
            fill("#email", address)
            fill("#password", PASSWORD)
            submit()
            see("""location.pathname === '/verify-email' &&
                !!document.querySelector('a[href="/login"]') && !document.querySelector('#token')""")
            token = mail_token(mail, address, "Verifikasi")
            js("""document.querySelector('a[href="/login"]').click()""")
            see("location.pathname === '/login' && !!document.querySelector('#password')")
            fill("#email", address)
            fill("#password", PASSWORD)
            submit()
            see("location.pathname === '/verify-email' && !!document.querySelector('#token')")
            fill("#token", token)
            submit()
            see("location.pathname === '/account' && document.querySelector('main').textContent.includes('Browser test')")
            cdp("Page.reload")
            see("location.pathname === '/account' && document.querySelector('main')?.textContent.includes('Browser test')")
            check(js("document.cookie.includes('duit-access') || document.cookie.includes('duit-refresh')"), False)
            check(js("localStorage.length + sessionStorage.length"), 0)
            # Page.reload returns before navigation; wait for the new document's button before clicking.
            see("Array.from(document.querySelectorAll('button')).some(button => button.textContent.trim() === 'Keluar')")
            js("Array.from(document.querySelectorAll('button')).find(button => button.textContent.trim() === 'Keluar').click()")
            see("location.pathname === '/login'")
            print("Chrome mobile viewport, keyboard skip link, register/login/verify/reload/logout OK", flush=True)
        finally:
            ws.close()
