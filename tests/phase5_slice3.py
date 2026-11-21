"""Phase 5 slice 3 through the real UI in Chrome: Balance Adjustment with review, a backdated activity
that changes only the adjustment's delta (shown in Audit), borrower detail with its own history and a
preselected receivable form, and the Audit timeline."""
from datetime import datetime

from phase1_auth import check
from phase2_financial import activity, operation
from phase3_sync import totals
from phase4_offline import login, logout
from phase5_ui import link, result, save, user


def text(page, selector, wanted):
    page.see(f"document.querySelector({selector!r})?.textContent.includes({wanted!r})")


def slice3_test(chrome, origin, api_port, mail):
    client, email = user(api_port, origin, mail, "ui-slice3")
    with chrome.run() as page:
        page.go(origin + "/login")
        page.see("!!document.querySelector('#email')")
        page.js("localStorage.removeItem('__clock')")
        login(page, origin, email)
        link(page, "Beranda")
        page.see("location.pathname === '/onboarding'")
        page.fill("#opening", "100.000")
        page.submit("#opening")
        page.see("document.body.innerText.includes('Saldo awal sudah ditentukan')")
        link(page, "Nanti saja")

        # Balance Adjustment: target, not delta; a review step; recorded at server time.
        link(page, "Sesuaikan saldo")
        page.see("location.pathname === '/adjust' && document.querySelector('[data-current]')?.textContent === 'Rp100.000'")
        page.fill("#target", "abc")
        page.submit("#target")
        text(page, "[data-adjust-error]", "Rupiah bulat")
        page.fill("#target", "250.000")
        page.submit("#target")
        text(page, "[data-adjust-summary]", "Rp250.000")
        text(page, "[data-adjust-summary]", "Rp150.000")
        check(totals(client), (100000, 0))  # nothing applied before the confirmation
        page.click("Simpan penyesuaian")
        text(page, "[data-adjust-result]", "Rp250.000")
        check(totals(client), (250000, 0))
        items = client.request("GET", "/activities", 200)["items"]
        adjustment = next(a for a in items if a["kind"] == "ADJUSTMENT")
        opening = next(a for a in items if a["kind"] == "OPENING")
        check((adjustment["targetBalance"], adjustment["snapshotDelta"]), ("250000", "150000"))
        print("Adjustment UI: field error, review shows target and difference, nothing applied before confirm, "
              "then a snapshot at server time", flush=True)

        # A backdated income between the two snapshots: the target holds, only the delta moves.
        t0 = datetime.fromisoformat(opening["effectiveAt"])
        t1 = datetime.fromisoformat(adjustment["effectiveAt"])
        check(t1 > t0, True)
        operation(client, "/activities", activity("INCREASE", 5000, (t0 + (t1 - t0) / 2).isoformat(), title="Telat dicatat"))
        check(totals(client), (250000, 0))
        link(page, "Beranda")
        page.see("document.querySelector('[data-balance]')?.textContent === 'Rp250.000'")
        link(page, "Audit")
        page.see("location.pathname === '/audit' && !!document.querySelector('[data-action=BALANCE_ADJUSTMENT]')")
        text(page, "[data-action=ACTIVITY_CREATED] [data-snapshot-change]", "Rp150.000 → Rp145.000 (target tetap)")
        text(page, "[data-action=ACTIVITY_CREATED]", "Saldo Rp250.000 → Rp250.000")
        page.js("Array.from(document.querySelectorAll('[data-action=BALANCE_ADJUSTMENT] a')).find(a => a.textContent === 'Lihat transaksi').click()")
        page.see("location.pathname === '/activity/" + adjustment["id"] + "'")
        text(page, ".details", "Rp250.000 (selisih saat ini Rp145.000)")
        check(page.js("Array.from(document.querySelectorAll('button')).some(b => b.textContent.trim() === 'Hapus')"), False)
        print("Audit UI: ordered by action time; a backdated income shows the adjustment delta change with the "
              "target kept; snapshot detail has no edit or delete", flush=True)

        # Borrower detail: its own history, and the receivable form opens with the borrower chosen.
        link(page, "Piutang")
        page.fill("#borrower-name", "Tono UI")
        page.submit("#borrower-name")
        page.see("document.querySelector('[data-borrower-message]')?.textContent.includes('Peminjam ditambahkan')")
        link(page, "Tono UI")
        page.see("location.pathname.startsWith('/borrowers/') && !!document.querySelector('[data-borrower-detail]')")
        tono = page.js("location.pathname.split('/').pop()")
        link(page, "Catat pinjaman")
        page.see(f"location.pathname === '/add/loan' && document.querySelector('#borrower')?.value === 's:{tono}'")
        page.js("document.querySelector('details').open = true")
        page.fill("#title", "Tono pinjam")
        page.fill("#amount", "20000")
        save(page)
        result(page, "Transaksi berhasil dicatat")
        operation(client, "/activities", activity("INCREASE", 1, datetime.now().astimezone().isoformat()))  # unrelated
        link(page, "Piutang")
        link(page, "Tono UI")
        text(page, "[data-outstanding]", "Rp20.000")
        page.see("document.querySelectorAll('[data-borrower-history] li').length === 1")
        text(page, "[data-borrower-history]", "Tono pinjam")
        check(page.js("Array.from(document.querySelectorAll('button')).some(b => b.textContent.trim() === 'Arsipkan')"), False)
        print("Borrower detail UI: outstanding and only this borrower's history; Catat pinjaman preselects the "
              "borrower; no archive while unpaid", flush=True)
        logout(page, origin)
