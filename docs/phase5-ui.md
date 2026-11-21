# Fase 5 · Product UX (slice 1–7)

Slice ini mencakup SCR-05, SCR-06, SCR-09 (sebagian), SCR-10, SCR-11, SCR-19 dan SCR-21 (koreksi konflik). Rujukan: PR-BAL-01, PR-DASH-01/05/06/07/08, PR-TXN-01–08 (tanpa lampiran), PR-REC-01/03/04/09, PR-OFF-03–05, dan §6.4. **Fase 5 dan gate G4 belum selesai.**

Slice 2 menambah Riwayat, detail, edit/hapus/restore, Baru dihapus, Kategori, dan Piutang (daftar peminjam).
Slice 4 menambah Laporan (SCR-20) dan statistik periode di Beranda (sebagian SCR-09). Rujukan: BR-RPT-01–08, BR-RPT-11, PR-DASH-02/03, PR-RPT-01–06, AC-20.
Slice 7 menambah pendaratan di Beranda setelah login/verifikasi, navigasi bawah mobile lima slot, dan Audit terkait di Detail transaksi. Rujukan: PRD §3.1, PR-UX-03, PR-HIS-03.
Slice 6 menambah kategori default, pencarian/filter Riwayat, ubah profil peminjam, dan peringatan logout bila ada pending. Rujukan: BR-HIS-01, BR-HIS-06, BR-OFF-16, PR-CAT-01, PR-HIS-02, PR-OFF-10, PR-SEC-07.
Slice 5 menambah Pengaturan (sebagian SCR-23): tema dan zona waktu akun. Rujukan: BR-RPT-11, BR-UX-03, PR-RPT-10, PR-SET-01/02, PR-NFR-11.
Slice 3 menambah Penyesuaian Saldo (SCR-16), Detail Peminjam (SCR-18), dan Audit (SCR-24). Rujukan: PR-BAL-02–04, PR-BAL-06, PR-REC-06/07, PR-HIS-08.

Belum termasuk:
- Ekspor PDF/Excel dan status job (Fase 6, worker)
- Daftar detail transaksi di halaman Laporan. Ringkasan, seri, dan tabel per kategori/peminjam sudah ada; daftar per transaksi menyusul bersama ekspor.
- Grafik di Beranda. Beranda hanya menampilkan ringkasan periode dengan tautan ke Laporan, tempat grafik berada.
- Perbandingan periode untuk Pergerakan Saldo dan Piutang. Yang ada baru perbandingan pemasukan, pengeluaran, dan selisih bersih.
- Draft persisten, lampiran, dan Audit History
- Bagian lain SCR-23: profil, PIN/keamanan, dan hapus data offline. Sesi perangkat tetap di `/sessions`.
- Peringatan logout di halaman verifikasi email (`AuthPage`). Akun belum terverifikasi tidak bisa punya pending, jadi halaman ini dibiarkan.
- Sidebar desktop. Desktop tetap memakai navigasi atas yang membungkus; fungsinya sama dengan navigasi bawah mobile.
- Indikator sinkron di header mobile. Tautan Sinkronisasi tetap di navigasi atas.

## Perilaku

