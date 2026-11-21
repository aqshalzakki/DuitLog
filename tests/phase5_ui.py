"""Phase 5 slice 1 through the real UI in Chrome: opening balance vs skip, Quick Add online (field
errors, double submit, lost response), dashboard, offline borrower/loan/repayment, conflict fixed in
Sync Center, Soft Lock mid-form, offline boot to the form."""
from datetime import UTC, datetime, timedelta
import json
import time

from phase1_auth import PASSWORD, Client, check, mail_token, wait_for
from phase3_sync import totals
from phase4_offline import MINUTE, PASSPHRASE, PIN, enroll, login, logout, unlock
from phase4_sync_client import intercept, network


def user(api_port, origin, mail, label):
    client = Client(api_port, origin)
    email = f"{label}@example.test"
    client.request("POST", "/auth/register", 202, data={"name": label, "email": email, "password": PASSWORD})
    client.login(email)
    client.request("POST", "/auth/verify-email", 204, data={"token": mail_token(mail, email, "Verifikasi")})
    return client, email


def link(page, text):
    """In-app navigation by link text; a full page load would be a Hard Lock."""
    page.see(f"Array.from(document.querySelectorAll('a')).some(a => a.textContent.trim() === {json.dumps(text)})")
    page.js(f"Array.from(document.querySelectorAll('a')).find(a => a.textContent.trim() === {json.dumps(text)}).click()")


def select(page, selector, value):
    page.js(f"""(() => {{ const s = document.querySelector({json.dumps(selector)}); s.value = {json.dumps(value)};
        s.dispatchEvent(new Event('change', {{ bubbles: true }})) }})()""")


def value(page, selector):
    return page.js(f"document.querySelector({json.dumps(selector)}).value")


def result(page, title):
    page.see(f"document.querySelector('[data-entry-result] strong')?.textContent === {json.dumps(title)}")


def save(page):
    page.see("!document.querySelector('form fieldset').disabled")
    page.js("document.querySelector('#amount').form.requestSubmit()")


