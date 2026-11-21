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