| Bagian | Implementasi |
| --- | --- |
| Saldo awal (`/onboarding`) | Halaman keuangan mengarahkan ke sini selama `opening` masih `pending` pada jawaban server live. Tombol berganti menjadi "Konfirmasi saldo awal Rp0" bila isiannya 0, terpisah dari "Lewati saldo awal". Nilai negatif diterima. Attempt yang hasilnya belum diketahui dipakai ulang dan isiannya dikunci. Sesudahnya ada tawaran Akses Offline yang bisa dilewati. |
| Beranda (`/`) | Saldo terkonfirmasi dan total piutang dari `/financial-state`. Peringatan freeze dan recovery. Empat tombol Quick Add. Lima aktivitas terbaru, dengan label "Tidak memengaruhi saldo". Offline: salinan terenkripsi di vault dari jawaban live terakhir untuk owner yang sama, dengan waktu pembaruan. Ada item yang belum tersinkron → "Estimasi belum tersedia" dan tautan Sinkronisasi. Pending tidak pernah dijumlahkan. |
| Form (`/add/increase`, `deduct`, `loan`, `repayment`) | Nominal tetap string. Titik ribuan boleh. 0, desimal, dan bukan-angka ditolak per field tanpa menghapus isian lain. Peminjam dipilih dari daftar aktif atau ditambah di tempat. Saat offline, peminjam baru masuk antrean sebagai `borrowerClientId`. Pinjaman dan pembayaran punya toggle "Memengaruhi saldo utama" yang default menyala. Kategori hanya yang aktif. |
| Jalur simpan | Vault terbuka → antrean engine sync, baik online maupun offline, lalu status item ditampilkan. Tanpa vault dan online → `POST` langsung. ID percobaan disimpan di Pinia: hasil tak diketahui → lookup, lalu 404 → attempt yang sama dikirim ulang sekali. Penolakan ber-kode → attempt baru untuk koreksi. Satu `clientActivityId` tidak pernah lewat dua jalur. Tanpa vault dan offline → arahan membuka Akses Offline. |
| Status setelah Simpan | Teks mengikuti §6.4: berhasil dicatat, tersimpan offline, memeriksa hasil (dengan tombol "Periksa hasil"), atau belum dapat disimpan beserta alasannya. Form dikunci sampai hasilnya jelas, jadi satu tap menghasilkan satu aktivitas. |
| Waktu | Kolom waktu yang tidak disentuh berarti instan saat Simpan, bukan menit yang ditampilkan. Kalau dibulatkan ke menit, transaksi bisa jatuh sebelum snapshot yang baru dibuat dan terserap. Koreksi memakai instan aslinya kecuali waktunya diubah. Waktu masa depan ditolak lebih dulu dengan jam perangkat, dan keputusan akhir tetap di server. |
| Koreksi | Sinkronisasi menampilkan "Perbaiki" untuk konflik aktivitas, kecuali `ALREADY_CONFIRMED_ACTIVITY`. Tautan membuka form yang sama dengan jenis tetap. Simpan → attempt baru → siklus sync. |
| Kunci | Isian form ada di memori Pinia tab ini, jadi tetap ada setelah Soft Lock meng-unmount halaman. Isian dibuang saat ganti owner. Tidak ada yang disimpan persisten; draft terenkripsi adalah slice berikutnya. |
| Offline boot | Navigasi tampil saat server tidak terjangkau dan vault ada. Form punya tautan ke `/offline?back=…`. Setelah unlock, aplikasi kembali ke halaman itu lewat navigasi in-app. |

| Riwayat (`/history`) | Aktivitas tercatat dari server, terbaru dulu, dengan "Muat lagi" lewat `nextCursor`. Bagian "Belum tersinkron" dari antrean vault diberi label status dan tidak dijumlahkan. Offline: hanya antrean, dengan catatan bahwa riwayat tercatat perlu online. |
| Baru dihapus (`/history?deleted=1`) | Aktivitas yang dihapus, disimpan tanpa batas waktu. Tidak ada hapus permanen. |
| Detail (`/activity/:id`) | Jenis, nominal, waktu efektif WIB, kategori (dengan "(diarsipkan)"), peminjam, dan pengaruh saldo. Snapshot menampilkan target dan selisih, tanpa Ubah/Hapus. Hapus memakai dialog dengan alasan opsional. Pulihkan mengembalikan transaksi ke waktu efektif aslinya. Semua dikirim dengan `expectedVersion` dan attempt yang dipakai ulang bila hasilnya belum diketahui. |
| Ubah (`/add/<jenis>?edit=<id>`) | Form yang sama, jenis tetap. Hanya online. Data dimuat dari server, lalu `PATCH` dengan versi yang ditampilkan. Kategori atau peminjam yang sudah diarsipkan boleh tetap dipakai, tetapi tidak bisa dipilih baru. Waktu tetap instan asli kecuali diubah. `VERSION_CONFLICT` → "Muat versi terbaru". Edit yang sudah selesai dimuat ulang dari server saat halaman dibuka lagi. |
| Kategori (`/categories`) | Tambah, ganti nama, arsip, aktifkan kembali. Hanya online. |
| Piutang (`/borrowers`) | Total piutang, daftar peminjam dengan sisa dan Lunas/Belum lunas, dan tambah peminjam (lewat antrean vault bila terbuka). "Arsipkan" hanya untuk yang lunas; server tetap memutuskan (`BORROWER_OUTSTANDING`). "Aktifkan kembali" online. |

| Penyesuaian (`/adjust`) | Hanya online, dibuka dari Beranda dan bukan dari Quick Add. Isinya target saldo (boleh Rp0 atau negatif), lalu ringkasan: saldo yang ditinjau, target, selisih, dan "waktu server saat disimpan". Tidak ada yang diterapkan sebelum "Simpan penyesuaian". Attempt dipakai ulang bila hasilnya belum diketahui. Gagal → target tidak ditampilkan seolah sudah diterapkan. |
| Detail peminjam (`/borrowers/:id`) | Sisa piutang, Lunas/Belum lunas, kontak, dan riwayat pinjaman/pembayaran lewat `GET /activities?borrowerId=` dengan "Muat lagi". "Catat pinjaman" dan "Terima pembayaran" membuka form dengan peminjam sudah dipilih, hanya bila form itu belum diisi. Arsip hanya saat lunas; aktifkan kembali. Hanya online. |
| Audit (`/audit`) | Urut menurut waktu aksi server. Label aksi, waktu WIB, aktor operator bila bukan pemilik, alasan, field yang berubah (sebelum → sesudah), saldo dan piutang sebelum → sesudah, perubahan selisih setiap titik saldo dengan "target tetap", reaktivasi peminjam otomatis, dan tautan ke transaksi. Kategori/peminjam yang berubah ditampilkan sebagai id. Hanya online. |

