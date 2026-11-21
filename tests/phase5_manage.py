"""Phase 5 slice 2 through the real UI in Chrome: categories (add, rename, archive, kept on edit),
confirmed activity edit with version conflict, delete refused by the receivable prefix, delete and
restore with Recently Deleted, borrower list with archive only at zero and reactivation."""
import json
import uuid

from phase1_auth import check
from phase3_sync import totals
from phase4_offline import login, logout
from phase5_ui import link, result, save, select, user


def row(page, attr, name, button):
    """Click a button inside the list row for one named item."""
    page.see(f"!!document.querySelector('[data-{attr}={json.dumps(name)}]')")
    page.see(f"""Array.from(document.querySelector('[data-{attr}={json.dumps(name)}]').querySelectorAll('button'))
        .some(b => b.textContent.trim() === {json.dumps(button)} && !b.disabled)""")
    page.js(f"""Array.from(document.querySelector('[data-{attr}={json.dumps(name)}]').querySelectorAll('button'))
        .find(b => b.textContent.trim() === {json.dumps(button)}).click()""")


def message(page, attr, text):
    page.see(f"document.querySelector('[data-{attr}-message]')?.textContent.includes({json.dumps(text)})")


def activities(client, deleted=False):
    return client.request("GET", "/activities" + ("?deleted=true" if deleted else ""), 200)["items"]


def open_activity(page, title):
    link(page, "Transaksi")  # bottom-nav slot for Riwayat
    page.see("location.pathname === '/history'")
    link(page, title)
    page.see("location.pathname.startsWith('/activity/') && !!document.querySelector('.details')")


