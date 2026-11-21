"""Phase 5 slice 7 through the real UI in Chrome: login lands on Beranda, the five-slot mobile bottom
navigation with its + menu (PRD §3.1, PR-UX-03), and related audit in transaction detail (PR-HIS-03)."""
from phase1_auth import check
from phase2_financial import operation
from phase4_offline import DESKTOP, MOBILE, login
from phase5_ui import link, result, save, user


def slice7_test(chrome, origin, api_port, mail):
    client, email = user(api_port, origin, mail, "ui-slice7")
    operation(client, "/onboarding/skip-opening-balance")

    with chrome.run() as page:
        login(page, origin, email)
        page.see("location.pathname === '/' && !!document.querySelector('[data-balance]')")
        try:
            page.cdp("Emulation.setDeviceMetricsOverride", **DESKTOP)
            page.see("getComputedStyle(document.querySelector('[data-bottom-nav]')).display === 'none'")
            print("Login UI: lands on Beranda; no bottom navigation on desktop", flush=True)
            page.cdp("Emulation.setDeviceMetricsOverride", **MOBILE)
            page.see("getComputedStyle(document.querySelector('[data-bottom-nav]')).display === 'grid'")
            check(page.js("Array.from(document.querySelectorAll('[data-bottom-nav] > a, [data-bottom-nav] button'))"
                          ".map(e => e.textContent.trim())"), ["Beranda", "Transaksi", "+ Tambah", "Piutang", "Laporan"])
            check(page.js("Array.from(document.querySelectorAll('.topbar .in-bottom')).every(a => getComputedStyle(a).display === 'none')"), True)
            check(page.js("document.documentElement.scrollWidth <= window.innerWidth"), True)  # no sideways scroll
            check(page.js("[...document.querySelectorAll('[data-bottom-nav] > a, [data-bottom-nav] button')]"
                          ".every(e => e.getBoundingClientRect().height >= 44)"), True)  # touch targets

            page.click("+ Tambah")
            page.see("document.querySelector('[data-bottom-nav] button').getAttribute('aria-expanded') === 'true' && "
                     "document.querySelectorAll('#add-menu a').length === 4")
            page.js("document.querySelector('.add').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
            page.see("!document.querySelector('#add-menu') && document.activeElement === document.querySelector('[data-bottom-nav] button')")
            page.click("+ Tambah")
            page.see("!!document.querySelector('#add-menu')")
            page.js("Array.from(document.querySelectorAll('#add-menu a')).find(a => a.textContent === 'Pengeluaran').click()")
            page.see("location.pathname === '/add/deduct' && !document.querySelector('#add-menu')")
            page.js("document.querySelector('details').open = true")
            page.fill("#amount", "2500")
            page.fill("#title", "Parkir mobile")
            save(page)
            result(page, "Transaksi berhasil dicatat")
            print("Mobile UI: five slots, header duplicates hidden, no sideways scroll, 44px targets, + menu opens, "
                  "Escape closes and returns focus, choice navigates and closes", flush=True)

            page.js("Array.from(document.querySelectorAll('[data-bottom-nav] a')).find(a => a.textContent === 'Transaksi').click()")
            page.see("location.pathname === '/history'")
            link(page, "Parkir mobile")
            page.see("document.querySelector('[data-related-audit] [data-action=ACTIVITY_CREATED]')?.textContent"
                     ".includes('Transaksi dicatat')")
            check(page.js("document.querySelectorAll('[data-related-audit] li').length"), 1)
            print("Detail UI: related audit lists this transaction's entries only", flush=True)

            # WCAG 2.2 SC 2.4.11: a focused control is never hidden under the fixed bar.
            link(page, "Kategori")
            page.see("document.querySelectorAll('[data-category]').length >= 10")
            check(page.js("""(() => {
                const nav = document.querySelector('[data-bottom-nav]').getBoundingClientRect().top
                const controls = [...document.querySelectorAll('main button, main input, main a')]
                return controls.every((c) => { c.focus(); const r = c.getBoundingClientRect(); return r.bottom <= nav + 0.5 })
            })()"""), True)
            page.click("+ Tambah")
            page.see("!!document.querySelector('#add-menu')")
            page.js("document.querySelector('main').dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))")
            page.see("!document.querySelector('#add-menu')")  # a tap elsewhere closes it
            print("Mobile UI: focused controls stay above the bar; tapping outside closes the + menu", flush=True)
        finally:
            page.cdp("Emulation.setDeviceMetricsOverride", **MOBILE)