## Laporan (slice 4)

`GET /reports/{income-expense|balance-movement|receivables}?period=day|week|month|year&date=YYYY-MM-DD`, atau `period=custom&from=…&to=…`. Endpoint ini hanya online, memakai data terkonfirmasi, dan dibatasi owner.

| Bagian | Implementasi |
| --- | --- |
| Konsistensi | Ledger, kategori, dan peminjam dibaca dalam satu transaksi InnoDB REPEATABLE READ (default; pool tidak mengubahnya). Tidak mengambil lock akun. |
| Sumber angka | Saldo dan piutang pembuka/penutup memakai `model::replay` pada prefiks ledger, dan delta snapshot diambil dari replay penuh. Pergerakan dalam rentang memakai `Activity::signed_amount`/`moves_cash`, helper yang juga dipakai `replay`, jadi aturan kasnya tidak diduplikasi. Server memeriksa pembuka + komponen = penutup dan per peminjam awal + pinjaman − pembayaran = akhir; selisih berarti defect (500). |
| Pemasukan/pengeluaran | Hanya Increase/Deduct yang tidak terhapus. Pinjaman, pembayaran, snapshot, dan pending tidak dihitung. Kategori null = "Tanpa kategori"; kategori arsip tetap muncul. |
| Periode | Batas dihitung di server dengan zona waktu akun (slice 5; sebelumnya tetap Asia/Jakarta). Minggu mulai Senin. Periode berjalan dipotong di "sekarang" dan dibandingkan dengan waktu berlalu yang sama sejak awal periode sebelumnya, dipotong di akhirnya (31 Maret ↔ Februari penuh). Periode selesai dibandingkan dengan periode penuh sebelumnya. Custom dibandingkan dengan rentang sama panjang tepat sebelumnya. Periode di masa depan, custom terbalik, atau lebih dari 5 tahun → 422. |
| Perbandingan | Integer saja, persepuluhan persen dibulatkan menjauhi nol, terhadap \|sebelumnya\|. Keduanya 0 → `ZERO` ("0%"). Sebelumnya 0 dan sekarang positif → `NEW` ("Baru"). Sebelumnya 0 dan sekarang negatif → `NO_BASELINE`, dijelaskan di UI. |
| Seri | Harian sampai 92 hari, bulanan untuk tahunan atau rentang lebih panjang. Pergerakan saldo memberi saldo akhir per bucket. |
| Freeze/recovery | Laporan ditolak dengan kode yang sama dengan mutasi (423/503). Angka dari ledger yang belum diverifikasi tidak ditampilkan seolah resmi. |
| UI `/reports` | Hanya online (`session` + `verified`) dan tidak pernah disimpan ke cache vault. Tiga tab, pilihan periode dan tanggal atau rentang, serta label rentang dan pembanding. Grafik berupa tabel dengan bar CSS: pemasukan polos, pengeluaran/negatif bergaris, jadi warna bukan satu-satunya pembeda, dan angka selalu tertulis. Gagal tanpa jawaban server → "Laporan hanya tersedia saat online", tanpa angka. |
| Beranda | Statistik periode (harian sampai tahunan) dari endpoint yang sama, hanya online. Saldo terkonfirmasi dan piutang di atasnya tidak bergantung pada periode. |

**Usulan, dapat direview:** minggu mulai Senin; batas custom 5 tahun; laporan ditolak saat freeze/recovery; cara baca persen terhadap baseline negatif.

`shortcut:` setiap laporan memuat dan me-replay seluruh ledger owner. Perlu total tersimpan atau replay ber-checkpoint bila ledger mencapai puluhan ribu baris.

Backend slice 3:
- `GET /activities` menerima `borrowerId` (UUID, dibatasi owner, bisa digabung dengan `before` dan `deleted`).
- Parameter query yang tidak valid di `/activities` dan `/audit` sekarang dijawab `422 VALIDATION_ERROR` dengan bentuk error API. Sebelumnya axum mengirim 400 berupa teks biasa.
- Diuji di `phase2_financial.py`: hanya aktivitas peminjam itu, peminjam lain kosong, akun lain kosong, kursor, dan tiga query yang salah.

