# Fase 5 · Product UX (slice 1–2)

Slice ini mencakup SCR-05, SCR-06, SCR-09 (sebagian), SCR-10, SCR-11, SCR-19 dan SCR-21 (koreksi konflik). Rujukan: PR-BAL-01, PR-DASH-01/05/06/07/08, PR-TXN-01–08 (tanpa lampiran), PR-REC-01/03/04/09, PR-OFF-03–05, dan §6.4. **Fase 5 dan gate G4 belum selesai.**

Slice 2 menambah Riwayat, detail, edit/hapus/restore, Baru dihapus, Kategori, dan Piutang (daftar peminjam).

Belum termasuk:
- Pencarian dan filter Riwayat. Server belum menyediakan filter; daftar hanya dipaginasi per `sequence`.
- Halaman detail per peminjam beserta riwayat piutangnya, dan ubah profil peminjam (endpoint sudah ada)
- Kategori default. Backend tidak menyemai kategori, padahal PRD memintanya.
- Halaman Audit History (endpoint `/audit` sudah ada)
- Balance Adjustment
- Statistik periode, grafik, dan Reports
- Draft persisten, lampiran, Settings (zona waktu, tema), dan Audit History
- Bottom navigation mobile lima slot dan peringatan logout bila ada pending
- Login dan verifikasi masih mendarat di `/account`. Beranda ada di `/`.

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

**Usulan, dapat direview:** zona waktu akun belum ada di backend, jadi UI memakai Asia/Jakarta (UTC+7, default BRD) untuk input dan tampilan. Juga diusulkan: rute `/add/:kind` dan `/onboarding`, Beranda di `/`, serta teks label.

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

Suite penuh (`--financial --browser --offline`) dijalankan 5 kali: 4 lulus. 1 gagal di langkah logout suite vault Fase 4 (halaman `/account` kosong), bukan di slice ini. Penyebabnya belum ditemukan. Diagnosa susulan: tiga run penuh lagi dengan log jaringan dan browser semuanya lulus, jadi kegagalannya tidak terulang. `see()` sekarang mencatat error jaringan/log, `readyState`, dan isi `#app`, sehingga kegagalan berikutnya memuat penyebabnya. Kegagalan lain dalam run verifikasi slice 2 ternyata bug sungguhan:
- Engine: `cycle(true)` dari simpan atau koreksi dibuang diam-diam bila tab yang sama sedang di tengah siklus. Item baru menunggu tick 30 detik, lebih lama dari batas tunggu tes. Sekarang ditandai dan dijalankan tepat setelah siklus itu. Ada kasus baru di `phase4_sync_client.py` yang gagal tanpa perbaikan ini dan lulus dengannya.
- Riwayat: pindah ke Baru dihapus saat muatan pertama belum selesai menampilkan isi Riwayat biasa. Sekarang hanya permintaan terbaru yang mengisi daftar.

Setelah kedua perbaikan, suite penuh dijalankan 3 kali dan semuanya lulus.

Error MySQL 1644 di log server berasal dari trigger `fixture_audit_reject` milik uji atomisitas Fase 2. Itu disengaja; log server hanya dicetak ulang saat suite gagal. Temuan sampingan: `Storage.overrideQuotaForOrigin` tidak berlaku di Chrome ini, sehingga kasus kuota di suite vault selalu "NOT RUN". Uji itu belum membuktikan penolakan kuota. Fixture sekarang mengosongkan `auth_rate_limits` sebelum suite browser karena gabungan suite melebihi batas 12 registrasi per IP. Uji UI juga mengembalikan jam uji ke waktu nyata di awal.

Ditemukan dan diperbaiki saat uji: waktu default yang dibulatkan ke menit membuat transaksi sesaat setelah onboarding terserap snapshot saldo awal. Hal yang sama terjadi pada prefill koreksi.

Belum dijalankan:
- Audit aksesibilitas manual (keyboard dan screen reader). Uji ini hanya memeriksa label, `aria-invalid`/`aria-describedby`, dan `role=status`.
- Dark mode.
- Layar mobile sungguhan.
- Browser selain Chrome.
- Edit dan hapus saat vault terbuka tetap lewat jalur online langsung, tidak lewat antrean. Ini sesuai aturan online-only, tetapi belum diuji dengan vault terbuka.