def manage_test(chrome, origin, api_port, mail):
    client, email = user(api_port, origin, mail, "ui-manage")
    with chrome.run() as page:
        page.go(origin + "/login")
        page.see("!!document.querySelector('#email')")
        page.js("localStorage.removeItem('__clock')")
        login(page, origin, email)
        link(page, "Beranda")
        page.see("location.pathname === '/onboarding'")
        page.click("Lewati saldo awal")
        link(page, "Nanti saja")

        # Categories: add, rename, then archive one that history still uses.
        link(page, "Kategori")
        page.see("location.pathname === '/categories' && !!document.querySelector('#category-name')")
        for name in ("Makan", "Transport"):
            page.fill("#category-name", name)
            page.submit("#category-name")
            message(page, "category", f"Kategori {name} ditambahkan")
        row(page, "category", "Transport", "Ganti nama")
        page.see("!!document.querySelector('[data-category=Transport] input')")
        page.fill("[data-category=Transport] input", "Ojek")
        page.submit("[data-category=Transport] input")
        message(page, "category", "Nama kategori diganti")
        names = {c["name"]: c for c in client.request("GET", "/categories", 200) if c["name"] in ("Makan", "Ojek", "Transport")}
        check(sorted(names), ["Makan", "Ojek"])

        link(page, "Beranda")
        link(page, "Pengeluaran")
        page.js("document.querySelector('details').open = true")
        page.fill("#amount", "25000")
        page.fill("#title", "Makan siang")
        select(page, "#category", names["Makan"]["id"])
        save(page)
        result(page, "Transaksi berhasil dicatat")
        lunch = next(a for a in activities(client) if a.get("title") == "Makan siang")
        check((lunch["categoryId"], lunch["version"]), (names["Makan"]["id"], 1))

        link(page, "Kategori")
        row(page, "category", "Makan", "Arsipkan")
        message(page, "category", "Makan diarsipkan")
        check({c["name"]: c["archived"] for c in client.request("GET", "/categories", 200) if c["name"] in names},
              {"Makan": True, "Ojek": False})
        link(page, "Beranda")
        link(page, "Pengeluaran")
        page.see("Array.from(document.querySelectorAll('#category option')).some(o => o.textContent === 'Ojek')")
        check(page.js("Array.from(document.querySelectorAll('#category option')).some(o => o.textContent === 'Makan')"), False)
        print("Categories UI: add, rename, archive; an archived category is not offered for new activity", flush=True)

        # Edit a confirmed activity: archived category kept, amount changed, effective time unchanged.
        open_activity(page, "Makan siang")
        page.see("document.querySelector('.details').textContent.includes('Makan (diarsipkan)')")
        link(page, "Ubah")
        page.see("location.pathname === '/add/deduct' && document.querySelector('#amount').value === '25000'")
        check(page.js("document.querySelector('#category').value"), names["Makan"]["id"])
        page.fill("#amount", "30000")
        save(page)
        result(page, "Perubahan tersimpan")
        edited = client.request("GET", "/activities/" + lunch["id"], 200)
        check((edited["amount"], edited["categoryId"], edited["effectiveAt"], edited["version"]),
              ("30000", names["Makan"]["id"], lunch["effectiveAt"], 2))
        check(totals(client), (-30000, 0))

        # Another device changes it first: the stale save is refused; the latest version is reloaded.
        link(page, "Kembali ke detail")
        link(page, "Ubah")
        page.see("document.querySelector('#amount')?.value === '30000'")
        client.request("PATCH", "/activities/" + lunch["id"], (200, 201), data={
            "attemptId": str(uuid.uuid4()), "clientActivityId": str(uuid.uuid4()), "expectedVersion": 2,
            "kind": "DEDUCT", "amount": "31000", "effectiveAt": lunch["effectiveAt"], "title": "Makan siang",
            "categoryId": names["Makan"]["id"]})
        page.fill("#amount", "32000")
        save(page)
        result(page, "Transaksi belum dapat disimpan")
        page.see("document.body.innerText.includes('Muat ulang versi terbaru')")
        page.click("Muat versi terbaru")
        page.see("document.querySelector('#amount').value === '31000'")
        check(totals(client), (-31000, 0))
        print("Edit UI: confirmed activity edited online with the archived category kept and the instant unchanged; "
              "a stale version is refused and reloaded", flush=True)

        # Borrowers: archive is offered only at zero; reactivation brings it back.
        link(page, "Piutang")
        page.see("location.pathname === '/borrowers' && !!document.querySelector('#borrower-name')")
        page.fill("#borrower-name", "Sari UI")
        page.submit("#borrower-name")
        message(page, "borrower", "Peminjam ditambahkan")
        sari = next(b for b in client.request("GET", "/borrowers", 200) if b["name"] == "Sari UI")
        link(page, "Beranda")
        link(page, "Tambah piutang")
        select(page, "#borrower", "s:" + sari["id"])
        page.js("document.querySelector('details').open = true")
        page.fill("#title", "Pinjam Sari")
        page.fill("#amount", "50000")
        save(page)
        result(page, "Transaksi berhasil dicatat")
        link(page, "Piutang")
        page.see("document.querySelector('[data-borrower=\"Sari UI\"]')?.textContent.includes('Belum lunas')")
        check(page.js("Array.from(document.querySelectorAll('[data-borrower=\"Sari UI\"] button')).length"), 0)
        link(page, "Beranda")
        link(page, "Terima pembayaran")
        select(page, "#borrower", "s:" + sari["id"])
        page.js("document.querySelector('details').open = true")
        page.fill("#title", "Sari bayar")
        page.fill("#amount", "50000")
        save(page)
        result(page, "Transaksi berhasil dicatat")
        check(totals(client), (-31000, 0))

        # Deleting the loan would leave the repayment above what was owed at that point: refused whole.
        open_activity(page, "Pinjam Sari")
        page.click("Hapus")
        page.see("document.querySelector('dialog')?.open")
        page.fill("#delete-reason", "salah catat")
        page.submit("#delete-reason")
        message(page, "activity", "piutang negatif")
        check((len(activities(client)), len(activities(client, True)), totals(client)), (3, 0, (-31000, 0)))

        link(page, "Piutang")
        page.see("document.querySelector('[data-borrower=\"Sari UI\"]')?.textContent.includes('Lunas')")
        row(page, "borrower", "Sari UI", "Arsipkan")
        message(page, "borrower", "Sari UI diarsipkan")
        check(client.request("GET", "/borrowers/" + sari["id"], 200)["archived"], True)
        row(page, "borrower", "Sari UI", "Aktifkan kembali")
        message(page, "borrower", "Sari UI aktif kembali")
        check(client.request("GET", "/borrowers/" + sari["id"], 200)["archived"], False)
        print("Borrowers UI: Paid/Unpaid, archive only at zero, reactivate; a delete that breaks the receivable "
              "prefix is refused with nothing changed", flush=True)

        # Delete and restore: Recently Deleted lists it; restore puts it back at its original instant.
        open_activity(page, "Makan siang")
        page.click("Hapus")
        page.see("document.querySelector('dialog')?.open")
        page.submit("#delete-reason")
        message(page, "activity", "Transaksi dihapus")
        check(totals(client), (0, 0))
        link(page, "Kembali ke Riwayat")
        link(page, "Baru dihapus")
        page.see("location.search === '?deleted=1' && document.querySelector('[data-history]')?.textContent.includes('Makan siang')")
        link(page, "Makan siang")
        page.see("document.body.innerText.includes('sudah dihapus')")
        page.click("Pulihkan")
        message(page, "activity", "Transaksi dipulihkan")
        restored = client.request("GET", "/activities/" + lunch["id"], 200)
        check((restored["deleted"], restored["effectiveAt"], restored["amount"]), (False, lunch["effectiveAt"], "31000"))
        check((totals(client), len(activities(client, True))), ((-31000, 0), 0))
        print("Delete/restore UI: soft delete recalculates, Recently Deleted lists it, restore keeps the original "
              "effective time", flush=True)
        logout(page, origin)
