# Fase 5 · Product UX (slice 1–4)

Slice ini mencakup SCR-05, SCR-06, SCR-09 (sebagian), SCR-10, SCR-11, SCR-19 dan SCR-21 (koreksi konflik). Rujukan: PR-BAL-01, PR-DASH-01/05/06/07/08, PR-TXN-01–08 (tanpa lampiran), PR-REC-01/03/04/09, PR-OFF-03–05, dan §6.4. **Fase 5 dan gate G4 belum selesai.**

Slice 2 menambah Riwayat, detail, edit/hapus/restore, Baru dihapus, Kategori, dan Piutang (daftar peminjam).
Slice 4 menambah Laporan (SCR-20) dan statistik periode di Beranda (sebagian SCR-09). Rujukan: BR-RPT-01–08, BR-RPT-11, PR-DASH-02/03, PR-RPT-01–06, AC-20.
Slice 3 menambah Penyesuaian Saldo (SCR-16), Detail Peminjam (SCR-18), dan Audit (SCR-24). Rujukan: PR-BAL-02–04, PR-BAL-06, PR-REC-06/07, PR-HIS-08.

Belum termasuk:
- Pencarian dan filter Riwayat. Server belum menyediakan filter; daftar hanya dipaginasi per `sequence`.
- Ubah profil peminjam (endpoint sudah ada)
- "Audit terkait" di Detail transaksi. Server belum bisa memfilter audit per resource.
- Kategori default. Backend tidak menyemai kategori, padahal PRD memintanya.
- Ekspor PDF/Excel dan status job (Fase 6, worker)
- Daftar detail transaksi di halaman Laporan. Ringkasan, seri, dan tabel per kategori/peminjam sudah ada; daftar per transaksi menyusul bersama ekspor.
- Grafik di Beranda. Beranda hanya menampilkan ringkasan periode dengan tautan ke Laporan, tempat grafik berada.
- Perbandingan periode untuk Pergerakan Saldo dan Piutang. Yang ada baru perbandingan pemasukan, pengeluaran, dan selisih bersih.
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
| Periode | Batas dihitung di server dengan zona Asia/Jakarta. Minggu mulai Senin. Periode berjalan dipotong di "sekarang" dan dibandingkan dengan waktu berlalu yang sama sejak awal periode sebelumnya, dipotong di akhirnya (31 Maret ↔ Februari penuh). Periode selesai dibandingkan dengan periode penuh sebelumnya. Custom dibandingkan dengan rentang sama panjang tepat sebelumnya. Periode di masa depan, custom terbalik, atau lebih dari 5 tahun → 422. |
| Perbandingan | Integer saja, persepuluhan persen dibulatkan menjauhi nol, terhadap \|sebelumnya\|. Keduanya 0 → `ZERO` ("0%"). Sebelumnya 0 dan sekarang positif → `NEW` ("Baru"). Sebelumnya 0 dan sekarang negatif → `NO_BASELINE`, dijelaskan di UI. |
| Seri | Harian sampai 92 hari, bulanan untuk tahunan atau rentang lebih panjang. Pergerakan saldo memberi saldo akhir per bucket. |
| Freeze/recovery | Laporan ditolak dengan kode yang sama dengan mutasi (423/503). Angka dari ledger yang belum diverifikasi tidak ditampilkan seolah resmi. |
| UI `/reports` | Hanya online (`session` + `verified`) dan tidak pernah disimpan ke cache vault. Tiga tab, pilihan periode dan tanggal atau rentang, serta label rentang dan pembanding. Grafik berupa tabel dengan bar CSS: pemasukan polos, pengeluaran/negatif bergaris, jadi warna bukan satu-satunya pembeda, dan angka selalu tertulis. Gagal tanpa jawaban server → "Laporan hanya tersedia saat online", tanpa angka. |
| Beranda | Statistik periode (harian sampai tahunan) dari endpoint yang sama, hanya online. Saldo terkonfirmasi dan piutang di atasnya tidak bergantung pada periode. |

**Usulan, dapat direview:** zona waktu tetap Asia/Jakarta di server (`report::ZONE`) sampai ada pengaturan akun; minggu mulai Senin; batas custom 5 tahun; laporan ditolak saat freeze/recovery; cara baca persen terhadap baseline negatif.

`shortcut:` setiap laporan memuat dan me-replay seluruh ledger owner. Perlu total tersimpan atau replay ber-checkpoint bila ledger mencapai puluhan ribu baris.

Backend slice 3:
- `GET /activities` menerima `borrowerId` (UUID, dibatasi owner, bisa digabung dengan `before` dan `deleted`).
- Parameter query yang tidak valid di `/activities` dan `/audit` sekarang dijawab `422 VALIDATION_ERROR` dengan bentuk error API. Sebelumnya axum mengirim 400 berupa teks biasa.
- Diuji di `phase2_financial.py`: hanya aktivitas peminjam itu, peminjam lain kosong, akun lain kosong, kursor, dan tiga query yang salah.

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