**Usulan, dapat direview:** rute `/add/:kind` dan `/onboarding`, Beranda di `/`, serta teks label.

## Pengaturan (slice 5)

| Bagian | Implementasi |
| --- | --- |
| Penyimpanan zona | Migrasi `0003_timezone.sql`: kolom `financial_accounts.timezone`, default `Asia/Jakarta`. Instant, snapshot, dan saldo tidak disentuh, jadi mengganti zona hanya mengubah pengelompokan. |
| Zona yang didukung | Semua zona IANA. `jiff =1.0.1` (fitur `std`, `tz-fat`, `tzdb-bundle-always`) membawa tzdb sendiri, jadi aturannya sama di Windows dan di image Docker minimal tanpa `/usr/share/zoneinfo`. Dependensi baru: jiff, jiff-core, jiff-tzdb. Hari DST bisa 23 atau 25 jam; tengah malam yang tidak ada diganti instant pertama sesudah celah. |
| `PUT /settings/timezone {timezone}` | Nama zona yang tidak dikenal, kosong, atau lebih dari 64 karakter → 422. Dijalankan dalam transaksi dengan lock akun (`anchor` FOR UPDATE), dan audit `TIMEZONE_CHANGED` mencatat nilai sebelum dan sesudah. Kalau nilainya sama, tidak ada perubahan dan tidak ada audit. Versi state finansial tidak naik karena ini bukan mutasi finansial. Karena menulis `financial_audit`, perubahan ditolak saat freeze akun (423) atau recovery global (503), sama seperti sync. |
| `/financial-state` | Menyertakan `timezone`. Frontend memakainya, juga dari cache vault saat offline, untuk input waktu efektif, tampilan waktu, dan "hari ini". Konversi memakai offset Intl per instant, jadi DST ikut terhitung. Waktu dinding di celah DST jatuh tepat sesudah celah; di tumpang-tindih, salah satu dari dua instant. Label "WIB" yang tetap diganti nama zona dari Intl. Logout atau ganti akun mengembalikan zona ke default. Zona bersifat reaktif: form baru mengisi ulang waktu yang belum disentuh setelah state dimuat, dan Laporan memuat state lebih dulu sebelum menentukan "hari ini". Waktu yang belum disentuh tetap dikirim sebagai instant "sekarang", bukan teks yang tampil. |
| UI `/settings` | Pilihan zona dari `Intl.supportedValuesOf('timeZone')` ditambah `UTC`, karena Chrome tidak mencantumkannya. Saat diuji, ke-418 zona dari daftar Intl Node dikenali tzdb jiff. Sebelum menyimpan, UI meminta konfirmasi dengan peringatan bahwa tanggal transaksi lama bisa pindah grup (PR-RPT-10). Zona hanya bisa diubah saat online. |
| Tema | Terang/Gelap/Ikuti sistem lewat `data-theme` di `<html>` dan token warna CSS (`color-scheme` ikut). Pilihan disimpan per perangkat di `localStorage` (`duit-theme`). Isinya bukan data finansial, dan kalau storage diblokir, pilihan hanya berlaku di halaman itu. |

**Usulan, dapat direview:** tema disimpan per perangkat, bukan per akun di server (PR-SET-01 meminta "dipertahankan", tanpa menyebut lintas perangkat). Endpoint `PUT /settings/timezone`. Ganti zona ditolak saat freeze/recovery. Kontras token diukur dengan rumus WCAG untuk kedua palet: teks ≥ 4,5:1 (terendah: teks redup 7,1:1 terang dan 7,8:1 gelap), fokus dan border field ≥ 3:1. Border select/textarea dipindah dari `--border` (sekitar 1,6:1, gagal 1.4.11, sudah ada sejak sebelumnya) ke `--field-border`. Uji manual dengan pembaca layar dan zoom belum dilakukan.

## Slice 6

