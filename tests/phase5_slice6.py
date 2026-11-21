"""Phase 5 slice 6 through the real UI in Chrome: default categories offered on a new account, History
search and filters (PR-HIS-02), borrower profile edit with a stale-version refusal, and the logout warning
with a pending item (PR-OFF-10) that keeps the item for the same account."""
from phase1_auth import check
from phase2_financial import DEFAULT_CATEGORIES, activity, operation
from phase4_offline import PASSPHRASE, enroll, login, unlock
from phase4_sync_client import network
from phase5_manage import message
from phase5_ui import link, result, save, select, user


def rows(page):
    return page.js("Array.from(document.querySelectorAll('[data-history] li strong')).map(s => s.textContent)")


def slice6_test(chrome, origin, api_port, mail):
    client, email = user(api_port, origin, mail, "ui-slice6")
    operation(client, "/onboarding/skip-opening-balance")
    bills = next(c["id"] for c in client.request("GET", "/categories", 200) if c["name"] == "Tagihan")
    operation(client, "/activities", activity("DEDUCT", 50000, "2022-05-01T03:00:00Z", title="Pulsa 50%", categoryId=bills))
    operation(client, "/activities", activity("INCREASE", 900000, "2022-05-02T03:00:00Z", title="Gaji Mei"))
    rina = operation(client, "/borrowers", {"name": "Rina"})["resourceId"]

    with chrome.run() as page:
        page.go(origin + "/login")
        page.see("!!document.querySelector('#email')")
        login(page, origin, email)
        link(page, "Beranda")
        link(page, "Pengeluaran")
        page.js("document.querySelector('details').open = true")
        page.see("document.querySelectorAll('#category option').length === 11")  # Tanpa kategori + 10 defaults
        check(page.js("Array.from(document.querySelectorAll('#category option')).slice(1).map(o => o.textContent).sort()"),
              sorted(DEFAULT_CATEGORIES))
        link(page, "Audit")
        page.see("document.querySelector('[data-action=DEFAULT_CATEGORIES_CREATED]')?.textContent.includes('Kategori default dibuat')")
        print("Default categories UI: a new account is offered the ten defaults; the audit names them", flush=True)

        link(page, "Riwayat")
        page.see("document.querySelectorAll('[data-history] li').length === 2")
        page.js("document.querySelector('[data-history-filter]').closest('details').open = true")
        page.fill("#q", "50%")
        page.submit("#q")
        page.see("document.querySelectorAll('[data-history] li').length === 1")
        check(rows(page), ["Pulsa 50%"])
        page.fill("#q", "")
        select(page, "#kind", "INCREASE")
        page.fill("#from", "2022-05-02")
        page.fill("#to", "2022-05-02")
        page.submit("#q")
        page.see("document.querySelector('[data-history] li strong')?.textContent === 'Gaji Mei' && "
                 "document.querySelectorAll('[data-history] li').length === 1")
        select(page, "#kind", "")
        select(page, "#category", bills)
        page.fill("#from", "2022-05-02")
        page.submit("#q")
        page.see("document.querySelector('[data-history-empty]')?.textContent.includes('cocok')")
        page.fill("#from", "2022-05-03")
        page.fill("#to", "2022-05-01")
        page.submit("#q")
        page.see("document.querySelector('.notice.error')?.textContent.includes('Filter tidak valid')")
        page.click("Hapus filter")
        page.see("document.querySelectorAll('[data-history] li').length === 2")
        print("History UI: search with a literal %, kind + date filter, empty result, invalid range, clear", flush=True)

        link(page, "Piutang")
        link(page, "Rina")
        page.see("location.pathname.startsWith('/borrowers/') && !!document.querySelector('[data-borrower-detail]')")
        page.click("Ubah profil")
        page.fill("#b-name", "")
        page.submit("#b-name")
        page.see("document.querySelector('#b-name-error')?.textContent.includes('wajib')")
        page.fill("#b-name", "Rina Sari")
        page.fill("#b-phone", "0812 555")
        page.submit("#b-name")
        message(page, "borrower", "Profil peminjam disimpan")
        page.see("document.querySelector('#page-title').textContent === 'Rina Sari'")
        check({k: client.request("GET", "/borrowers/" + rina, 200)[k] for k in ("name", "phone", "version")},
              {"name": "Rina Sari", "phone": "0812 555", "version": 2})
        page.click("Ubah profil")
        operation(client, "/borrowers/" + rina, {"expectedVersion": 2, "name": "Rina (perangkat lain)"}, "PATCH")
        page.fill("#b-name", "Rina S")
        page.submit("#b-name")
        message(page, "borrower", "Data telah berubah di perangkat lain")
        page.see("document.querySelector('#page-title').textContent === 'Rina (perangkat lain)'")
        check(client.request("GET", "/borrowers/" + rina, 200)["name"], "Rina (perangkat lain)")
        print("Borrower UI: profile edit, empty name refused, stale version refused and reloaded", flush=True)

        # PR-OFF-10: logout with a pending item warns, can be cancelled, and keeps the item for this account.
        enroll(page, origin)
        link(page, "Beranda")
        page.see("!!document.querySelector('[data-balance]')")
        network(page, False)
        link(page, "Beranda")
        link(page, "Terima pembayaran")
        page.see("location.pathname === '/add/repayment'")
        select(page, "#borrower", "s:" + rina)
        page.fill("#amount", "1500")  # Rina owes nothing: a business conflict once it reaches the server
        save(page)
        result(page, "Transaksi tersimpan offline")
        network(page, True)
        link(page, "Sinkronisasi")
        page.see("document.body.textContent.includes('Konflik')")  # never retried automatically
        link(page, "Akun")
        page.see("Array.from(document.querySelectorAll('button')).some(b => b.textContent.trim() === 'Keluar')")
        page.click("Keluar")
        page.see("document.querySelector('[data-logout-warning]')?.textContent.includes('1 transaksi di perangkat ini belum tersinkron')")
        page.click("Batal")
        page.see("!document.querySelector('[data-logout-warning]') && location.pathname === '/account'")
        page.click("Keluar")
        page.see("!!document.querySelector('[data-logout-warning]')")
        link(page, "Perangkat")
        page.see("location.pathname === '/sessions' && !document.querySelector('[data-logout-warning]')")
        page.see("Array.from(document.querySelectorAll('button')).some(b => (b.getAttribute('aria-label') ?? '').endsWith(' ini'))")
        page.js("Array.from(document.querySelectorAll('button')).find(b => (b.getAttribute('aria-label') ?? '').endsWith(' ini')).click()")
        page.see("document.querySelector('[data-logout-warning]')?.textContent.includes('Cabut sesi ini')")
        page.click("Tetap keluar")
        page.see("location.pathname === '/login'")
        check([a for a in client.request("GET", "/activities", 200)["items"] if a["kind"] == "REPAYMENT"], [])
        login(page, origin, email)
        page.go(origin + "/offline")
        unlock(page, "passphrase", PASSPHRASE)
        link(page, "Sinkronisasi")
        page.see("document.body.textContent.includes('Konflik') && document.body.textContent.includes('Rp1.500')")
        print("Logout UI (PR-OFF-10): warning counts the unsynced item, cancel keeps the session, logout keeps the "
              "encrypted item for the same account", flush=True)
