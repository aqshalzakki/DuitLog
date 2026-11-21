"""Phase 5 Reports through the real UI in Chrome: dashboard period statistics, the three report families
on fixed historical days with comparison text, category spending, and AC-20 (offline shows the
online-only message, never a cached official report)."""
from datetime import UTC, datetime

from phase1_auth import check
from phase2_financial import activity, operation
from phase4_offline import login, logout
from phase4_sync_client import network
from phase5_ui import link, select, user


def text(page, selector, wanted):
    page.see(f"document.querySelector({selector!r})?.textContent.includes({wanted!r})")


def reports_test(chrome, origin, api_port, mail):
    client, email = user(api_port, origin, mail, "ui-reports")
    operation(client, "/onboarding/skip-opening-balance")
    food = operation(client, "/categories", {"name": "Makan"})["resourceId"]
    tono = operation(client, "/borrowers", {"name": "Tono"})["resourceId"]
    for kind, amount, at, extra in [
        ("INCREASE", 1000, "2021-03-10T16:59:59.999999Z", {}),  # 10 March WIB
        ("INCREASE", 500, "2021-03-10T17:00:00Z", {}),  # 11 March WIB
        ("DEDUCT", 300, "2021-03-11T05:00:00Z", {"categoryId": food}),
        ("LOAN", 200, "2021-03-11T06:00:00Z", {"borrowerId": tono}),
        ("REPAYMENT", 50, "2021-03-11T07:00:00Z", {"borrowerId": tono}),
        ("LOAN", 70, "2021-03-11T08:00:00Z", {"borrowerId": tono, "affectCashBalance": False}),
        ("INCREASE", 4000, datetime.now(UTC).isoformat(), {}),  # this month, for the dashboard
    ]:
        operation(client, "/activities", activity(kind, amount, at, **extra))

    with chrome.run() as page:
        page.go(origin + "/login")
        page.see("!!document.querySelector('#email')")
        page.js("localStorage.removeItem('__clock')")
        login(page, origin, email)
        link(page, "Beranda")
        # Statistics follow the period; the current balance does not.
        text(page, "[data-stats-income]", "Rp4.000 · Baru")
        balance = page.js("document.querySelector('[data-balance]').textContent")
        check(balance, "Rp5.050")
        select(page, "#stats-period", "year")
        text(page, "[data-stats-income]", "Rp4.000")
        check(page.js("document.querySelector('[data-balance]').textContent"), balance)
        print("Dashboard statistics UI: period filter changes income/expense, not the confirmed balance", flush=True)

        link(page, "Lihat laporan dan grafik")
        page.see("location.pathname === '/reports' && !!document.querySelector('#period')")
        select(page, "#period", "day")
        page.fill("#date", "2021-03-11")
        page.submit("#date")
        text(page, "[data-report-range]", "11 Mar 2021")
        text(page, "[data-report-range]", "10 Mar 2021")  # comparison label
        text(page, "[data-income]", "Rp500 · turun 50,0%")
        text(page, "[data-expense]", "Rp300 · Baru")
        text(page, "[data-net]", "Rp200 · turun 80,0%")
        text(page, "[data-categories-report]", "Makan")
        check(page.js("document.querySelectorAll('[data-flow] tbody tr').length"), 1)

        page.click("Pergerakan saldo")
        text(page, "[data-opening]", "Rp1.000")
        text(page, "[data-closing]", "Rp1.050")
        page.click("Piutang")
        page.see("document.querySelector('[data-borrowers-report] tbody tr')?.textContent.includes('Tono')")
        check(page.js("Array.from(document.querySelectorAll('[data-borrowers-report] tbody td')).map(td => td.textContent)"),
              ["Rp0", "Rp270", "Rp50", "Rp220"])
        text(page, "[data-receivables-closing]", "Rp220")

        page.click("Pemasukan & pengeluaran")
        select(page, "#period", "month")
        page.fill("#date", "2021-03-01")
        page.submit("#date")
        page.see("document.querySelectorAll('[data-flow] tbody tr').length === 31")
        text(page, "[data-report-range]", "1 Mar 2021 – 31 Mar 2021")
        print("Reports UI: day and month on fixed WIB days, comparison text, categories, balance movement and "
              "receivables per borrower", flush=True)

        # AC-20: offline gives the online-only message and no figures.
        network(page, False)
        page.submit("#date")
        text(page, "[data-report-error]", "hanya tersedia saat online")
        check(page.js("document.querySelector('[data-report-summary]')"), None)
        network(page, True)
        page.submit("#date")
        page.see("!!document.querySelector('[data-report-summary]')")
        print("Reports offline (AC-20): online-only message, no cached official figures", flush=True)
        logout(page, origin)