| Bagian | Implementasi |
| --- | --- |
| Kategori default | 10 nama (keputusan pemilik): Makan & Minum, Transportasi, Belanja, Tagihan, Kesehatan, Hiburan, Pendidikan, Gaji, Bonus, Lainnya. Disemai sekali di `store::anchor`, dalam transaksi tulis pertama akun, bersama satu audit `DEFAULT_CATEGORIES_CREATED`. Setelah itu kategori ini sama seperti kategori personal: bisa diganti nama dan diarsipkan. Migrasi `0004_default_categories.sql` menambah flag `default_categories` dengan default TRUE (akun lama langsung tertandai selesai dalam satu statement, jadi tidak diubah diam-diam), lalu default kolom diubah menjadi FALSE untuk akun baru. Flag dibaca di SELECT `FOR UPDATE` akun yang memang sudah ada, jadi tidak ada query tambahan per tulis. Upsert akun tetap `ON DUPLICATE KEY UPDATE`, yang langsung mengambil lock eksklusif. Versi pertama memakai `INSERT IGNORE` dan uji tab paralel gagal sekali; dugaan penyebabnya deadlock karena lock bersama dinaikkan ke `FOR UPDATE`. Log tidak menunjukkan kode 1213, jadi penyebab itu belum terbukti. Setelah kembali ke upsert, uji itu lulus di setiap putaran berikutnya. |
| Filter Riwayat | `GET /activities` menerima `q` (judul/deskripsi, ≤100 karakter, `%` dan `_` literal, tidak peka huruf besar lewat collation kolom), `kind`, `category` (UUID atau `none`), serta `from`/`to` (tanggal di zona akun; satu sisi saja berarti terbuka ke arah lain; `from` setelah `to` → 422; tanpa batas panjang karena hasil dipaginasi). Semua digabung dengan AND, dibatasi owner, dan kursor `before` tetap jalan di dalam filter. Nilai tidak valid → 422. Query dibangun dengan `sqlx::QueryBuilder` dan parameter terikat. |
| UI Riwayat | Panel "Cari dan filter" (`<details>`, terbuka saat ada filter). Hasil kosong dan filter tidak valid diumumkan. Filter hanya untuk transaksi tercatat; item yang belum tersinkron tetap tampil di atasnya. |
| Profil peminjam | "Ubah profil" di Detail Peminjam: nama wajib, telepon dan catatan opsional. Lewat `PATCH /borrowers/{id}` dengan `expectedVersion` dan `attemptId` yang sama saat hasilnya belum diketahui. Versi basi → pesan `VERSION_CONFLICT` dan data terbaru dimuat ulang. |
| Peringatan logout | Di `/account` dan `/sessions`, "Keluar", "Keluar dari semua perangkat", dan "Cabut" pada sesi perangkat ini lebih dulu menampilkan peringatan bila: ada item antrean yang belum `SYNCED`, ada transaksi online yang sedang dikirim/diperiksa, atau Akses Offline milik akun ini terkunci (jumlahnya tidak bisa dihitung). "Tetap keluar" melanjutkan; tidak ada data lokal yang dihapus. Helper uji `logout()` kini mengonfirmasi peringatan itu. |

**Usulan, dapat direview:** nama aksi audit `DEFAULT_CATEGORIES_CREATED` (label "Kategori default dibuat" beserta daftar namanya di Audit); pencarian tidak mencakup nama kategori atau peminjam.

## Slice 7

| Bagian | Implementasi |
| --- | --- |
| Pendaratan | Login dan verifikasi email berhasil → `/` (Beranda). Guard yang ada mengarahkan akun belum terverifikasi ke verifikasi dan akun dengan saldo awal pending ke `/onboarding`. `/verify-email` untuk akun terverifikasi → Beranda. |
| Navigasi bawah | Di bawah 40rem: Beranda · Transaksi · + Tambah · Piutang · Laporan (Laporan hanya untuk sesi terverifikasi, jadi tidak ada saat boot offline). Tautan yang sama di header disembunyikan di mobile; sisanya (Kategori, Sinkronisasi, Offline, Pengaturan, Akun, Perangkat, Audit) tetap di header yang membungkus. "+ Tambah" adalah tombol `aria-expanded` yang membuka empat pilihan Quick Add; Escape menutup dan mengembalikan fokus, dan pindah rute juga menutup. `viewport-fit=cover` di `index.html` mengaktifkan inset safe area: navigasi bawah memakai inset bawah dan header inset atas. Target sentuh ≥ 44px. `main` diberi ruang bawah, dan `scroll-padding-bottom` menjaga kontrol yang difokus tidak tertutup bar (WCAG 2.2 SC 2.4.11). Ketukan di luar menu + menutupnya. Di Detail, status "memuat" dan "gagal" dibedakan. Semua perjalanan UI diuji di viewport ponsel 390px (sudah begitu sejak awal). Helper `link()` kini hanya mengklik tautan yang terlihat, jadi salinan header yang disembunyikan di mobile tidak pernah diklik; uji Riwayat memakai slot "Transaksi". Slice 7 memeriksa lebar desktop 1280px terpisah. |
| Audit terkait | `GET /audit?resourceId=` (UUID, owner-scoped, kursor tetap jalan): entri dengan `details.resourceId` itu, ditambah entri yang `snapshotChanges`-nya menghitung ulang resource itu sebagai titik saldo. Detail transaksi menampilkan label aksi dan waktu aksi, dengan tautan ke Audit untuk rincian sebelum/sesudah. Label aksi dipindah ke `messages.ts` dan dipakai bersama. |

