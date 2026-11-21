"""Client sync engine in real Chrome against the real API: offline queue, Partial Sync states,
correction, lost response, crash mid-send, 3 attempts per cycle, owner binding, in-flight guard,
two tabs and Hard Lock."""
from base64 import b64encode
from datetime import UTC, datetime, timedelta
import json
import time

from phase1_auth import PASSWORD, Client, check, mail_token
from phase2_financial import operation
from phase3_sync import totals
from phase4_offline import MINUTE, PASSPHRASE, PIN, enroll, login, unlock

URL = "*/api/v1/sync/items"


def at(seconds):
    return (datetime.now(UTC) - timedelta(minutes=30) + timedelta(seconds=seconds)).isoformat()


def account(api_port, origin, mail, label):
    client = Client(api_port, origin)
    email = f"{label}@example.test"
    client.request("POST", "/auth/register", 202, data={"name": label, "email": email, "password": PASSWORD})
    client.login(email)
    client.request("POST", "/auth/verify-email", 204, data={"token": mail_token(mail, email, "Verifikasi")})
    operation(client, "/onboarding/skip-opening-balance")  # otherwise every item is OPENING_REQUIRED
    return client, email, client.request("GET", "/me", 200)["id"]


def hook(page, call):
    return page.js(f"window.__duitSync.{call}.then(v => ({{ ok: v ?? null }}), e => ({{ error: e.code || e.message }}))")


def add(page, kind, amount, eff, depends=(), **fields):
    data = {"kind": kind, "amount": str(amount), "effectiveAt": eff, **fields}
    result = hook(page, f"enqueue('ACTIVITY', {json.dumps(data)}, {json.dumps(list(depends))})")
    return result["ok"]


def items(page):
    return {item["clientActivityId"]: item for item in page.js("window.__duitSync.items()")}


def states(page, *ids):
    found = items(page)
    return tuple(found[i]["state"] if i in found else None for i in ids)