def past_now(client):
    """A real past second for the WIB time field that is still after the opening snapshot; one in the same
    second or earlier would be absorbed by it (correct behaviour, wrong for a test of the fix)."""
    opening = next(a for a in client.request("GET", "/activities", 200)["items"] if a["kind"] == "OPENING")
    after = datetime.fromisoformat(opening["effectiveAt"])
    while (moment := (datetime.now(UTC) - timedelta(seconds=1)).replace(microsecond=0)) <= after:
        time.sleep(0.1)
    return (moment + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S")


def kinds(client):
    items = client.request("GET", "/activities", 200)["items"]
    return [(a["kind"], a.get("amount"), a.get("title")) for a in items if a["kind"] != "OPENING"]


def ui_test(chrome, origin, api_port, mail):
    first, first_email = user(api_port, origin, mail, "ui-a")
    second, second_email = user(api_port, origin, mail, "ui-b")
    with chrome.run() as page:
        # Earlier suites leave the test clock shifted in this profile; these accounts start from real time.
        page.go(origin + "/login")
        page.see("!!document.querySelector('#email')")
        page.js("localStorage.removeItem('__clock')")
        # Opening balance: an explicit Rp0 is a recorded snapshot; skipping is not.
        login(page, origin, second_email)
        link(page, "Beranda")
        page.see("location.pathname === '/onboarding'")
        link(page, "Beranda")
        page.see("location.pathname === '/onboarding'")  # finance pages wait for the decision
        page.click("Lewati saldo awal")
        page.see("document.body.innerText.includes('Saldo awal sudah ditentukan')")
        check(second.request("GET", "/financial-state", 200)["opening"], "skipped")
        logout(page, origin)

        login(page, origin, first_email)
        link(page, "Beranda")
        page.see("location.pathname === '/onboarding'")
        page.fill("#opening", "abc")
        page.submit("#opening")
        page.see("document.querySelector('#opening-error')?.textContent.includes('Rupiah bulat')")
        page.fill("#opening", "0")
        page.see("document.querySelector('form .primary').textContent.trim() === 'Konfirmasi saldo awal Rp0'")
        page.submit("#opening")
        page.see("document.body.innerText.includes('Saldo awal sudah ditentukan')")
        state = first.request("GET", "/financial-state", 200)
        check((state["opening"], state["balance"]), ("recorded", "0"))
        print("Onboarding UI: Rp0 is a recorded opening balance, Lewati is skipped; finance pages wait for it", flush=True)

        # Quick Add online without a vault: per-field errors keep other input; one tap, one activity.
        link(page, "Nanti saja")
        page.see("location.pathname === '/' && !!document.querySelector('[data-balance]')")
        check(page.js("document.querySelector('[data-balance]').textContent"), "Rp0")
        link(page, "Pemasukan")
        page.see("location.pathname === '/add/increase'")
        page.js("document.querySelector('details').open = true")
        page.fill("#title", "Gaji UI")
        page.fill("#amount", "12,5")
        save(page)
        page.see("document.querySelector('#amount-error')?.textContent.includes('bulat')")
        check((value(page, "#title"), value(page, "#amount")), ("Gaji UI", "12,5"))
        page.fill("#amount", "1.250.000")
        page.js("const f = document.querySelector('#amount').form; f.requestSubmit(); f.requestSubmit()")
        result(page, "Transaksi berhasil dicatat")
        page.js("new Promise(r => setTimeout(r, 500))")
        check(kinds(first), [("INCREASE", "1250000", "Gaji UI")])

        # Lost response: the server commits, the browser never sees it, the page looks it up.
        page.click("Catat lagi")
        page.fill("#amount", "50000")
        page.cdp("Fetch.enable", patterns=[{"urlPattern": "*/api/v1/activities", "requestStage": "Response"}])
        failed = []

        def drop(event):
            if event["request"]["method"] == "POST":
                failed.append(event)
                page.cdp("Fetch.failRequest", requestId=event["requestId"], errorReason="ConnectionReset")
            else:
                page.cdp("Fetch.continueRequest", requestId=event["requestId"])
        page.js("document.querySelector('#amount').form.requestSubmit()")
        intercept(page, drop, lambda: failed and page.js(
            "document.querySelector('[data-entry-result] strong')?.textContent === 'Transaksi berhasil dicatat'"))
        page.cdp("Fetch.disable")
        check(len(failed), 1)
        check(totals(first), (1300000, 0))
        check(len(kinds(first)), 2)
        link(page, "Ke Beranda")
        page.see("document.querySelector('[data-balance]')?.textContent === 'Rp1.300.000'")
        page.see("document.querySelector('.recent')?.textContent.includes('Gaji UI')")
        print("Quick Add online: field error keeps input, double submit makes one activity, lost response is "
              "looked up and confirmed once; Beranda shows the confirmed balance", flush=True)

        # Offline with the vault: new borrower, loan and repayment through the forms.
        enroll(page, origin)
        link(page, "Beranda")
        page.see("!!document.querySelector('[data-balance]')")
        network(page, False)
        link(page, "Tambah piutang")
        page.see("location.pathname === '/add/loan'")
        page.fill("#new-borrower", "Budi UI")
        page.click("Tambah peminjam")
        page.see("document.querySelector('#borrower').value.startsWith('c:')")
        page.fill("#amount", "100000")
        save(page)
        result(page, "Transaksi tersimpan offline")
        link(page, "Beranda")
        page.see("!!document.querySelector('[data-waiting]')")
        check(page.js("document.querySelector('[data-cache-time]') !== null"), True)
        link(page, "Terima pembayaran")
        page.see("location.pathname === '/add/repayment'")
        borrower = page.js("Array.from(document.querySelectorAll('#borrower option')).find(o => o.textContent.includes('Budi UI')).value")
        select(page, "#borrower", borrower)
        page.fill("#amount", "40000")
        save(page)
        result(page, "Transaksi tersimpan offline")
        check(totals(first), (1300000, 0))

        # A repayment above what is owed is a conflict, fixed from Sync Center with a new attempt.
        page.click("Catat lagi")
        select(page, "#borrower", borrower)
        page.fill("#amount", "999999")
        save(page)
        result(page, "Transaksi tersimpan offline")
        network(page, True)
        link(page, "Sinkronisasi")
        page.see("document.querySelectorAll('[data-state=SYNCED]').length === 3 && "
                 "document.querySelectorAll('[data-state=CONFLICT]').length === 1")
        check(totals(first), (1300000 - 60000, 60000))
        page.see("document.body.innerText.includes('piutang negatif')")
        link(page, "Perbaiki")
        page.see("location.pathname === '/add/repayment' && document.querySelector('#amount').value === '999999'")
        page.fill("#amount", "10000")
        save(page)
        page.see("location.pathname === '/sync'")
        page.see("document.querySelectorAll('[data-state=CONFLICT]').length === 0 && "
                 "document.querySelectorAll('[data-state=SYNCED]').length === 4")
        check(totals(first), (1300000 - 50000, 50000))
        print("Offline forms: borrower, loan and repayment saved encrypted and synced; a conflict is fixed from "
              "Sync Center as a new attempt", flush=True)

        # Soft Lock unmounts the form; the typed values are still there after the PIN.
        link(page, "Beranda")
        link(page, "Pengeluaran")
        page.fill("#amount", "777")
        page.js("document.querySelector('details').open = true")
        page.fill("#title", "Setengah jalan")
        page.shift(5 * MINUTE + 1000)
        page.see("!!document.querySelector('[data-soft-lock]') && !document.querySelector('#amount')")
        page.fill("#soft-pin", PIN)
        page.submit("#soft-pin")
        page.see("document.querySelector('#amount')?.value === '777'")
        check(value(page, "#title"), "Setengah jalan")
        save(page)
        # The test clock now runs 5 minutes ahead of the server, like a fast device clock: the server
        # refuses the future time and nothing is moved silently.
        result(page, "Transaksi belum dapat disimpan")
        page.see("document.body.innerText.includes('masa depan')")
        check(totals(first)[0], 1300000 - 50000)
        link(page, "Buka Sinkronisasi")
        link(page, "Perbaiki")
        page.see("location.pathname === '/add/deduct' && document.querySelector('#amount').value === '777'")
        page.fill("#when", past_now(first))
        save(page)
        page.see("location.pathname === '/sync' && document.querySelectorAll('[data-state=CONFLICT]').length === 0")
        try:
            wait_for(lambda: True if totals(first)[0] == 1300000 - 50000 - 777 else None, 30)
        except TimeoutError:
            queue = page.js("window.__duitSync.items().then(l => l.map(i => [i.state, i.code, i.payload.effectiveAt, i.attemptId]))")
            raise TimeoutError(f"corrected item not applied; queue {queue}; sync {page.js('window.__duitSync.state()')}; "
                               f"totals {totals(first)}; server {[(x['kind'], x.get('amount'), x['effectiveAt'], x.get('snapshotDelta')) for x in first.request('GET', '/activities', 200)['items']]}; "
                               f"real {datetime.now(UTC).isoformat()}")
        print("Soft Lock mid-form: page unmounted, input kept after PIN; a fast device clock gives a future-time "
              "conflict, fixed by editing the time", flush=True)

    # Offline boot straight to a form: unlock returns to it in-app, then it syncs once online.
    with chrome.run(blocked=True) as page:
        page.go(origin + "/add/deduct")
        page.see("location.pathname === '/add/deduct'")
        link(page, "Buka Akses Offline")
        page.status("hard")
        page.fill("#unlock-secret", PASSPHRASE)
        page.submit("#unlock-secret")
        page.see("location.pathname === '/add/deduct' && !!document.querySelector('nav a')")
        page.fill("#amount", "3000")
        # The test clock is still 5 minutes ahead, so give the real time explicitly.
        page.fill("#when", past_now(first))
        save(page)
        result(page, "Transaksi tersimpan offline")
    with chrome.run() as page:
        page.go(origin + "/offline")
        unlock(page, "passphrase", PASSPHRASE)
        deadline = time.time() + 30
        while totals(first)[0] != 1300000 - 50000 - 777 - 3000 and time.time() < deadline:
            time.sleep(0.2)
        check(totals(first), (1300000 - 50000 - 777 - 3000, 50000))
    print("Offline boot: form reachable without a reload, unlock returns to it, item syncs after restart", flush=True)