`shortcut:` filter audit memakai `JSON_EXTRACT` dan memindai baris audit owner. Perlu kolom `resource_id` berindeks bila audit owner mencapai puluhan ribu baris. Detail transaksi hanya memuat halaman pertama (50 entri).

## Verifikasi

`tests/phase5_ui.py` dijalankan oleh `--offline`. Semua langkah lewat UI sungguhan: klik tautan, isi field, submit. Tidak ada hook DEV.

| Kasus | Hasil |
| --- | --- |
| Saldo awal | Beranda mengarah ke `/onboarding`. "abc" ditolak per field. "0" → tombol "Konfirmasi saldo awal Rp0" → server `recorded`, saldo 0. Akun lain "Lewati" → `skipped`. |
| Quick Add online | "12,5" ditolak dan judul tetap terisi. "1.250.000" dengan dua submit beruntun → satu aktivitas. |
| Respons hilang | Respons `POST /activities` digagalkan setelah commit → "Memeriksa hasil" → lookup → "Transaksi berhasil dicatat". Efek sekali. Beranda menampilkan Rp1.300.000 dan aktivitas terbaru. |
| Offline | Peminjam baru, pinjaman, dan pembayaran lewat form saat offline → "Transaksi tersimpan offline". Beranda menampilkan data cache bertanda waktu dan "Estimasi belum tersedia". Server tidak berubah. Online → semua `SYNCED`, saldo dan piutang tepat. |
| Konflik | Pembayaran melebihi piutang → `CONFLICT` "piutang negatif" → "Perbaiki" → nominal diubah → `SYNCED`. |
| Soft Lock | Form ter-unmount, dan isian kembali setelah PIN. Jam uji yang 5 menit lebih cepat membuat server menolak waktu masa depan. Ditampilkan sebagai konflik, waktu dikoreksi lewat form, lalu `SYNCED`. |
| Offline boot (slice 1) | Chrome di-restart dengan API diblokir: `/add/deduct` → "Buka Akses Offline" → unlock → kembali ke form tanpa reload → tersimpan offline. Restart dengan API terbuka dan unlock → tersinkron sekali. |

`tests/phase5_manage.py` (slice 2), juga lewat UI sungguhan:

| Kasus | Hasil |
| --- | --- |
| Kategori | Tambah Makan dan Transport, ganti nama Transport → Ojek, arsip Makan. Form baru hanya menawarkan Tanpa kategori dan Ojek. |
| Edit | Pengeluaran berkategori Makan (sudah diarsip) diubah 25.000 → 30.000. Kategori tetap, `effectiveAt` tetap, versi 2. Perubahan dari "perangkat lain" lewat API, lalu simpan dari form → ditolak; "Muat versi terbaru" menampilkan nilai server. |
| Peminjam | Tambah lewat halaman Piutang. Setelah pinjaman tidak ada tombol arsip. Setelah dibayar penuh → Lunas → Arsipkan → Aktifkan kembali, dicek di server. |
| Hapus ditolak | Menghapus pinjaman yang sudah dibayar membuat piutang negatif pada prefiks → ditolak, tidak ada yang berubah. |
| Hapus dan pulihkan | Saldo dihitung ulang. Muncul di Baru dihapus. Pulihkan → waktu efektif dan nominal kembali, saldo kembali. |

`tests/phase5_slice3.py` (slice 3):

| Kasus | Hasil |
| --- | --- |
| Penyesuaian | Saldo awal Rp100.000. "abc" ditolak. Target 250.000 → ringkasan Rp250.000 dan selisih Rp150.000. Server belum berubah sebelum konfirmasi; sesudahnya saldo Rp250.000, snapshot ADJUSTMENT dengan delta 150.000. |
| Mundur tanggal | Pemasukan Rp5.000 di antara saldo awal dan penyesuaian → saldo tetap Rp250.000. Audit menampilkan "Rp150.000 → Rp145.000 (target tetap)" dan saldo Rp250.000 → Rp250.000. Detail penyesuaian: target dan selisih Rp145.000, tanpa Hapus. |
| Detail peminjam | Nama di Piutang → detail. "Catat pinjaman" → form dengan peminjam terpilih → simpan. Detail: sisa Rp20.000, satu baris riwayat (aktivitas lain tidak ikut), tanpa Arsipkan. |