def settings_test(chrome, origin, api_port, mail):
    """SCR-23: theme Light/Dark/System per device, and the account timezone with its warning (PR-RPT-10,
    PR-SET-01/02): after confirming, report days regroup and the audit shows the change."""
    client, email = user(api_port, origin, mail, "ui-settings")
    operation(client, "/onboarding/skip-opening-balance")
    operation(client, "/activities", activity("INCREASE", 500, "2021-03-10T17:00:00Z"))  # 11 March WIB, 10 March UTC

    with chrome.run() as page:
        page.go(origin + "/login")
        page.see("!!document.querySelector('#email')")
        login(page, origin, email)
        link(page, "Pengaturan")
        page.see("!!document.querySelector('#zone')")
        page.js("document.querySelector('input[value=dark]').click()")
        page.see("document.documentElement.dataset.theme === 'dark'")
        check(page.js("[localStorage.getItem('duit-theme'), getComputedStyle(document.body).backgroundColor]"),
              ["dark", "rgb(17, 22, 18)"])
        page.js("document.querySelector('input[value=system]').click()")
        page.see("!document.documentElement.hasAttribute('data-theme') && localStorage.getItem('duit-theme') === null")
        print("Settings UI: Light/Dark/System applied and stored per device", flush=True)

        text(page, "[data-current-zone]", "Asia/Jakarta")
        select(page, "#zone", "UTC")
        page.submit("#zone")
        text(page, "[data-zone-warning]", "Waktu transaksi yang tersimpan, saldo, dan piutang tidak berubah")
        check(client.request("GET", "/financial-state", 200)["timezone"], "Asia/Jakarta")  # nothing saved yet
        page.click("Ya, ubah zona waktu")
        text(page, "[data-current-zone]", "UTC")
        check(client.request("GET", "/financial-state", 200)["timezone"], "UTC")

        link(page, "Laporan")
        page.see("!!document.querySelector('#period')")
        select(page, "#period", "day")
        page.fill("#date", "2021-03-10")
        page.submit("#date")
        text(page, "[data-income]", "Rp500")
        link(page, "Audit")
        page.see("document.body.textContent.includes('Zona waktu akun diubah')")
        print("Settings UI: timezone change needs confirmation, regroups report days, shows in audit", flush=True)

        # Cold loads: the zone arrives after the page is set up. Tokyo has no DST, New York is behind WIB.
        client.request("PUT", "/settings/timezone", 200, data={"timezone": "Asia/Tokyo"})
        page.go(origin + "/add/increase")
        page.see("document.querySelector('label[for=when]')?.textContent.includes('Asia/Tokyo')")
        page.see("[0, 60e3].map(d => new Date(Date.now() + 9 * 3600e3 - d).toISOString().slice(0, 16))"
                 ".includes(document.querySelector('#when').value)")
        page.fill("#amount", "7")
        page.submit("#amount")
        page.see("document.body.textContent.includes('Transaksi berhasil dicatat')")
        latest = client.request("GET", "/activities", 200)["items"][0]
        check((latest["amount"], abs(datetime.fromisoformat(latest["effectiveAt"]) - datetime.now(UTC)).total_seconds() < 120),
              ("7", True))
        client.request("PUT", "/settings/timezone", 200, data={"timezone": "America/New_York"})
        page.go(origin + "/reports")
        page.see("!!document.querySelector('[data-report-summary]')")
        check(page.js("document.querySelector('#date').value === new Intl.DateTimeFormat('en-CA', "
                      "{ timeZone: 'America/New_York' }).format(new Date())"), True)
        print("Settings UI: cold-loaded form and report use the account zone (Tokyo prefill, New York today)", flush=True)
        logout(page, origin)