def expect(page, ids, wanted, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if states(page, *ids) == tuple(wanted) and not page.js("window.__duitSync.state().running"):
            return
        time.sleep(0.1)
    raise TimeoutError(f"states {states(page, *ids)} != {wanted}; sync {page.js('window.__duitSync.state()')}")


def nav(page, path):
    """In-app navigation; a full page load would be a Hard Lock."""
    page.see(f"!!document.querySelector('nav a[href=\"{path}\"]')")
    page.js(f"document.querySelector('nav a[href=\"{path}\"]').click()")
    page.see(f"location.pathname === {json.dumps(path)}")


def network(page, online):
    page.cdp("Network.emulateNetworkConditions", offline=not online, latency=0, downloadThroughput=-1, uploadThroughput=-1)
    page.see(f"navigator.onLine === {json.dumps(online)}")


def intercept(page, handle, until, timeout=30):
    """Answer Fetch.requestPaused events from Python while the page's own cycle keeps running."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.js("1")  # pump CDP events
        while page.paused:
            handle(page.paused.pop(0))
        if until():
            return
        time.sleep(0.05)
    raise TimeoutError(f"interception did not finish; sync {page.js('window.__duitSync.state()')}")


def fulfill(page, event, status, body):
    page.cdp("Fetch.fulfillRequest", requestId=event["requestId"], responseCode=status,
             responseHeaders=[{"name": "Content-Type", "value": "application/json"}],
             body=b64encode(json.dumps(body).encode()).decode())


def lookup(client, item):
    return client.request("GET", "/operations/" + item["attemptId"], (200, 404), full=True)[0]


def sync_client_test(chrome, origin, api_port, mail):
    client, email, sid = account(api_port, origin, mail, "sync-a")
    with chrome.run() as page:
        login(page, origin, email)
        enroll(page, origin)
        nav(page, "/sync")
        page.see("document.querySelector('h1')?.textContent === 'Sinkronisasi'")
        b0, r0 = totals(client)

        # Offline: items are saved encrypted and nothing is sent.
        network(page, False)
        check(hook(page, "enqueue('ACTIVITY', { kind: 'INCREASE', amount: 5, effectiveAt: '2024-01-01T00:00:00Z' })"),
              {"error": "INVALID"})  # money as a JS Number is refused
        check(hook(page, "enqueue('ACTIVITY', { kind: 'ADJUSTMENT', amount: '5', effectiveAt: '2024-01-01T00:00:00Z' })"),
              {"error": "INVALID"})
        check(hook(page, "enqueue('ACTIVITY', { kind: 'INCREASE', amount: '5', effectiveAt: '2024-01-01T00:00:00Z', x: 1 })"),
              {"error": "INVALID"})
        b = hook(page, "enqueue('BORROWER', { name: 'Teman offline' })")["ok"]
        loan = add(page, "LOAN", 10, at(1), borrowerClientId=b)
        repay = add(page, "REPAYMENT", 4, at(2), [loan], borrowerClientId=b)
        x = add(page, "INCREASE", 5, at(3))
        big = add(page, "INCREASE", "9007199254740993", at(3))
        future = add(page, "DEDUCT", 6, (datetime.now(UTC) + timedelta(days=1)).isoformat())
        child = add(page, "INCREASE", 3, at(6), [future])
        every = (b, loan, repay, x, big, future, child)
        check(states(page, *every), ("PENDING",) * 7)
        page.js("1")
        check(page.sent, [])
        check(page.js("document.querySelectorAll('[data-state=PENDING]').length"), 7)

        # Back online: one Partial Sync request, parents first, conflict kept, child blocked.
        network(page, True)
        expect(page, every, ["SYNCED"] * 5 + ["CONFLICT", "BLOCKED"])
        check(items(page)[future]["code"], "INVALID_FUTURE_EFFECTIVE_TIME")
        check(len(page.sent), 1)
        body = page.sent[0]
        order = [i["clientActivityId"] for i in body["items"]]
        check((body["owner"], sorted(order) == sorted(every)), (sid, True))
        check(order.index(b) < order.index(loan) < order.index(repay) and order.index(future) < order.index(child), True)
        check({i["amount"] for i in body["items"] if "amount" in i} >= {"9007199254740993"}, True)
        check(totals(client), (b0 + 5 + 9007199254740993 - 10 + 4, r0 + 6))
        print("Sync engine: offline enqueue sends nothing; online Partial Sync gives SYNCED, CONFLICT, BLOCKED "
              "in one request; money stays a string end to end", flush=True)

        # A business conflict is never retried automatically, and its held child is not resent.
        check(hook(page, "cycle(true)"), {"ok": None})
        check(len(page.sent), 1)
        check(hook(page, f"correct({json.dumps(x)}, {{ kind: 'INCREASE', amount: '1', effectiveAt: {json.dumps(at(3))} }})"),
              {"error": "NOT_EDITABLE"})
        old_attempt = items(page)[future]["attemptId"]
        check(hook(page, f"correct({json.dumps(future)}, {{ kind: 'DEDUCT', amount: '6', effectiveAt: {json.dumps(at(5))} }})"),
              {"ok": None})
        expect(page, (future, child), ["SYNCED", "SYNCED"])
        fixed = page.sent[-1]["items"]
        check([(i["clientActivityId"], i["attemptId"] != old_attempt) for i in fixed], [(future, True), (child, True)])
        check(totals(client), (b0 + 9007199254740993 - 1 - 6 + 3, r0 + 6))
        check(client.request("GET", "/operations/" + old_attempt, 200)["code"], "INVALID_FUTURE_EFFECTIVE_TIME")
        print("Conflict not resent; correction is a new attempt of the same activity; blocked child follows", flush=True)

        # Lost response: the server commits, the browser sees a network error, the lookup finds it.
        network(page, False)
        lost = add(page, "DEDUCT", 2, at(7))
        start, sent = totals(client), len(page.sent)
        page.cdp("Fetch.enable", patterns=[{"urlPattern": URL, "requestStage": "Response"}])
        handled = []
        network(page, True)
        intercept(page, lambda e: (handled.append(e), page.cdp("Fetch.failRequest", requestId=e["requestId"],
                                                                  errorReason="ConnectionReset")),
                  lambda: states(page, lost) == ("SYNCED",))
        page.cdp("Fetch.disable")
        page.js("1")
        check((len(handled), len(page.sent) - sent), (1, 1))  # answered by lookup, not by a resend
        check(totals(client), (start[0] - 2, start[1]))
        print("Lost response: committed batch, failed response, lookup marks SYNCED with no resend", flush=True)

        # Crash mid-send: the request never leaves, the page reloads, the same attempt is resent once.
        network(page, False)
        crash = add(page, "INCREASE", 7, at(8))
        attempt = items(page)[crash]["attemptId"]
        start = totals(client)
        page.cdp("Fetch.enable", patterns=[{"urlPattern": URL, "requestStage": "Request"}])
        network(page, True)
        stuck = []
        intercept(page, stuck.append, lambda: stuck and states(page, crash) == ("SYNCING",))
        check(lookup(client, items(page)[crash]), 404)
        page.cdp("Page.reload")
        for event in stuck:  # normally gone with the old document; never let it continue
            try:
                page.cdp("Fetch.failRequest", requestId=event["requestId"], errorReason="Aborted")
            except RuntimeError:
                pass
        page.cdp("Fetch.disable")
        page.js("new Promise(r => setTimeout(r, 1000))")
        check(lookup(client, {"attemptId": attempt}), 404)  # the paused request never reached the server
        nav(page, "/offline")
        unlock(page, "passphrase", PASSPHRASE)
        expect(page, (crash,), ["SYNCED"])
        check(items(page)[crash]["attemptId"], attempt)
        check([i["attemptId"] for i in page.sent[-1]["items"]], [attempt])
        check(totals(client), (start[0] + 7, start[1]))
        print("Crash mid-send: reload, lookup 404, same attempt resent once, one effect", flush=True)

        # Temporary failure: exactly 3 attempts in a cycle, then wait; nothing recorded.
        network(page, False)
        temp = add(page, "INCREASE", 1, at(9))
        start = totals(client)
        page.cdp("Fetch.enable", patterns=[{"urlPattern": URL, "requestStage": "Request"}])
        tries = []
        busy = {"code": "TEMPORARY_FAILURE", "message": "busy", "retryable": True}
        network(page, True)
        intercept(page, lambda e: (tries.append(e), fulfill(page, e, 503, busy)),
                  lambda: len(tries) == 3 and states(page, temp) == ("RETRY_WAITING",)
                  and not page.js("window.__duitSync.state().running"))
        stop = time.time() + 4
        intercept(page, lambda e: (tries.append(e), fulfill(page, e, 503, busy)), lambda: time.time() > stop)
        page.cdp("Fetch.disable")
        check(len(tries), 3)
        check(lookup(client, items(page)[temp]), 404)
        check(totals(client), start)
        check(hook(page, "cycle(true)"), {"ok": None})
        check(states(page, temp), ("SYNCED",))
        print("Temporary failure: 3 attempts per cycle with backoff, then RETRY_WAITING until the next cycle", flush=True)

        # A coded 500 can follow committed items: it is an unknown outcome, looked up before any resend.
        network(page, False)
        crashed = add(page, "INCREASE", 1, at(9))
        start, sent = totals(client), len(page.sent)
        page.cdp("Fetch.enable", patterns=[{"urlPattern": URL, "requestStage": "Request"}])
        seen = set()

        def internal(event):
            fulfill(page, event, 500, {"code": "INTERNAL_ERROR", "message": "x"})
            page.cdp("Fetch.disable")
        network(page, True)
        intercept(page, internal, lambda: seen.add(states(page, crashed)[0]) or states(page, crashed) == ("SYNCED",))
        page.js("1")
        check("CHECKING_OUTCOME" in seen, True)
        check([i["attemptId"] for r in page.sent[sent:] for i in r["items"]], [items(page)[crashed]["attemptId"]] * 2)
        check(totals(client), (start[0] + 1, start[1]))

        # Chunking: 52 items need two requests; the child's parent is in the first one.
        network(page, False)
        first = add(page, "INCREASE", 1, at(9))
        rest = [add(page, "INCREASE", 1, at(9)) for _ in range(50)]
        last = add(page, "INCREASE", 1, at(10), [first])
        start, sent = totals(client), len(page.sent)
        network(page, True)
        expect(page, [first, *rest, last], ["SYNCED"] * 52, timeout=60)
        page.js("1")
        check([len(r["items"]) for r in page.sent[sent:]], [50, 2])
        check(first in [i["clientActivityId"] for i in page.sent[sent]["items"]], True)
        check(totals(client), (start[0] + 52, start[1]))
        print("Coded 500 is an unknown outcome (lookup, then the same attempt); 52 items go in chunks of 50, "
              "parent first", flush=True)

        # The envelope names the vault owner; a session of another account makes the client hard-lock.
        network(page, False)
        stray = add(page, "INCREASE", 11, at(10))
        start = totals(client)
        page.cdp("Fetch.enable", patterns=[{"urlPattern": URL, "requestStage": "Request"}])
        owners = []
        network(page, True)
        intercept(page, lambda e: (owners.append(json.loads(e["request"]["postData"])["owner"]),
                                   fulfill(page, e, 409, {"code": "SESSION_OWNER_MISMATCH", "message": "x"})),
                  lambda: page.vault("list('pending')") == {"error": "LOCKED"})
        page.cdp("Fetch.disable")
        check(owners, [sid])
        check(page.js("window.__duitSync.items().then(list => list.length)"), 0)  # decrypted queue cleared with the key
        check(totals(client), start)
        nav(page, "/offline")
        unlock(page, "passphrase", PASSPHRASE)
        expect(page, (stray,), ["SYNCED"])
        check(totals(client), (start[0] + 11, start[1]))
        print("Owner binding: envelope carries the vault owner; SESSION_OWNER_MISMATCH hard-locks, item stays queued", flush=True)

        # An attempt whose answer never arrived cannot be edited or cancelled until it settles.
        network(page, False)
        parent = add(page, "DEDUCT", 1, (datetime.now(UTC) + timedelta(days=1)).isoformat())
        network(page, True)
        expect(page, (parent,), ["CONFLICT"])
        network(page, False)
        kid = add(page, "INCREASE", 1, at(11), [parent])
        page.cdp("Fetch.enable", patterns=[{"urlPattern": URL, "requestStage": "Request"}])
        faked = []

        def fail_once(event):
            faked.append(event)
            fulfill(page, event, 200, {"results": [{"clientActivityId": kid, "status": "FAILED", "code": "INTERNAL_ERROR"}]})
            page.cdp("Fetch.disable")
        network(page, True)
        intercept(page, fail_once, lambda: faked and states(page, kid) == ("BLOCKED",)
                  and not page.js("window.__duitSync.state().running"))
        check(bool(items(page)[kid].get("unsure")), True)
        check(hook(page, f"cancel({json.dumps(kid)})"), {"error": "IN_FLIGHT"})
        check(hook(page, f"cancel({json.dumps(parent)})"), {"error": "HAS_CHILDREN"})
        nav(page, "/sync")
        page.see(f"!!document.querySelector('[data-client-id=\"{kid}\"]')")
        check(page.js(f"!!document.querySelector('[data-client-id=\"{kid}\"] button')"), False)
        page.shift(11 * MINUTE)  # past the settle time; also idle, so Soft Lock first
        page.see("!!document.querySelector('[data-soft-lock]')")
        page.fill("#soft-pin", PIN)
        page.submit("#soft-pin")
        page.see(f"window.__duitSync.items().then(list => list.some(i => i.clientActivityId === {json.dumps(kid)} && !i.unsure))")
        check(hook(page, f"cancel({json.dumps(kid)})"), {"ok": None})
        check(hook(page, f"cancel({json.dumps(parent)})"), {"ok": None})
        check(states(page, kid, parent), (None, None))
        print("In-flight guard: unanswered attempt blocks cancel until a lookup after the settle time; parent with "
              "children refused", flush=True)

        # Two unlocked tabs: one cycle sends, the other finds nothing to do.
        second = chrome.new_tab(origin + "/offline")
        unlock(second, "passphrase", PASSPHRASE)
        network(page, False)
        network(second, False)
        pair = [add(page, "INCREASE", n, at(12)) for n in (2, 3)]
        start, sent = totals(client), len(page.sent) + len(second.sent)
        network(page, True)
        network(second, True)
        second.js("void window.__duitSync.cycle(true)")
        expect(page, pair, ["SYNCED", "SYNCED"])
        second.see("!window.__duitSync.state().running")
        page.js("1")
        second.js("1")
        check(len(page.sent) + len(second.sent) - sent, 1)
        check(totals(client), (start[0] + 5, start[1]))
        # Deterministic lease: while the other tab holds the owner's sync lock, this tab sends nothing.
        network(page, False)
        leased = add(page, "INCREASE", 6, at(12))
        network(page, True)
        # The newer tab is in front: a hidden tab does not sync (foreground-first).
        check(page.js("document.visibilityState"), "hidden")
        check(hook(page, "cycle(true)"), {"ok": None})
        check(states(page, leased), ("PENDING",))
        second.js(f"void navigator.locks.request('duitlog-sync-{sid}', () => new Promise(r => window.__release = r))")
        second.see("typeof window.__release === 'function'")
        page.cdp("Page.bringToFront")  # becoming visible triggers a cycle, which must find the lease taken
        page.see("document.visibilityState === 'visible'")
        sent = len(page.sent) + len(second.sent)
        check(hook(page, "cycle(true)"), {"ok": None})
        check(states(page, leased), ("PENDING",))
        page.js("1")
        check(len(page.sent) - (sent - len(second.sent)), 0)
        second.js("window.__release()")
        page.see("navigator.locks.query().then(q => q.held.length === 0)")
        check(hook(page, "cycle(true)"), {"ok": None})
        check(states(page, leased), ("SYNCED",))
        second.close()
        print("Two tabs: one Web Lock holder sends, one request and one effect; a held lease stops the other tab; a hidden tab does not sync", flush=True)

        # Hard Lock holds sync even when online.
        network(page, False)
        held = add(page, "INCREASE", 4, at(13))
        start, sent = totals(client), len(page.sent)
        nav(page, "/offline")
        page.status("unlocked")
        page.click("Kunci sekarang")
        page.status("hard")
        network(page, True)
        page.js("new Promise(r => setTimeout(r, 2000))")
        check((totals(client), len(page.sent)), (start, sent))
        unlock(page, "passphrase", PASSPHRASE)
        expect(page, (held,), ["SYNCED"])
        check(totals(client), (start[0] + 4, start[1]))
        check(client.request("GET", "/integrity-status", 200)["frozen"], False)
        print("Hard Lock holds sync; unlock resumes it", flush=True)