Verifikasi slice 4:
- `cargo test`: 7 uji murni `report.rs` untuk perbandingan bulan berjalan, potongan 31 Maret, periode selesai, minggu, custom (termasuk hari ini), rentang tidak valid, batas hari WIB, dan pembulatan perbandingan.
- `phase2_financial.py` di MySQL, dengan tanggal historis tetap:
  - 16:59:59.999999Z dan 17:00Z jatuh di hari WIB berbeda;
  - pinjaman, pembayaran, pinjaman tanpa pengaruh saldo, dan pemasukan terhapus tidak masuk pemasukan;
  - kategori, seri bulan, pergerakan saldo, dan piutang per peminjam;
  - akun lain tidak bocor, dan 422 untuk lima query salah;
  - freeze → 423.
- Rekonsiliasi: penutup tahun berjalan = `/financial-state` dan piutang per peminjam = `outstanding`, untuk alice, bob, dan carol (setelah histori acak dan penulis konkuren).
- `tests/phase5_reports.py` lewat UI:
  - statistik Beranda berubah ikut periode, saldo tidak;
  - laporan harian dengan "turun 50,0%", "Baru", dan "turun 80,0%";
  - kategori, pergerakan saldo Rp1.000 → Rp1.050, piutang Tono 0/270/50/220, dan bulan 31 baris;
  - offline → pesan online-only tanpa angka (AC-20).
- Suite penuh 2/2 lulus.

Suite penuh (`--financial --browser --offline`) dijalankan 5 kali: 4 lulus. 1 gagal di langkah logout suite vault Fase 4 (halaman `/account` kosong), bukan di slice ini. Penyebabnya belum ditemukan. Diagnosa susulan: tiga run penuh lagi dengan log jaringan dan browser semuanya lulus, jadi kegagalannya tidak terulang. `see()` sekarang mencatat error jaringan/log, `readyState`, dan isi `#app`, sehingga kegagalan berikutnya memuat penyebabnya. Kegagalan lain dalam run verifikasi slice 2 ternyata bug sungguhan:
- Engine: `cycle(true)` dari simpan atau koreksi dibuang diam-diam bila tab yang sama sedang di tengah siklus, sehingga item baru menunggu tick 30 detik. Sekarang ditandai dan dijalankan tepat setelah siklus itu. Ada kasus baru di `phase4_sync_client.py` yang gagal tanpa perbaikan ini dan lulus dengannya.
- Riwayat: pindah ke Baru dihapus saat muatan pertama belum selesai menampilkan isi Riwayat biasa. Sekarang hanya permintaan terbaru yang mengisi daftar.

Setelah kedua perbaikan, suite penuh dijalankan 3 kali dan semuanya lulus.

Kegagalan Soft Lock tadi masih muncul sesekali, jadi penyebab yang diduga di atas ternyata keliru. Dengan diagnostik antrean dan isi server, penyebab sebenarnya terlihat: tes mengisi waktu koreksi "sekarang − 2 detik", dibulatkan ke detik. Kalau alur dari onboarding sampai koreksi lebih cepat dari itu, waktunya jatuh sebelum snapshot saldo awal dan transaksi terserap (delta saldo awal 777). Itu perilaku yang benar menurut BRD, tetapi salah sebagai uji koreksi. `past_now()` sekarang memilih detik lampau yang pasti setelah snapshot saldo awal. Sesudahnya suite UI lulus 8/8 dan suite penuh lulus 2/2.

Error MySQL 1644 di log server berasal dari trigger `fixture_audit_reject` milik uji atomisitas Fase 2. Itu disengaja; log server hanya dicetak ulang saat suite gagal. Temuan sampingan: `Storage.overrideQuotaForOrigin` tidak berlaku di Chrome ini, sehingga kasus kuota di suite vault selalu "NOT RUN". Uji itu belum membuktikan penolakan kuota. Fixture sekarang mengosongkan `auth_rate_limits` sebelum suite browser karena gabungan suite melebihi batas 12 registrasi per IP. Uji UI juga mengembalikan jam uji ke waktu nyata di awal.

Ditemukan dan diperbaiki saat uji: waktu default yang dibulatkan ke menit membuat transaksi sesaat setelah onboarding terserap snapshot saldo awal. Hal yang sama terjadi pada prefill koreksi.

Belum dijalankan:
- Audit aksesibilitas manual (keyboard dan screen reader). Uji ini hanya memeriksa label, `aria-invalid`/`aria-describedby`, dan `role=status`.
- Dark mode.
- Layar mobile sungguhan.
- Browser selain Chrome.
- Edit dan hapus saat vault terbuka tetap lewat jalur online langsung, tidak lewat antrean. Ini sesuai aturan online-only, tetapi belum diuji dengan vault terbuka.

Verifikasi slice 5:
- `cargo test`: 15 uji. Uji `report.rs` kini memakai zona akun, ditambah uji DST America/New_York: 8 Maret 2026 = 23 jam, 1 November 2026 = 25 jam, Maret punya 31 bucket, dan zona tidak valid ditolak.
- `phase2_financial.py` di MySQL:
  - ganti ke UTC membuat 17:00Z pindah ke 10 Maret;
  - `/activities`, saldo, dan versi state tetap sama;
  - zona akun lain tetap;
  - audit `TIMEZONE_CHANGED` sebelum/sesudah, dan nilai sama tidak menambah audit;
  - tiga nilai tidak valid → 422;
  - di America/New_York, 14 Maret 2021 berlangsung 05:00Z–04:00Z.
- `phase1_auth.py` kini mengharapkan tiga migrasi.
- `phase5_reports.py::settings_test` lewat UI sungguhan:
  - tema Gelap mengubah atribut, `localStorage`, dan warna latar; Ikuti sistem menghapus keduanya;
  - ganti zona ke UTC menampilkan peringatan dan server belum berubah sebelum konfirmasi;
  - setelah dikonfirmasi, Laporan 10 Maret menampilkan Rp500 dan Audit menampilkan "Zona waktu akun diubah";
  - muat langsung `/add/increase` dengan zona Asia/Tokyo: label dan isian waktu dalam jam Tokyo, dan simpan → `effectiveAt` server dalam 2 menit dari sekarang;
  - muat langsung `/reports` dengan zona America/New_York: tanggal default = hari ini di New York, dan laporan tampil.
- Ganti zona saat freeze → 423 dan saat recovery → 503 (`phase2_financial.py`).
- `cargo-audit` tidak terpasang, jadi audit dependensi Rust (termasuk jiff) tidak dijalankan. `npm audit`: 0 kerentanan.

Verifikasi slice 6:
- `phase2_financial.py` di MySQL:
  - akun baru mendapat tepat 10 kategori default aktif versi 1, dan audit seeding hanya ada satu;
  - filter kategori/`none`, jenis, pencarian dengan `%` dan `_` literal, tidak peka huruf besar, batas hari WIB, tanggal satu sisi yang terbuka, kursor di dalam filter;
  - akun lain tidak menemukan apa pun dengan id kategori milik bob;
  - lima query tidak valid → 422;
  - ubah profil peminjam naik ke versi 2, versi basi → 409, akun lain → 404.
- Uji paralel `phase3_sync.py` (empat tab) lulus lagi setelah kembali ke upsert eksklusif.
- `phase1_auth.py` kini mengharapkan empat migrasi.
- `phase5_slice6.py` lewat UI sungguhan:
  - form Pengeluaran menawarkan 10 kategori default, dan Audit menampilkan "Kategori default dibuat";
  - Riwayat: cari "50%", jenis + tanggal, hasil kosong, rentang terbalik → pesan, Hapus filter;
  - Ubah profil: nama kosong ditolak, simpan → server versi 2, perubahan dari perangkat lain → pesan versi dan data dimuat ulang;
  - pembayaran offline yang menjadi Konflik → "Keluar" menampilkan "1 transaksi … belum tersinkron", Batal tetap di halaman; pindah ke Perangkat menutup peringatan; "Cabut" sesi ini → peringatan "Cabut sesi ini" → Tetap keluar → `/login`; server tidak punya pembayaran itu; masuk lagi dan buka kunci → item Konflik masih ada untuk akun yang sama.
- Tidak diuji: migrasi 0004 terhadap database yang sudah berisi akun (tiap suite memakai database baru), dan pesan "sedang diperiksa hasilnya" saat logout.

Verifikasi slice 7:
- `phase2_financial.py` di MySQL:
  - audit terkait sebuah transaksi = dipulihkan, dihapus, diubah, dicatat (urut waktu aksi);
  - saldo awal ikut memuat transaksi mundur tanggal dan edit yang menghitung ulang selisihnya;
  - akun lain mendapat daftar kosong;
  - `resourceId` bukan UUID → 422.
- `phase1_browser.py` dan helper `login()`: verifikasi dan login mendarat di Beranda (`/onboarding` untuk akun baru).
- `phase5_slice7.py` lewat UI sungguhan:
  - di lebar 1280px tidak ada navigasi bawah;
  - di 375px: lima slot berurutan, duplikat header tersembunyi, tanpa scroll ke samping, target ≥ 44px;
  - "+ Tambah" membuka empat pilihan, Escape menutup dan fokus kembali ke tombol, pilihan Pengeluaran membuka form dan menutup menu;
  - transaksi tersimpan, lalu Detail menampilkan tepat satu entri audit terkait "Transaksi dicatat".
  - di Kategori (10 default), setiap kontrol yang difokus berada di atas bar; ketukan di luar menu + menutupnya.
- Tidak diuji: iOS Safari sungguhan (safe area dan keyboard), dan pembaca layar.
