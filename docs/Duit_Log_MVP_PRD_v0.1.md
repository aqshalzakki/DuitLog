# Duit Log MVP — Product Requirements Document (PRD)

**Versi:** 0.1 — baseline untuk review produk  
**Tanggal:** 21 November 2026  
**Status:** Draft spesifikasi produk; **MVP scope frozen**, namun teks PRD belum memperoleh persetujuan formal  
**Bahasa:** Indonesia  
**Sumber acuan utama:** `Duit_Log_MVP_BRD_v0.1.md` (BRD v0.1, 21 November 2026)  
**Tahap lanjutan:** Technical Specification → AGENTS.md → feasibility gates dan implementasi bertahap

> **Tujuan PRD.** Menerjemahkan 96 kebutuhan bisnis dan 25 skenario penerimaan dalam BRD ke dalam pengalaman pengguna, perilaku halaman, alur produk, validasi, keadaan gagal, serta acceptance criteria yang dapat diuji. PRD **bukan** skema database, implementasi algoritma, rancangan API, atau kode. Keputusan teknis yang telah dikunci dihormati sebagai batasan; detail implementasinya diturunkan di Technical Specification.

---

## 1. Ringkasan dan status produk

Duit Log adalah aplikasi pencatatan keuangan pribadi berbasis web/PWA dengan akun terisolasi per pengguna, satu saldo utama, transaksi Increase/Deduct, piutang per peminjam, snapshot saldo aktual, laporan, lampiran bukti, dan audit. Ciri utama MVP adalah kemampuan **mencatat offline secara aman** setelah aktivasi sukarela, kemudian melakukan Partial Sync tanpa menggandakan pengaruh finansial.

**North-star pengalaman:** pengguna dapat mencatat uang yang masuk/keluar dengan cepat, membedakan angka *confirmed* dari estimasi lokal, mengoreksi sejarah keuangan tanpa merusak snapshot, dan memahami nasib setiap transaksi saat jaringan atau perangkat bermasalah.

**Status kesiapan:** siap menjadi baseline PRD; bukan pernyataan bahwa implementasi, desain visual final, kompatibilitas kriptografi, maupun disaster recovery telah diuji.

### 1.1 Sasaran produk

| ID | Sasaran produk | Bukti keberhasilan |
|---|---|---|
| GOAL-01 | Catat transaksi rutin tanpa friksi tinggi | Quick Add dan form ringkas bekerja di mobile/desktop |
| GOAL-02 | Saldo/piutang dapat dipercaya | Semua mutasi dapat ditelusuri; aturan snapshot dan kronologi lulus uji |
| GOAL-03 | Operasi offline transparan | Draft, pending, syncing, conflict, confirmed tidak tertukar |
| GOAL-04 | Pemulihan akses lokal yang nyata | Recovery Key dapat membuka data lokal yang masih ada |
| GOAL-05 | Laporan resmi konsisten | Pending dikecualikan; periode, zona waktu, dan ekspor konsisten |
| GOAL-06 | Aman digunakan oleh banyak akun | Tidak ada kebocoran lintas akun; sesi dapat dicabut dan anomali ditangani |

Target kuantitatif bisnis (DAU, retensi, jumlah transaksi/hari, SLA performa numerik) **belum disepakati**. Jangan menciptakan target tersebut sebagai persyaratan final.

### 1.2 Scope freeze dan batas produk

**Termasuk MVP:** autentikasi email; saldo dan adjustment snapshot; piutang; kategori; history, edit, soft delete, restore, audit; Dashboard; Reports/PDF/Excel; Offline Access opsional, encrypted draft/pending, Hybrid Lock, Recovery Key, Partial Sync; private attachments; operasional backup/PITR dan Financial Integrity Freeze.

**Tidak termasuk MVP:** multi-wallet, recurring/scheduled transactions, transaksi masa depan, write-off piutang, transfer uang sungguhan/payment gateway, bank feed, mata uang selain IDR, push notifications wajib, always-on background sync, dan admin dashboard operasional kompleks. **Tidak ada permanent delete transaksi finansial melalui UI MVP.**

### 1.3 Aktor dan prinsip otorisasi

| Aktor | Kebutuhan akses |
|---|---|
| Pengunjung | Register, login, reset password |
| Akun login belum verifikasi email | Verifikasi, resend, logout, pengelolaan sesi dasar; tidak dapat mengakses fitur finansial |
| Pengguna terverifikasi | Seluruh fitur keuangan **miliknya** dan Offline Access yang telah diaktifkan |
| Operator pemulihan berwenang | Verifikasi/perbaikan anomali dan pelepasan freeze melalui prosedur terbatas, dengan audit |
| Sistem | Validasi, sync, pembaruan ringkasan, audit, notifikasi status, pekerjaan asinkron |

UI harus menghindari kesan bahwa PIN lokal dapat menggantikan sesi autentikasi online. Semua akses server tetap harus diautentikasi dan diotorisasi.

## 2. Konvensi, status, dan sumber data

### 2.1 Klasifikasi data yang harus tampak pada UI

| Status | Makna produk | Pengaruh angka |
|---|---|---|
| **Draft** | Form belum dikirim/disimpan sebagai aktivitas | Tidak memengaruhi saldo maupun piutang, termasuk estimasi |
| **Pending** | Aktivitas sudah tersimpan aman di perangkat, belum diterima server | Boleh memengaruhi **estimasi lokal** yang valid, bukan angka resmi |
| **Syncing** | Aktivitas sedang dikirim/diperiksa | Form pending tidak dapat diubah sampai hasil jelas |
| **Checking outcome** | Request sudah dikirim, hasil commit belum diketahui akibat timeout/respons hilang | Jangan dianggap gagal atau dikirim dengan ID baru |
| **Synced / Confirmed** | Telah diterima server | Masuk ledger, saldo resmi, laporan, audit sesuai jenis |
| **Conflict** | Pelanggaran bisnis atau data tidak kompatibel dengan kondisi server terkini | Tetap lokal, butuh tindakan pengguna |
| **Blocked** | Menunggu aktivitas yang menjadi dependensi atau pembatasan sistem | Tidak boleh dikirim melewati dependensi |
| **Retry waiting** | Gangguan sementara; percobaan otomatis per siklus sudah dijeda/selesai | Tetap terlindungi lokal sampai retry berhasil |
| **Deleted** | Soft-deleted pada server | Tidak memengaruhi laporan/saldo; ada di Recently Deleted |
| **Evidence pending/failed** | Lampiran belum terunggah/tervalidasi | **Tidak** mengubah status confirmed transaksi finansial |

State lokal dan status evidence adalah **dua dimensi terpisah**. Satu transaksi bisa `Synced` sementara buktinya masih `Pending`.

### 2.2 Invarians presentasi

1. **Saldo terkonfirmasi** dan **saldo perkiraan** tidak disatukan dalam satu angka tanpa penjelasan. Angka confirmed berasal dari server atau cache yang jelas bertanda waktu.
2. Angka Dashboard pada kondisi offline harus menyatakan **terakhir diperbarui**; ringkasan periode yang tidak tersedia penuh tidak boleh disebut laporan resmi.
3. **Reports adalah online-only** dan **tidak memasukkan pending**. Export hanya mengambil transaksi confirmed sesuai filter.
4. Riwayat utama memuat seluruh aktivitas finansial, termasuk piutang dengan pengaruh saldo OFF; tampilkan label **Tidak memengaruhi saldo**.
5. Tanggal/waktu efektif berbeda dari waktu aksi audit. Perubahan zona waktu tidak mengubah instant sebenarnya.
6. Rupiah selalu **bilangan bulat**; input nominal pergerakan transaksi > Rp0, sementara saldo/target adjustment boleh negatif.
7. Seluruh langkah finansial yang ditolak tidak boleh menghasilkan partial commit; UI tidak menampilkan pesan sukses palsu.

### 2.3 Sumber kebenaran per konteks

| Yang ditampilkan | Sumber yang diutamakan |
|---|---|
| Saldo, total piutang, Reports resmi | Data server confirmed |
| Estimasi saat ada pending | Snapshot/saldo server terakhir + pending **yang dapat direkonstruksi secara benar** |
| History online | Transaksi server + pending lokal yang **dipisahkan statusnya** |
| History offline | Riwayat cache terbatas + pending lokal; tandai bagian yang tidak tersedia |
| Draft persistent | Encrypted IndexedDB, hanya setelah Offline Access aktif |
| Draft tanpa Offline Access | State selama sesi aplikasi aktif; tidak ada janji survive restart |
| Bukti offline | Berkas lokal terenkripsi sampai berhasil diunggah atau sengaja dibuang |

Jika cache tidak cukup untuk memperkirakan saldo secara benar karena snapshot/referensi kronologis tidak lengkap, tampilkan **Estimasi belum tersedia**, bukan jumlah pending mentah yang menyesatkan.

## 3. Information architecture dan navigasi

### 3.1 Desktop dan mobile

**Desktop:** sidebar untuk Dashboard, Transactions, Piutang, Reports, Sync Center, Settings, dan Audit History. Quick Add tersedia jelas di header/konten.

**Mobile:** bottom navigation lima slot — **Home · Transaksi · (+ Tambah) · Piutang · Laporan**. Tombol `+` di tengah membuka empat pilihan: Increase, Deduct, Tambah Piutang, Terima Pembayaran. Sync Center dibuka lewat indikator sync di header; Settings dan Audit History melalui profil/halaman detail.

**Gaya:** Light, Dark, System. PWA install bersifat pilihan, bukan prasyarat menggunakan aplikasi.

### 3.2 Inventaris layar produk

| ID | Layar/rute konseptual | Fungsi utama |
|---|---|---|
| SCR-01 | Register | Nama, email, password, persetujuan tindakan registrasi |
| SCR-02 | Login | Login email/password dan tautan reset |
| SCR-03 | Forgot / Reset Password | Memulai dan menyelesaikan reset via email |
| SCR-04 | Verification Pending | Verifikasi email, resend, logout, status |
| SCR-05 | Onboarding: Opening Balance | Isi saldo aktual atau lewati |
| SCR-06 | Onboarding: Offline Offer | Aktifkan sekarang atau lewati |
| SCR-07 | Offline Setup | PIN, authenticator/passphrase, Recovery Key + verifikasi penyimpanan |
| SCR-08 | Soft / Hard Lock / Recovery | PIN untuk Soft Lock; kredensial kuat atau Recovery Key untuk Hard Lock |
| SCR-09 | Dashboard | Saldo confirmed, estimasi, piutang, statistik/grafik, Quick Add |
| SCR-10 | Quick Add Picker | Empat aktivitas utama |
| SCR-11 | Transaction Form | Increase/Deduct, lampiran, detail, autosave |
| SCR-12 | Transactions List | History campuran confirmed/pending, search/filter/sort |
| SCR-13 | Transaction Detail | Semua informasi, bukti, edit/delete, audit terkait |
| SCR-14 | Drafts | Draft tersimpan, lanjutkan, hapus |
| SCR-15 | Recently Deleted | Detail soft delete dan restore |
| SCR-16 | Balance Adjustment | Masukkan saldo aktual saat ini **online-only** |
| SCR-17 | Borrowers List | Peminjam, status Paid/Unpaid, sisa piutang, arsip |
| SCR-18 | Borrower Detail | Riwayat pinjaman/pembayaran, reaktivasi, aksi piutang |
| SCR-19 | Receivable Form | Pinjaman/pembayaran, toggle pengaruh saldo |
| SCR-20 | Reports | Tiga keluarga laporan, periode/filter, grafik dan ekspor online |
| SCR-21 | Sync Center | Pending/syncing/conflict/blocked/retry, dependensi dan status evidence |
| SCR-22 | Categories | Kategori default/personal, archive/reactivate |
| SCR-23 | Settings & Devices | Profil, timezone, tema, PIN/security, sesi perangkat, penghapusan offline |
| SCR-24 | Audit History | Timeline aksi dan rekalkulasi, detail sebelum/sesudah |
| SCR-25 | Export Status | Job diproses, siap unduh, gagal/coba lagi |
| SCR-26 | Offline / Error / Integrity State | Reports offline, expiry 7 hari, freeze, maintenance dan recovery |

Rute URL, nama komponen, dan path API final ditentukan pada Technical Specification; inventaris di atas adalah kontrak produk, bukan skema router.

### 3.3 Navigasi, guard, dan pemulihan rute

- Pengguna yang belum login diarahkan ke autentikasi; pengguna belum verifikasi email dibatasi pada Verification Pending dan alur sesi dasar.
- Ketika membuka halaman berproteksi dalam kondisi terkunci, tampilkan Soft/Hard Unlock sesuai keadaan kunci. Setelah berhasil, **kembali ke halaman yang diminta semula** bila masih berwenang.
- Jika halaman Reports dibuka offline, tampilkan penjelasan online-only tanpa mengubah laporan lama menjadi angka resmi baru.
- Jika offline belum aktif atau telah melewati tujuh hari tanpa validasi, blokir operasi offline dan jelaskan tindakan yang diperlukan; pending tidak dihapus.
- Jangan menyimpan detail finansial sensitif pada URL, query string, notifikasi lock screen, atau nama tab yang dapat dilihat ketika terkunci.
- Perpindahan akun/logout mengunci dan mengisolasi data akun sebelumnya; tidak ada sync silang pengguna.
- Form belum terkirim harus disimpan sesuai mode draft sebelum perpindahan; bila penyimpanan gagal, jangan diam-diam membuang perubahan.

## 4. Onboarding dan autentikasi

### 4.1 Journey registrasi hingga Dashboard

1. Pengunjung mengisi nama, email, password. Validasi field dan respons tidak mengungkap data sensitif.
2. Setelah registrasi, arahkan ke layar verifikasi. Pengguna boleh login, resend verifikasi, atau logout, tetapi tidak boleh membuka data keuangan sebelum verifikasi.
3. Setelah terverifikasi, tampilkan **Opening Balance**: masukkan nilai saldo sebenarnya (termasuk Rp0 dan negatif) **atau** pilih *Lewati*.
4. Jika diisi, nilai menjadi snapshot onboarding pada saat validasi server. Jika dilewati, mulai Rp0 **tanpa snapshot**.
5. Tawarkan Offline Access secara **opsional**. Jika dilewati, pengguna langsung ke Dashboard online. Aktivasi dapat dilakukan nanti dari Settings.
6. Jika Offline Access dipilih, setup keamanan wajib tuntas: PIN 6 digit, mekanisme pembukaan DEK kuat (authenticator kompatibel atau passphrase kuat), dan Recovery Key disimpan serta dikonfirmasi.
7. Instalasi PWA adalah anjuran opsional, bukan langkah yang memblokir onboarding.

### 4.2 Kebutuhan produk autentikasi

| ID | Perilaku yang harus ada | Referensi BRD |
|---|---|---|
| PR-AUTH-01 | Form register/login memberi validasi per-field, status loading, error yang tidak membocorkan akun pihak lain. | BR-AUTH-01, 04 |
| PR-AUTH-02 | Halaman belum verifikasi hanya mengizinkan verifikasi, resend, logout, dan tindakan sesi dasar. | BR-AUTH-02, 03 |
| PR-AUTH-03 | Forgot/reset password via email memiliki status berhasil/gagal yang aman. | BR-AUTH-03 |
| PR-AUTH-04 | Sesi dapat dilihat dan dicabut per perangkat; terdapat logout perangkat ini/semua perangkat. | BR-AUTH-05, 07 |
| PR-AUTH-05 | Setelah 30 hari **absolut** sejak login, autentikasi ulang wajib; refresh tidak memperpanjang tenggat. | BR-AUTH-06 |
| PR-AUTH-06 | Jika sesi online berakhir, hentikan API/sync, tetapi jangan otomatis menghapus draft/pending terenkripsi. | BR-AUTH-06, 07; BR-OFF-16 |
| PR-AUTH-07 | PIN tidak pernah dipresentasikan sebagai metode login server. | BR-AUTH-08 |
| PR-AUTH-08 | Sesi akun lain tidak boleh membuka cache, draft, pending, atau lampiran akun sebelumnya. | BR-AUTH-04; BR-OFF-16 |

### 4.3 Acceptance utama autentikasi

- **Given** akun belum terverifikasi, **when** membuka Dashboard atau endpoint keuangan, **then** akses ditolak secara konsisten meskipun URL diubah manual.
- **Given** sesi 30 hari selesai, **when** mengirim aktivitas, **then** re-auth diperlukan; data pending lokal tetap utuh.
- **Given** sesi HP dicabut via laptop ketika HP offline, **when** HP terhubung, **then** akses/sync berikutnya ditolak; UI **tidak** mengklaim remote wipe berhasil.
- **Given** register/login error, **then** tidak ada password atau token yang muncul pada pesan/log antarmuka.

## 5. Dashboard dan angka keuangan

### 5.1 Struktur Dashboard

Tampilan pertama menempatkan **Saldo Utama Terkonfirmasi** di posisi utama, **Total Piutang Saat Ini**, ringkasan Income, Expense, net income/expense menurut filter, tiga grafik sesuai cakupan, aktivitas terbaru, serta Quick Add dan status sinkronisasi.

**Periode default usulan PRD:** *Bulan ini* untuk statistik/grafik. Ini merupakan **default tampilan**, bukan perubahan aturan bisnis; pengguna dapat mengganti harian, mingguan, bulanan, tahunan, dan custom range. Hari/periode menurut zona waktu akun saat ini.

**Saldo utama terkini dan total piutang terkini tidak berubah ketika pengguna mengganti filter periode.** Hanya angka statistik periode dan grafik yang terfilter.

### 5.2 Kebutuhan Dashboard

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-DASH-01 | Tampilkan saldo confirmed dan total piutang terkini terpisah dari statistik periode. | BR-RPT-01 |
| PR-DASH-02 | Ringkasan income/expense mengecualikan piutang dan adjustment; tampilkan net. | BR-RPT-03 |
| PR-DASH-03 | Sediakan filter periode harian/mingguan/bulanan/tahunan/custom dengan rentang aktual terlihat. | BR-RPT-02, 11 |
| PR-DASH-04 | Tampilkan grafik income vs expense, expense by category, tren saldo, plus alternatif tekstual aksesibel. | BR-RPT-05; BR-UX-07 |
| PR-DASH-05 | Saat offline, tampilkan cache confirmed dengan waktu pembaruan dan estimasi lokal **berlabel**. | BR-OFF-18; BR-RPT-08 |
| PR-DASH-06 | Jika cache tidak lengkap untuk estimasi, tampilkan “Estimasi belum tersedia”; jangan gunakan angka yang keliru. | BR-OFF-18 |
| PR-DASH-07 | Tampilkan indikator sinkronisasi yang membuka Sync Center; konflik tetap tampak meskipun toast ditutup. | BR-UX-04 |
| PR-DASH-08 | Empty state berisi arahan membuat transaksi pertama/peminjam pertama, bukan grafik rusak. | BR-UX-08 |

### 5.3 Aturan penampilan nominal

- Rupiah menggunakan pemisah ribuan lokal (`Rp1.250.000`); nilai negatif menunjukkan `−Rp...`, dibantu label jenis aktivitas.
- Pengeluaran tampil sebagai Deduct, pemasukan Increase, tetapi warna **tidak** menjadi satu-satunya penanda.
- Pending pada history dapat disertai estimasi; jangan masukkan ke ringkasan resmi.
- Saldo negatif legal dan tidak diubah menjadi Rp0 atau dianggap kegagalan secara otomatis.

## 6. Quick Add dan formulir transaksi

### 6.1 Alur Quick Add

Di mobile, sentuh `+` pada bottom navigation → picker empat aktivitas → halaman penuh untuk formulir terpilih → simpan → status confirmed/pending/checking outcome. Desktop boleh menggunakan modal/panel yang cukup luas; fungsi dan validasinya harus identik.

### 6.2 Field dan validasi Increase/Deduct

| Field | Wajib? | Perilaku |
|---|---|---|
| Jenis | Ya | Increase atau Deduct, dipilih dari Quick Add |
| Nominal | Ya | IDR integer positif; `0`, negatif untuk jumlah transaksi, desimal, dan nonangka ditolak |
| Judul | Tidak | Boleh kosong; daftar menampilkan fallback jenis aktivitas jika kosong |
| Kategori | Tidak | Pilih kategori aktif atau Tanpa Kategori; kategori arsip tidak tersedia untuk transaksi baru |
| Deskripsi | Tidak | Teks opsional; jangan dijadikan identitas transaksi |
| Tanggal efektif | Ya | Default tanggal hari ini dalam zona waktu akun |
| Waktu efektif | Ya secara sistem | Default waktu sekarang, bisa diedit oleh pengguna; form tidak boleh menyimpan waktu efektif yang lebih maju dari waktu validasi server |
| Bukti | Tidak | Maksimal 1 file; JPG/PNG/WebP/PDF, maksimal 10 MB |

Tanggal waktu yang dipilih pengguna dikonversi menjadi **instant absolut** untuk kronologi. Ketika offline, jam perangkat hanya dipakai untuk validasi awal; server melakukan validasi akhir dan tidak mengubah timestamp diam-diam.

### 6.3 Kebutuhan form

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-TXN-01 | Quick Add mobile mempunyai empat aksi yang telah ditetapkan. | BR-UX-01 |
| PR-TXN-02 | Form mobile layar penuh, nominal mudah difokuskan, rincian opsional dapat dibuka/tutup, tombol Simpan mudah dijangkau. | BR-UX-02 |
| PR-TXN-03 | Input nominal menolak nilai tidak valid dengan pesan per-field tanpa menghilangkan input lain. | BR-FIN-01, 02 |
| PR-TXN-04 | Waktu efektif boleh diedit sampai sekarang atau masa lampau; server menolak masa depan termasuk jam masa depan pada tanggal yang sama. | BR-FIN-02, 03 |
| PR-TXN-05 | Simpan online memberi status confirmed hanya setelah hasil commit diketahui; timeout menghasilkan checking outcome. | BR-FIN-13; BR-OFF-13 |
| PR-TXN-06 | Simpan offline hanya sukses setelah transaksi **dan referensi/lampiran lokal yang dibutuhkan** benar-benar tersimpan; jika gagal, tampilkan kegagalan penyimpanan. | BR-OFF-08, 19; BR-FILE-05 |
| PR-TXN-07 | Double-submit dicegah; satu tindakan pengguna tidak menjadi dua transaksi. | BR-OFF-13 |
| PR-TXN-08 | Setelah berhasil, pengguna dapat kembali ke history/detail atau membuat aktivitas berikutnya tanpa kehilangan status sync. | BR-HIS-05; BR-UX-08 |

### 6.4 Feedback setelah Simpan

| Kondisi | Judul/status yang disarankan | Penjelasan |
|---|---|---|
| Commit confirmed | “Transaksi berhasil dicatat” | Saldo resmi diperbarui/tersedia dari server |
| Offline write sukses | “Transaksi tersimpan offline” | Masih pending; belum masuk laporan resmi |
| Respons tak sampai | “Memeriksa hasil transaksi” | Jangan membuat transaksi baru atau menyebut gagal |
| Validasi finansial gagal | “Transaksi belum dapat disimpan” | Alasan dan langkah koreksi jelas |
| Local storage gagal | “Tidak dapat menyimpan di perangkat” | Tidak ada klaim pending tersimpan |

## 7. Opening Balance dan Balance Adjustment

### 7.1 Aturan perilaku

- Opening Balance saat onboarding **opsional**. Jika pengguna memasukkan nilai apa pun termasuk Rp0, itu adalah **snapshot otoritatif pada waktu onboarding**; transaksi backdated sebelum titik ini tidak menghitung dua kali saldo kini.
- Jika pengguna memilih *Lewati*, saldo mulai dari Rp0 **tanpa snapshot**, sehingga transaksi bertanggal lampau yang valid tetap dapat mengubah saldo kini.
- Balance Adjustment **online-only**, meminta **target saldo aktual saat ini** yang dikonfirmasi pengguna, bukan “delta koreksi”. Timestamp snapshot berasal dari server pada saat konfirmasi, **tidak dapat di-backdate**.
- Target saldo adjustment boleh negatif. Preview sebelum konfirmasi menunjukkan saldo confirmed sebelum, target yang dimasukkan, dan delta yang dihitung pada kondisi server saat itu; hasil final dapat berubah jika ada transaksi bersamaan, sehingga backend memutuskan final secara atomik.
- Mengedit/menghapus/restore aktivitas sebelum snapshot dapat mengubah **delta adjustment**, tetapi **bukan target** snapshot. UI harus menjelaskan mengapa saldo akhir bisa tidak berubah.

### 7.2 Kebutuhan adjustment

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-BAL-01 | Onboarding membedakan “Konfirmasi Rp0” dari “Lewati saldo awal”. | BR-FIN-04, 05 |
| PR-BAL-02 | Form adjustment hanya dapat diakses online dari area transaksi/saldo khusus, bukan Quick Add rutin. | BR-FIN-06 |
| PR-BAL-03 | Pengguna melihat target saldo, bukan hanya delta; sebelum simpan ada ringkasan konfirmasi. | BR-FIN-06 |
| PR-BAL-04 | Perubahan historis yang terpengaruh snapshot menampilkan penjelasan rekalkulasi dan tetap mempertahankan target snapshot. | BR-FIN-07, 08 |
| PR-BAL-05 | Adjustment tidak muncul dalam income/expense, tetapi muncul dalam history dan Balance Movement. | BR-FIN-09; BR-RPT-03, 04 |
| PR-BAL-06 | Operasi yang gagal validasi versi/concurrency tidak menampilkan target seolah-olah sudah diterapkan. | BR-FIN-11, 13 |

### 7.3 Contoh penerimaan

**Skenario A:** onboarding pukul 12.00 pengguna menegaskan Rp2.000.000. Malam hari menambahkan Deduct Rp100.000 bertanggal sebelum pukul 12.00; target snapshot tetap Rp2.000.000 dan saldo sekarang tidak dikurangi untuk kedua kali, kecuali ada mutasi setelah snapshot.

**Skenario B:** pengguna melewati opening balance, lalu menambahkan Increase Rp500.000 bertanggal kemarin; saldo terkini naik Rp500.000 karena tidak ada snapshot onboarding.

## 8. Piutang dan profil peminjam

### 8.1 Borrower List dan detail

Daftar peminjam menampilkan nama, sisa piutang, status **Paid** (Rp0) atau **Unpaid** (> Rp0), status arsip, serta penanda apakah data confirmed atau cache. Nama tidak unik: dua profil “Andi” harus tetap bisa dibedakan melalui detail masing-masing, tanpa menganggapnya orang yang sama.

Detail peminjam menampilkan informasi opsional (telepon, catatan), saldo piutang, history pinjaman dan pembayaran, serta Quick Action pinjam/bayar. Peminjam yang telah lunas **tidak** otomatis diarsipkan.

### 8.2 Form aktivitas piutang

| Field/opsi | Perilaku |
|---|---|
| Peminjam | Wajib; dapat memilih profil aktif atau membuat profil baru secara offline bila Offline Access aktif |
| Nominal | Integer IDR > Rp0 |
| Jenis | Pinjaman (+ piutang) atau pembayaran (− piutang) |
| Pengaruh saldo utama | **ON secara default per aktivitas**; pinjaman mengurangi saldo, pembayaran menambah saldo |
| Pengaruh saldo OFF | Piutang tetap berubah; saldo utama tidak berubah; beri label “Tidak memengaruhi saldo” |
| Tanggal/waktu | Default sekarang, boleh historis; masa depan ditolak setelah validasi server |
| Judul/deskripsi/bukti | Mengikuti kemampuan formulir transaksi yang relevan |

Pembayaran tidak boleh menyebabkan sisa piutang negatif pada **titik mana pun** dalam urutan kronologis. Ini berlaku juga pada backdate, koreksi, delete, restore, dan sync.

### 8.3 Kebutuhan Piutang

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-REC-01 | Dapat membuat profil peminjam dengan nama wajib, telepon/catatan opsional; nama duplikat tidak digabung. | BR-REC-01, 02 |
| PR-REC-02 | Semua pinjaman dan pembayaran milik satu profil terakumulasi dalam satu akun piutang. | BR-REC-03 |
| PR-REC-03 | Toggle pengaruh saldo default ON untuk kedua jenis; OFF tetap memengaruhi piutang saja. | BR-REC-04 |
| PR-REC-04 | Form pembayaran menjelaskan sisa piutang yang diketahui; keputusan final tetap memvalidasi kronologi server. | BR-REC-05, 06 |
| PR-REC-05 | Jika kronologi piutang negatif, tolak seluruh operasi dan beri alasan/tanggal terdampak jika aman diungkapkan. | BR-REC-05, 06, 10 |
| PR-REC-06 | Status Paid/Unpaid dihitung otomatis; profil tidak otomatis diarsipkan ketika lunas. | BR-REC-07, 08 |
| PR-REC-07 | Arsip peminjam hanya ketika sisa piutang Rp0; reaktivasi manual untuk aktivitas baru. | BR-REC-08, 09 |
| PR-REC-08 | Koreksi historis yang menyebabkan profil arsip kembali memiliki sisa positif otomatis mengaktifkannya kembali dan dicatat audit. | BR-REC-09 |
| PR-REC-09 | Offline mendukung pembuatan peminjam lalu aktivitas dependent, dengan status Pending/Blocked yang jelas. | BR-OFF-08, 12 |
| PR-REC-10 | Tidak ada menu write-off/pengampunan piutang di MVP. | BR-REC-11 |

### 8.4 Tampilan error piutang

- Pembayaran melebihi piutang kronologis: “Pembayaran menyebabkan sisa piutang tidak valid pada riwayat [tanggal]. Periksa nominal atau tanggal.”
- Peminjam arsip: “Aktifkan kembali peminjam untuk membuat transaksi baru.”
- Peminjam belum tersinkron: “Menunggu profil peminjam tersinkron terlebih dahulu.”
- Piutang cache lama: tampilkan “Data terakhir diperbarui ...; saldo resmi mungkin sudah berubah.”

## 9. Transaction History, detail, Recently Deleted, dan audit

### 9.1 History utama

Default urut **effective time terbaru**; saat timestamp identik, gunakan urutan finansial sekunder immutable dari server. Transaksi lokal pending yang belum mempunyai sequence server diberi label pending dan posisi sementara yang tidak diklaim sebagai urutan final. Setelah sync, daftar bisa tersusun kembali sesuai kronologi server.

Pencarian dan filter: judul/deskripsi, peminjam bila relevan, jenis aktivitas, kategori, rentang tanggal, rentang nominal, dan status yang tersedia (confirmed/pending/conflict). History tidak boleh menyembunyikan mutasi piutang dengan pengaruh saldo OFF. Adjustment memiliki jenis khusus, bukan Increase/Expense biasa.

Saat offline, daftar dapat mencampurkan data confirmed yang **di-cache** dan pending. Tampilkan batas cakupan cache (“Sebagian riwayat tidak tersedia offline”) daripada *empty state* palsu.

### 9.2 Detail, edit, delete, dan restore

- Detail memuat nominal, jenis, judul, kategori (termasuk kategori arsip pada catatan historis), deskripsi, tanggal/waktu efektif, peminjam jika ada, toggle pengaruh saldo, status server/sync, status evidence, serta tautan riwayat audit.
- **Confirmed:** edit/delete/restore hanya saat online. Form edit menggunakan nilai server terkini dan memeriksa versi saat menyimpan. Jika versi sudah berubah, tampilkan konflik serta opsi memuat ulang; jangan menimpa diam-diam.
- **Pending:** dapat diedit/dibatalkan lokal sebelum pengiriman. Saat `Syncing` atau `Checking outcome`, aksi edit/cancel dikunci sampai status jelas.
- **Delete confirmed:** soft delete dengan dialog konfirmasi, dampak ke saldo/piutang/snapshot dijelaskan, alasan penghapusan opsional. Hasil validasi dapat ditolak apabila kronologi piutang menjadi tidak valid.
- **Recently Deleted:** daftar tanpa masa kedaluwarsa otomatis; pengguna dapat membuka detail dan memulihkan transaksi selama semua aturan finansial masih terpenuhi. Tidak ada `Delete permanently` untuk transaksi finansial pada MVP.
- **Restore:** memulihkan waktu efektif aslinya; dapat merekalkulasi snapshot terdampak. Kategori yang telah diarsipkan tetap menempel pada transaksi historis yang dipulihkan, tanpa mengaktifkannya kembali.
- **Audit History:** timeline berdasarkan waktu aksi server, aktor, before/after, serta rincian setiap adjustment delta yang berubah dengan kaitan ke operasi pemicu.

### 9.3 Kebutuhan riwayat

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-HIS-01 | History memuat semua jenis aktivitas, termasuk no-balance-impact dan pending berlabel. | BR-HIS-05 |
| PR-HIS-02 | Filter, pencarian, dan tanggal efektif dipakai secara konsisten; audit memakai waktu aksi. | BR-HIS-06, 11 |
| PR-HIS-03 | Detail menampilkan field lengkap, bukti/status, dan relasi audit tanpa membocorkan data akun lain. | BR-HIS-11; BR-FILE-03 |
| PR-HIS-04 | Edit confirmed online-only; versi lama ditolak dengan opsi reload. | BR-HIS-07; BR-FIN-11 |
| PR-HIS-05 | Delete confirmed adalah soft delete, alasan opsional, dan koreksi finansial atomik. | BR-HIS-07, 09; BR-FIN-13 |
| PR-HIS-06 | Recently Deleted tidak kedaluwarsa otomatis; restore tunduk validasi bisnis; no permanent delete. | BR-HIS-08 |
| PR-HIS-07 | Restore tidak mengaktifkan kategori arsip secara otomatis; tampilan historis tetap tepat. | BR-HIS-02, 08 |
| PR-HIS-08 | Audit append-only di level aplikasi menampilkan before/after dan rincian rekalkulasi otomatis yang berelasi. | BR-HIS-10 |
| PR-HIS-09 | Pending dalam state Syncing/Unknown dikunci dari modifikasi sementara. | BR-OFF-09, 13 |

### 9.4 Kategori transaksi

Kategori default disediakan per akun, dan kategori custom dapat dibuat, diedit, diarsipkan, serta diaktifkan kembali. Kategori opsional; **Tanpa Kategori** adalah label laporan, bukan pemaksaan pilihan kategori.

- Kategori arsip tidak tersedia saat membuat aktivitas baru, tetapi masih terlihat pada transaksi lama dan laporan historis.
- Saat mengedit transaksi lama, kategori arsip yang sudah melekat boleh **dipertahankan** tanpa perubahan; jika pengguna menggantinya, pilih kategori aktif atau kosongkan.
- Jika kategori diarsipkan pada perangkat lain ketika suatu pending baru telah dibuat, proses sync menghasilkan Conflict. Pengguna boleh memilih kategori aktif atau Tanpa Kategori dan mencoba kembali; tidak ada penggantian otomatis.

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-CAT-01 | Tampilkan daftar kategori default/personal yang aktif dan arsip, serta tindakan kelola. | BR-HIS-01 |
| PR-CAT-02 | Form transaksi baru tidak menawarkan kategori arsip; histori tetap mempertahankannya. | BR-HIS-02 |
| PR-CAT-03 | Kategori kosong dihitung dan dilabeli Tanpa Kategori. | BR-HIS-03 |
| PR-CAT-04 | Konflik kategori arsip saat sync tidak otomatis mengubah pilihan pengguna. | BR-HIS-04 |
| PR-CAT-05 | Kategori yang diarsipkan dapat diaktifkan lagi; transaksi lama tidak ditulis ulang. | BR-HIS-01, 02 |

## 10. Reports dan ekspor

### 10.1 Akses dan struktur

Reports **online-only**. Tiga keluarga laporan yang diperlukan:

1. **Income/Expense:** pemasukan dan pengeluaran biasa menurut periode, kategori, filter, beserta total/net. Tidak memasukkan piutang maupun adjustment.
2. **Balance Movement:** saldo pembuka/penutup historis dan semua mutasi yang benar-benar memengaruhi saldo, termasuk pinjaman/pembayaran dengan toggle ON serta delta adjustment yang dihitung ulang. Aktivitas no-balance-impact bisa ditampilkan di history umum tetapi tidak dijumlahkan sebagai mutasi saldo.
3. **Receivables:** saldo piutang pembuka/penutup, pinjaman baru dan pembayaran per periode/per peminjam; tidak diperlakukan sebagai income/expense.

Filter tersedia untuk harian, mingguan, bulanan, tahunan, dan custom date range. Rentang aktual ditampilkan secara eksplisit berdasarkan **zona waktu akun saat ini**. Ringkasan current balance/current receivables pada Dashboard tidak tunduk pada filter periode ini.

### 10.2 Perbandingan periode

- Periode **sedang berjalan** (hari/minggu/bulan/tahun) dibandingkan dengan durasi elapsed yang setara pada periode sebelumnya, bukan dengan keseluruhan periode sebelumnya.
- Periode historis yang sudah selesai dibandingkan periode penuh sebelumnya.
- Custom date range dibandingkan dengan rentang tepat sebelumnya yang **sama panjang**.
- Label kedua rentang tanggal harus terlihat sehingga tidak terjadi salah interpretasi.
- Jika angka pembanding sebelumnya 0 sedangkan sekarang > 0, tampilkan **Baru**, bukan persen tak terhingga; jika keduanya 0, tampilkan **0%**.
- Karena jumlah net dapat negatif, rumus penyajian persen untuk nilai signed dan basis negatif perlu dinyatakan eksplisit dalam Technical Specification. Jangan memberi angka misleading tanpa penjelasan.

### 10.3 Ekspor dan status job

- Ekspor **PDF dan Excel**, tersedia untuk masing-masing keluarga Reports dan filter yang dipilih.
- Konten ekspor mencakup ringkasan **dan seluruh detail transaksi yang cocok** (bukan hanya halaman pagination yang sedang ditampilkan), tanpa binary bukti.
- File memuat rentang periode, zona waktu yang dipakai, waktu generasi, jenis laporan, dan indikasi confirmed-only.
- Jika perlu proses asinkron, tampilkan status job: *Diproses*, *Siap diunduh*, *Gagal — Coba lagi*. File hasil ekspor privat dan dapat diunduh hanya oleh pemiliknya.
- Jika financial integrity sedang ditinjau atau database baru selesai restore, antarmuka harus menandai status data; ekspor hanya bisa diizinkan sesuai kebijakan keamanan yang telah ditetapkan.

### 10.4 Kebutuhan Reports

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-RPT-01 | Reports hanya online; ketika offline menjelaskan kebutuhan koneksi, tidak merakit laporan resmi dari cache parsial. | BR-RPT-08 |
| PR-RPT-02 | Tiga keluarga laporan lengkap tersedia dengan definisi perhitungan berbeda. | BR-RPT-03, 04 |
| PR-RPT-03 | Semua filter periode dan custom range menggunakan zona waktu akun saat ini. | BR-RPT-02, 11 |
| PR-RPT-04 | Perbandingan periode berjalan/historis/custom mengikuti aturan durasi setara dan pelabelan rentang. | BR-RPT-06, 07 |
| PR-RPT-05 | Kondisi baseline nol ditampilkan sebagai Baru/0% sesuai kesepakatan. | BR-RPT-07 |
| PR-RPT-06 | Grafik dan ringkasan menyediakan alternatif tekstual aksesibel. | BR-RPT-05; BR-UX-07 |
| PR-RPT-07 | PDF dan Excel mencakup summary serta semua transaksi confirmed yang cocok dengan filter, bukan page yang terlihat saja. | BR-RPT-09 |
| PR-RPT-08 | Ekspor memuat waktu generasi, rentang dan zona waktu; tidak menyertakan file bukti. | BR-RPT-10, 11 |
| PR-RPT-09 | File ekspor dan status job hanya dapat dilihat pemilik; tersedia error/retry terarah. | BR-RPT-10; BR-OPS-07 |
| PR-RPT-10 | Jika timezone akun berubah, tanggal grup historis dapat berubah; tampilkan peringatan sebelum menyimpan pengaturan. | BR-RPT-11 |

### 10.5 Empty, loading, partial, dan fail states

- **Tidak ada data sungguhan:** tampilkan angka 0 dan keterangan tidak ada transaksi untuk filter.
- **Sedang memuat:** skeleton/indikator loading tanpa mengganti nilai confirmed dengan Rp0.
- **Request error:** keterangan server tidak dapat dijangkau dan tombol coba lagi.
- **Offline:** informasi Reports online-only, bukan halaman error generik.
- **Reconciliation concern:** peringatan status integritas; tidak menyajikan laporan sebagai final tanpa kualifikasi.

## 11. Offline Access dan keamanan lokal

### 11.1 Aktivasi Offline Access

Offline Access **opsional** pada onboarding dan dapat diaktifkan lewat Settings setelah login online pertama dan verifikasi email berhasil. Alur aktivasi wajib meminta:

1. PIN App Lock **6 digit**, disiapkan dan dikonfirmasi.
2. Perlindungan kunci enkripsi: authenticator perangkat melalui kemampuan yang **benar-benar kompatibel**, atau **passphrase kuat** sebagai fallback yang tersedia sejak setup. Keberadaan biometrik/passkey tidak otomatis berarti WebAuthn PRF dapat dipakai.
3. Recovery Key acak yang benar-benar mampu memulihkan akses ke data yang masih tersimpan; tampilkan satu kali pada aktivasi dengan instruksi penyimpanan aman dan konfirmasi telah disimpan.
4. Konfirmasi kemampuan offline aktif. Bila salah satu langkah gagal, jangan menandai setup sebagai aktif sebagian.

Recovery Key tidak memulihkan data yang dihapus dari browser dan bukan backup server. Jangan memasukkan Recovery Key ke email, URL, console log, atau notifikasi.

### 11.2 Hybrid Lock dan validasi online

| Kondisi | Perilaku UI |
|---|---|
| Tidak aktif selama 5 menit | Soft Lock: layar PIN hanya bila DEK masih ada dalam sesi aktif |
| DEK sudah dibersihkan dari memori | Hard Lock: authenticator/passphrase atau Recovery Key |
| Browser/app restart atau ditutup | Hard Lock; tidak bergantung pada event close yang tidak andal |
| Logout/beralih akun | Hard Lock dan isolasi akun, pending terlindungi |
| Lebih dari 7 hari tanpa validasi server | Aktivitas offline diblokir hingga validasi online, **pending tetap ada** |
| Login server berakhir 30 hari absolut | Re-auth online diperlukan untuk API/sync; local recovery tidak menggantikan sesi |
| Pencabutan sesi saat perangkat offline | Efek pada server diketahui ketika reconnect; jangan klaim remote deletion |

Pengguna yang membuka kembali setelah Soft/Hard Unlock dikembalikan ke halaman sebelumnya bila masih diizinkan. Data finansial sensitif tidak boleh tetap terlihat di bawah lock overlay atau di state yang dapat dibaca oleh akun lain.

### 11.3 Pemulihan keamanan lokal

- Lupa PIN: melalui jalur pembukaan kuat yang sah, lalu setel PIN baru; pending tidak dihapus.
- Lupa passphrase: authenticator kompatibel yang masih bisa membuka data atau Recovery Key dapat digunakan.
- Authenticator gagal/hilang: fallback passphrase atau Recovery Key.
- Recovery Key hilang tetapi DEK masih bisa diakses sah: buat pengganti dengan verifikasi dan penyimpanan aman, sebelum yang lama dinonaktifkan.
- Semua jalur hilang: UI harus mengakui kemungkinan data lokal tidak dapat dipulihkan, bukan menjanjikan reset PIN akan mengembalikannya.

### 11.4 Kebutuhan security UX

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-SEC-01 | Offline Access ditawarkan tetapi opsional; status nonaktif tidak memblokir penggunaan online. | BR-OFF-01, 02 |
| PR-SEC-02 | Setup wajib menyiapkan PIN 6 digit, perlindungan DEK kuat, dan Recovery Key yang dikonfirmasi. | BR-OFF-03, 07 |
| PR-SEC-03 | Soft Lock setelah 5 menit idle dapat dibuka PIN hanya bila kunci data tetap tersedia dalam sesi. | BR-OFF-04 |
| PR-SEC-04 | Hard Lock memakai authenticator kompatibel/passphrase/Recovery Key, bukan PIN saja. | BR-OFF-04, 05 |
| PR-SEC-05 | Expiry validasi offline tujuh hari menahan akses offline tetapi mempertahankan data. | BR-OFF-06 |
| PR-SEC-06 | Recovery Key diuji memulihkan data lokal yang ada; tidak disebut sebagai pemulihan data browser yang terhapus. | BR-OFF-07, 19 |
| PR-SEC-07 | Logout/pergantian akun mengisolasi state sensitif dan tidak menghapus pending diam-diam. | BR-OFF-16 |
| PR-SEC-08 | Menu hapus data offline dengan pending memakai konfirmasi ekstra dan peringatan permanen. | BR-OFF-17 |
| PR-SEC-09 | Device management tidak mengklaim data perangkat lain telah dihapus ketika sesi dicabut. | BR-AUTH-07 |
| PR-SEC-10 | Install PWA opsional; perubahan status support PRF menggunakan fallback kuat tanpa mengorbankan Recovery Key. | BR-OFF-03, 07 |

## 12. Draft, offline queue, Sync Center, dan konflik

### 12.1 Draft lifecycle

- Draft dibuat ketika pengguna mulai mengubah form. **Draft bukan transaksi dan tidak menambah estimasi**.
- Saat Offline Access aktif, draft auto-save secara persisten dalam encrypted IndexedDB. Status “Draft tersimpan” hanya muncul sesudah write benar-benar sukses; lampiran lokal mengikuti perlindungan yang sama.
- Saat Offline Access nonaktif, draft dipertahankan selama sesi SPA aktif; tidak ada janji survive reload/restart.
- Draft dapat dibuka kembali, diedit, atau dihapus dengan konfirmasi. Tidak ada kedaluwarsa otomatis yang memusnahkan draft terlindungi.
- Setelah pengguna menekan Simpan dan penulisan aktivitas berhasil, draft beralih menjadi Pending atau menjadi Synced tergantung jalur; tidak boleh masih dihitung ganda sebagai draft lain.

### 12.2 Aktivitas yang mendukung offline

Saat Offline Access aktif dan masih berlaku: membuat Increase, Deduct, peminjam baru, pinjaman, pembayaran. Tindakan edit/delete/restore pada transaksi **yang sudah synced**, balance adjustment, arsip/reaktivasi peminjam, pengelolaan kategori, Reports dan export tetap online-only pada MVP (kecuali jika hanya membaca cache yang tersedia dan tidak melakukan mutasi).

Pending lokal dapat diedit/cancel sebelum terkirim. Saat syncing/outcome unknown, edit/cancel ditahan. Pengguna dapat melihat dependency: peminjam baru harus synced sebelum pinjaman/pembayarannya.

### 12.3 Sync Center dan feedback

**Tab/penyaringan yang diusulkan:** Semua · Menunggu · Sedang diproses · Perlu tindakan · Tersinkron (riwayat ringkas). Satu item menampilkan: jenis, tanggal efektif, nominal, penerima/peminjam bila ada, status sinkronisasi, jumlah percobaan bila relevan, error singkat, tombol aksi sesuai status, serta badge evidence.

**Partial Sync:** aktivitas valid dan independen diproses, konflik serta dependensinya tetap ditahan. Jika server mengalami perubahan lain yang tidak menyebabkan pelanggaran bisnis, aktivitas valid diterima otomatis dan saldo/estimasi direkonsiliasi tanpa konfirmasi manual tambahan.

**Retry:** gangguan sementara maksimal **3 kali otomatis per siklus** dengan backoff. Setelah itu status menunggu; ketika ada kesempatan/pengguna memilih Retry, siklus baru dapat dimulai. Konflik bisnis tidak dicoba ulang tanpa koreksi.

**Unknown outcome:** setelah timeout pasca-kirim, UI menampilkan “Memeriksa hasil”; menggunakan identitas operasi untuk mendapatkan hasil commit yang sudah ada, bukan membuat mutasi baru. Setelah terkonfirmasi, status berubah menjadi Synced dan lokal diperbarui.

**Hard Lock:** menahan sync hingga data dibuka kembali. Foreground-first sebagai jalur utama; tidak ada janji auto background saat aplikasi tertutup.

### 12.4 Kebutuhan offline dan sync

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-OFF-01 | Autosave draft sesuai Offline Access; draft tidak memengaruhi angka finansial. | BR-OFF-10 |
| PR-OFF-02 | Pending, draft, dan bukti pending tidak dieviction akibat batas cache biasa. | BR-OFF-11 |
| PR-OFF-03 | Offline creation dibatasi ke empat aktivitas finansial + profil peminjam baru. | BR-OFF-08 |
| PR-OFF-04 | Peminjam yang dibuat offline tersinkron sebelum aktivitas dependennya. | BR-OFF-08, 12 |
| PR-OFF-05 | Pending dapat diedit/cancel hanya sebelum request syncing; status unknown dikunci hingga jelas. | BR-OFF-09, 13 |
| PR-OFF-06 | Sync menggunakan Partial Sync, auto-accept aktivitas valid, tahan konflik dan dependensi. | BR-OFF-12 |
| PR-OFF-07 | Status hasil tak diketahui diperiksa; retry tidak menggandakan efek transaksi. | BR-OFF-13 |
| PR-OFF-08 | Error sementara diretry maksimum tiga per siklus dengan backoff; konflik perlu koreksi. | BR-OFF-14 |
| PR-OFF-09 | Sync otomatis foreground jika aplikasi aktif, unlock, online, sesi valid; Hard Lock menahan sync. | BR-OFF-15 |
| PR-OFF-10 | Logout dengan pending diperbolehkan setelah peringatan; data lokal tetap per akun. | BR-OFF-16 |
| PR-OFF-11 | Penghapusan data offline dengan pending butuh konfirmasi ekstra, konsekuensi loss jelas. | BR-OFF-17 |
| PR-OFF-12 | Estimasi disajikan hanya jika snapshot/cache memungkinkan perhitungan yang benar. | BR-OFF-18 |
| PR-OFF-13 | History cache dibatasi dan kekosongan cache dibedakan dari “memang tidak ada transaksi”. | BR-OFF-11, 19 |
| PR-OFF-14 | Konflik akibat kategori arsip, waktu masa depan, kronologi piutang, dan integritas freeze punya pesan serta tindakan yang jelas. | BR-HIS-04; BR-FIN-03, 14; BR-REC-10 |

### 12.5 Status error Sync Center

| Masalah | Status lokal | Aksi pengguna/sistem |
|---|---|---|
| Tidak ada koneksi ke API | Retry waiting | Periksa koneksi; retry saat memungkinkan |
| Timeout sesudah submit | Checking outcome | Periksa hasil operasi yang sama |
| Peminjam baru gagal dibuat | Conflict/Blocked | Koreksi profil; aktivitas terkait tetap ditahan |
| Pembayaran piutang historis tidak valid | Conflict | Ubah nominal/tanggal/aktivitas terkait secara sah |
| Kategori telah diarsipkan | Conflict | Ganti kategori aktif atau kosongkan |
| Timestamp masa depan | Conflict | Pengguna koreksi waktu; jangan ganti otomatis |
| Refresh token/sesi dicabut | Auth required | Login kembali; data lokal tetap tersimpan |
| Financial Integrity Freeze | Blocked by integrity | Tunggu operator; jangan retry otomatis tanpa perubahan status |
| Bukti transaksi gagal upload | Evidence failed | Retry bukti saja; status finansial tetap confirmed |

## 13. Attachment UX dan file handling

### 13.1 Form upload dan preview

Satu lampiran opsional per transaksi: JPG, PNG, WebP, PDF maksimal 10 MB. Di mobile, pilih kamera, galeri, atau file melalui kemampuan browser yang tersedia. UI harus menampilkan nama, ukuran, tipe, status upload, serta tindakan lihat/ganti/hapus ketika diizinkan.

Upload **terpisah** dari financial commit: transaksi berhasil menjadi Synced walaupun bukti belum berhasil diunggah. Berkas pending yang dibuat offline harus terenkripsi dan tetap tertahan sampai benar-benar berhasil dikirim dan terverifikasi. File yang belum lolos pemeriksaan server belum boleh diberi label “Bukti tersedia”.

### 13.2 Kebutuhan attachment

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-FILE-01 | Batasi maksimal satu lampiran opsional per transaksi. | BR-FILE-01 |
| PR-FILE-02 | Validasi format JPG/PNG/WebP/PDF dan batas 10 MB dengan pesan jelas. | BR-FILE-02 |
| PR-FILE-03 | Preview/download hanya setelah otorisasi dan validasi server; jangan gunakan URL publik permanen. | BR-FILE-03, 06 |
| PR-FILE-04 | Kegagalan upload tidak membatalkan financial commit dan tidak mengulangi transaksi. | BR-FILE-04 |
| PR-FILE-05 | Lampiran pending offline dienkripsi dan statusnya terpisah dari state finansial. | BR-FILE-05 |
| PR-FILE-06 | Berkas belum tervalidasi diberi status karantina/validasi, bukan tersedia. | BR-FILE-06 |

## 14. Settings, perangkat, timezone, dan tema

### 14.1 Halaman Settings

Pengaturan minimum: profil akun, zona waktu, Light/Dark/System, kategori, aktivasi dan pengelolaan Offline Access, perubahan PIN/kredensial kuat/Recovery Key, daftar sesi perangkat, logout perangkat/all devices, clear offline data, serta informasi versi PWA.

**Zona waktu akun:** default `Asia/Jakarta`, dapat dipilih zona waktu lain. Ketika mengubah, tampilkan peringatan bahwa tanggal kalender dan kelompok laporan historis bisa berubah, tetapi **waktu absolut transaksi/snapshot tidak diubah**. Pengaturan tidak boleh memodifikasi effective timestamp yang sebelumnya telah disimpan.

**Device revocation:** tampilkan nama/peramban dan waktu terakhir online yang diketahui dengan jelas. Server tidak menjanjikan status pending real-time dari perangkat offline. Cabut sesi berarti memblokir akses API berikutnya, **bukan** remote wipe yang terjamin.

**Clear Offline Data:** bila pending/draft/evidence ada, konfirmasi ekstra menyebut kemungkinan hilangnya data permanen. Dapat dilanjutkan atas pilihan sadar pengguna; jangan menyamarkan sebagai logout.

### 14.2 Kebutuhan Settings

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-SET-01 | Light, Dark, System tersedia dan dipertahankan sebagai preferensi pengguna. | BR-UX-03 |
| PR-SET-02 | Timezone default Asia/Jakarta; perubahan disertai penjelasan regrouping historis. | BR-RPT-11 |
| PR-SET-03 | Sesi perangkat dapat dilihat/dicabut tanpa klaim remote wipe. | BR-AUTH-05, 07 |
| PR-SET-04 | Offline Access dapat diaktifkan setelah onboarding lewat Settings dengan setup keamanan lengkap. | BR-OFF-01, 03 |
| PR-SET-05 | Tindakan hapus data lokal terpisah dari logout dan memerlukan konfirmasi ekstra ketika ada pending. | BR-OFF-16, 17 |
| PR-SET-06 | Prompt-Based Update tersedia saat versi baru ditemukan; tidak reload paksa ketika draft/sync masih aktif. | BR-UX-06 |

## 15. Empty states, error UX, dan notifikasi

### 15.1 Standar empty/error states

| Kondisi | Copy inti yang disarankan | Tindakan |
|---|---|---|
| Akun baru tanpa transaksi | “Belum ada transaksi” | Tambah transaksi |
| Filter tidak menghasilkan data | “Tidak ada transaksi pada periode ini” | Ubah filter |
| Data cache offline belum lengkap | “Sebagian riwayat tidak tersedia offline” | Hubungkan internet |
| Report dibuka offline | “Laporan resmi memerlukan koneksi” | Coba lagi saat online |
| Penyimpanan draft lokal gagal | “Draft belum berhasil disimpan” | Coba simpan lagi/jangan tutup sembarang |
| Sync outcome belum diketahui | “Memeriksa hasil transaksi” | Tunggu/cek hasil operasi |
| Bisnis menolak pembayaran | “Riwayat piutang menjadi tidak valid” | Koreksi transaksi |
| Offline Access kedaluwarsa | “Validasi online diperlukan” | Sambungkan dan validasi ulang |
| Financial Integrity Freeze | “Aktivitas finansial sementara dibatasi” | Informasi status/perlu verifikasi operator |
| Proses backup recovery | “Layanan keuangan sedang diverifikasi” | Lihat data read-only bila aman |

### 15.2 Notifikasi produk

- Keberhasilan biasa menggunakan toast singkat; status kritis (Conflict, Freeze, Offline Expired) tetap terlihat pada halaman/Sync Center sampai diatasi.
- Tidak ada persyaratan **push notification** atau notifikasi background eksternal pada MVP.
- Ketika aplikasi terkunci, notifikasi tidak mengungkap nominal, nama peminjam, Recovery Key, atau informasi sensitif.
- Tindakan berisiko (delete, logout dengan pending, clear offline data, perubahan timezone, adjustment) memerlukan penjelasan sebelum konfirmasi sesuai dampaknya.

### 15.3 Kebutuhan feedback

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-UX-01 | Seluruh state utama (loading, empty, offline, error, conflict, confirmed) dibedakan dengan istilah konsisten. | BR-UX-08 |
| PR-UX-02 | Status sync hadir di header dan tetap dapat ditelusuri melalui Sync Center. | BR-UX-04 |
| PR-UX-03 | Quick Add, bottom nav, sidebar, dan komponen form punya perilaku yang setara di desktop/mobile. | BR-UX-01, 02 |
| PR-UX-04 | Setelah unlock, kembali ke halaman sebelumnya bila masih sah. | BR-UX-05 |
| PR-UX-05 | Prompt-Based Update tidak reload paksa; pending/draft divalidasi sebelum update. | BR-UX-06 |

## 16. Accessibility dan desain responsif

**Target:** WCAG 2.2 Level AA pada seluruh alur utama. UI final harus diverifikasi, tidak cukup sekadar memilih library komponen aksesibel.

| Area | Acceptance UI |
|---|---|
| Navigasi keyboard | Semua kontrol dapat difokus dan dipakai keyboard, urutan fokus logis |
| Fokus/modal | Fokus masuk dialog, terjaga di dalam selama terbuka, kembali ke pemicu setelah ditutup |
| Label dan error | Input diberi label jelas, invalid dapat ditemukan tanpa bergantung warna |
| Status dinamis | Simpan, sync, conflict, dan error diumumkan sesuai semantik status/screen reader |
| Status uang | +/− dan label Increase/Deduct/No Balance Impact tersedia, bukan warna saja |
| Grafik | Ringkasan tekstual/tabel tersedia sebagai alternatif |
| Touch target | Kontrol utama ditargetkan nyaman disentuh, rekomendasi desain 44×44 px jika memungkinkan |
| Zoom/reflow | Layar utama tetap bisa digunakan pada teks besar dan viewport mobile sempit |
| Motion | Hormati preferensi reduced motion |
| Safe area | Bottom navigation dan tombol sticky tidak tertutup gesture area/keyboard |

| ID | Perilaku | Referensi BRD |
|---|---|---|
| PR-A11Y-01 | Alur auth, Quick Add, piutang, History, Reports, dan Sync Center memenuhi target WCAG 2.2 AA. | BR-UX-07 |
| PR-A11Y-02 | Status dan jenis uang dapat dibedakan tanpa mengandalkan warna. | BR-UX-07 |
| PR-A11Y-03 | Pengumuman status dinamis tidak menyebabkan kehilangan fokus. | BR-UX-07, 08 |
| PR-A11Y-04 | Dialog security/recovery dan form dapat digunakan lewat keyboard dan pembaca layar. | BR-UX-07 |

## 17. State transition dan aturan lintas layar

### 17.1 Matriks operasi

| Aksi | Online + unlocked | Offline Access sah | Hard Lock / 7 hari habis |
|---|---|---|---|
| Buat Increase/Deduct | Confirmed setelah commit | Pending terenkripsi | Diblokir sampai pembukaan/validasi |
| Buat peminjam, pinjam, bayar | Confirmed setelah commit | Pending + dependensi | Diblokir |
| Edit/cancel pending belum dikirim | Diizinkan lokal | Diizinkan lokal | Diblokir sampai unlock |
| Edit/delete/restore confirmed | Diizinkan dengan validasi | Tidak tersedia | Tidak tersedia |
| Balance Adjustment | Diizinkan online | Tidak tersedia | Tidak tersedia |
| Archive/reactivate peminjam/kategori | Diizinkan online | Tidak tersedia | Tidak tersedia |
| Reports/export | Diizinkan online | Tidak tersedia | Tidak tersedia |
| Lihat riwayat | Server + pending berlabel | Cache parsial + pending | Terkunci |
| Sync Center | Lihat dan proses ketika sah | Lihat queue lokal saat unlocked | Terkunci |
| Logout | Diizinkan, peringatan pending | Boleh keluar lokal dengan peringatan jika aplikasi dapat menjalankan logout lokal; revocation server menyusul saat online | Tidak menghapus pending |

### 17.2 Konflik dan precedence produk

**Precedence tampilan dan kemampuan:** (1) isolasi akun dan pemegang kunci, (2) Hard Lock/Soft Lock, (3) masa validasi offline dan status sesi, (4) recovery/freeze global atau freeze akun, (5) capability online/offline per layar, (6) status pending/hasil sync. Sebuah banner offline tidak boleh menutupi pesan Hard Lock yang lebih penting; tombol finansial tidak aktif saat freeze walaupun tampilan cache masih tersedia.

### 17.3 Multi-tab dan update PWA

- Perubahan akun/logout/lock diumumkan ke tab lain secara aman. Jangan menyisakan data akun sebelumnya di tab lain.
- Dua tab tidak boleh membuat dua efek server untuk pending yang sama; pengguna melihat status yang akhirnya konsisten.
- Prompt update tidak boleh memaksa reload di tengah draft/sync; migrasi data encrypted harus menjaga kemampuan recovery. Jika migrasi gagal, data sebelumnya dipertahankan dan UI tidak memberi status berhasil palsu.

## 18. Journey dan acceptance tests end-to-end

Bagian ini mempertahankan **25 skenario penerimaan BRD** dan menambahkan observasi UI yang diharapkan. ID `AC-xx` berasal dari BRD; tidak boleh ditafsirkan sebagai implementasi yang sudah lulus.

| AC | Skenario pengguna | Hasil produk yang dapat diamati |
|---|---|---|
| AC-01 | Lewati opening balance lalu input transaksi historis | Saldo saat ini mengikuti transaksi; tidak ada snapshot onboarding |
| AC-02 | Konfirmasi saldo awal Rp0 lalu backdate sebelum onboarding | Snapshot Rp0 dipertahankan; saldo kini tidak double-count |
| AC-03 | Edit expense historis sebelum snapshot | Delta adjustment yang terdampak berubah; target snapshot tetap; audit terlihat |
| AC-04 | Dua Deduct paralel dari perangkat berbeda | Keduanya tercatat satu kali; saldo resmi benar |
| AC-05 | Dua perangkat mengedit versi transaksi sama | Versi lama ditolak; UI menawarkan memuat ulang |
| AC-06 | Pinjaman dengan pengaruh saldo OFF | Piutang naik; saldo utama dan income/expense tidak berubah; History berlabel |
| AC-07 | Pembayaran historis menyebabkan piutang negatif | Ditolak utuh; error menunjuk masalah kronologi |
| AC-08 | Peminjam Paid lalu arsip, koreksi membuat outstanding | Profil aktif kembali dengan audit; tidak bisa membuat aktivitas baru saat masih arsip |
| AC-09 | Kategori arsip pada transaksi lama | Riwayat dan laporan tetap menampilkan kategori lama; pilihan baru tidak tersedia |
| AC-10 | Pending memakai kategori yang diarsipkan perangkat lain | Conflict; user memilih kategori aktif/kosong; tidak ada penggantian diam-diam |
| AC-11 | Tanggal atau jam efektif masa depan | Ditolak dengan kesalahan field; tanggal tidak diubah diam-diam |
| AC-12 | Tinggalkan draft saat Offline Access aktif, restart | Hard Unlock lalu draft terenkripsi dapat dilanjutkan |
| AC-13 | Tinggalkan draft tanpa Offline Access, sesi ditutup | Tidak dijanjikan pemulihan persisten |
| AC-14 | Commit server sukses, respons sync hilang | Checking outcome; status diperiksa; saldo dipengaruhi satu kali |
| AC-15 | Satu item batch sync konflik | Item independen tersinkron, konflik dan dependensi menunggu |
| AC-16 | Logout/berganti akun dengan pending | Peringatan, data akun asal terkunci dan terisolasi |
| AC-17 | Lupa PIN dengan Recovery Key, data lokal ada | Recovery benar-benar membuka ciphertext tanpa kehilangan pending |
| AC-18 | Restart browser lalu mencoba PIN saja | Hard Unlock menuntut authenticator/passphrase/Recovery Key |
| AC-19 | Lewat 7 hari tanpa validasi online | Akses offline tertahan, pending tidak terhapus |
| AC-20 | Reports diakses offline | Pesan online-only; cache parsial bukan laporan resmi |
| AC-21 | Upload bukti gagal sesudah financial commit | Transaksi tetap confirmed, evidence dapat di-retry terpisah |
| AC-22 | Materialized balance terbukti tidak cocok ledger | Financial Freeze; operator saja yang bisa memulihkan dengan audit |
| AC-23 | Database selesai restore PITR | Financial Recovery Mode menahan sync/mutasi sampai verifikasi |
| AC-24 | Update PWA ketika draft/pending ada | Tidak reload paksa, migrasi/penjagaan data dinyatakan aman atau ditunda |
| AC-25 | Timezone akun diganti | Instant tidak berubah, pengelompokan tanggal ikut zona waktu baru, ada peringatan |

### 18.1 Skenario P0 tambahan untuk produk

- P0-UX-01: dua browser tab aktif; hanya satu efek transaksi setelah keduanya mencoba sync item sama.
- P0-UX-02: local IndexedDB tidak dapat menulis/kehabisan quota; tidak muncul status “Pending tersimpan”.
- P0-UX-03: Recovery Key tersedia tetapi browser storage sudah dibersihkan; UI menjelaskan ketidakmampuan memulihkan data hilang.
- P0-UX-04: saat freeze, history/audit masih bisa dilihat sesuai hak, namun pembuatan transaksi online dan sync ditahan.
- P0-UX-05: transaksi pending sebelum snapshot tidak mengubah saldo estimasi seolah-olah mutasi pascasnapshot; bila tidak dapat dihitung, status estimasi tidak tersedia.
- P0-UX-06: hasil ekspor seluruh detail sesuai filter, termasuk data pada halaman pagination yang tidak sedang ditampilkan.
- P0-UX-07: perubahan confirmed pada perangkat lain membuat data Dashboard diperbarui saat online tanpa mengubah pending lokal secara diam-diam.

## 19. Nonfunctional product requirements dan quality gates

### 19.1 Persyaratan nonfungsional

| ID | Kebutuhan produk | Sumber |
|---|---|---|
| PR-NFR-01 | Isolasi multi-akun di seluruh UI, API, cache, bukti, dan ekspor. | BR-AUTH-04 |
| PR-NFR-02 | Tidak ada efek finansial ganda akibat retry, timeout, atau dua tab. | BR-OFF-13; BR-FIN-13 |
| PR-NFR-03 | Materialized balance dapat direkonsiliasi dari ledger dan snapshot; anomali terverifikasi membekukan mutasi. | BR-FIN-10, 14 |
| PR-NFR-04 | Audit rinci append-only untuk semua aksi finansial dan perubahan snapshot terdampak. | BR-HIS-10 |
| PR-NFR-05 | Evidence dan ekspor disimpan privat, tidak dibocorkan melalui URL tidak sah. | BR-FILE-03; BR-RPT-10 |
| PR-NFR-06 | Backup harian/PITR off-VPS, RPO target ≤1 jam dan RTO target ≤4 jam dibuktikan restore drill. | BR-OPS-01, 02, 03 |
| PR-NFR-07 | Controlled Recovery menahan mutasi dan sync pascarestore; operator melakukan verifikasi/pembukaan dengan audit. | BR-OPS-04, 05, 06 |
| PR-NFR-08 | Worker/jobs bertahan restart dan punya retry aman; tidak wajib Redis. | BR-OPS-07 |
| PR-NFR-09 | Monitoring kegagalan kritis tersedia tanpa menyimpan PIN, key, token, atau isi sensitif ke log. | BR-OPS-08 |
| PR-NFR-10 | Aksesibilitas alur utama ditargetkan WCAG 2.2 AA. | BR-UX-07 |
| PR-NFR-11 | Tanggal/waktu efektif dipertahankan sebagai instant absolut; grouping mengikuti timezone akun kini. | BR-RPT-11; BR-FIN-12 |

### 19.2 Release gates dan bukti yang dibutuhkan

**Gate Financial:** seluruh AC keuangan, concurrency, kronologi piutang, snapshot, dan audit lulus automated integration/property tests; tidak ada defect kritis yang diketahui.

**Gate Offline Security:** browser target yang didukung terbukti dapat Hard Unlock, fallback passphrase, Recovery Key, serta pemulihan draft/pending setelah restart; hasil kegagalan kompatibilitas dicatat dan fallback diterapkan.

**Gate Sync:** Partial Sync, dependensi, unknown outcome, dua tab, retry, dan evidence pending terbukti tidak menghasilkan efek finansial ganda.

**Gate UX/A11Y:** alur utama diuji keyboard, screen reader, responsif mobile, safe area, dark/light mode, dan WCAG 2.2 AA.

**Gate Recovery:** restore drill membuktikan target RPO/RTO yang realistis, audit/freeze berfungsi, dan penanganan transaksi confirmed yang berpotensi hilang dijalankan tanpa replay otomatis tak terverifikasi.

Tidak ada target performa milidetik atau jumlah user concurrent yang diputuskan saat pembahasan. Nilai benchmark, rate limit, kapasitas berkas total, dan ambang monitoring merupakan kebijakan teknis terukur pada spesifikasi/operasional, bukan janji produk yang diada-adakan.

## 20. Traceability BRD → PRD

Setiap BRD ID dicakup oleh satu atau lebih bagian PRD. Bagian ini menyediakan **indeks cakupan 96 kebutuhan** agar tidak ada requirement bisnis yang terlewat; mapping rinci ke test cases dan desain teknis akan dipertajam pada Technical Specification.


### 20.1 Kelompok AUTH (8 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-AUTH-01 | PR-AUTH-01 | §4, 11, 14 |
| BR-AUTH-02 | PR-AUTH-02 | §4, 11, 14 |
| BR-AUTH-03 | PR-AUTH-03 | §4, 11, 14 |
| BR-AUTH-04 | PR-AUTH-08, PR-NFR-01 | §4, 11, 14 |
| BR-AUTH-05 | PR-AUTH-04, PR-SET-03 | §4, 11, 14 |
| BR-AUTH-06 | PR-AUTH-05, PR-AUTH-06 | §4, 11, 14 |
| BR-AUTH-07 | PR-SEC-09 | §4, 11, 14 |
| BR-AUTH-08 | PR-AUTH-07 | §4, 11, 14 |

### 20.2 Kelompok FIN (14 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-FIN-01 | PR-TXN-03 | §5–7, 17 |
| BR-FIN-02 | PR-TXN-04 | §5–7, 17 |
| BR-FIN-03 | PR-OFF-14 | §5–7, 17 |
| BR-FIN-04 | PR-BAL-01 | §5–7, 17 |
| BR-FIN-05 | PR-BAL-01 | §5–7, 17 |
| BR-FIN-06 | PR-BAL-02, PR-BAL-03 | §5–7, 17 |
| BR-FIN-07 | PR-BAL-04 | §5–7, 17 |
| BR-FIN-08 | PR-BAL-04, PR-HIS-08 | §5–7, 17 |
| BR-FIN-09 | PR-BAL-05 | §5–7, 17 |
| BR-FIN-10 | PR-NFR-03 | §5–7, 17 |
| BR-FIN-11 | PR-BAL-06, PR-HIS-04 | §5–7, 17 |
| BR-FIN-12 | PR-NFR-11 | §5–7, 17 |
| BR-FIN-13 | PR-HIS-05, PR-NFR-02, PR-TXN-05 | §5–7, 17 |
| BR-FIN-14 | PR-NFR-03 | §5–7, 17 |

### 20.3 Kelompok REC (11 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-REC-01 | PR-REC-01 | §8, 17 |
| BR-REC-02 | PR-REC-01 | §8, 17 |
| BR-REC-03 | PR-REC-02 | §8, 17 |
| BR-REC-04 | PR-REC-03 | §8, 17 |
| BR-REC-05 | PR-REC-04, PR-REC-05 | §8, 17 |
| BR-REC-06 | PR-REC-05 | §8, 17 |
| BR-REC-07 | PR-REC-06 | §8, 17 |
| BR-REC-08 | PR-REC-07 | §8, 17 |
| BR-REC-09 | PR-REC-08 | §8, 17 |
| BR-REC-10 | PR-OFF-14 | §8, 17 |
| BR-REC-11 | PR-REC-10 | §8, 17 |

### 20.4 Kelompok HIS (11 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-HIS-01 | PR-CAT-01, PR-CAT-05 | §9, 12 |
| BR-HIS-02 | PR-CAT-02, PR-HIS-07 | §9, 12 |
| BR-HIS-03 | PR-CAT-03 | §9, 12 |
| BR-HIS-04 | PR-CAT-04, PR-OFF-14 | §9, 12 |
| BR-HIS-05 | PR-HIS-01, PR-TXN-08 | §9, 12 |
| BR-HIS-06 | PR-HIS-02 | §9, 12 |
| BR-HIS-07 | PR-HIS-04, PR-HIS-05 | §9, 12 |
| BR-HIS-08 | PR-HIS-06 | §9, 12 |
| BR-HIS-09 | PR-HIS-05 | §9, 12 |
| BR-HIS-10 | PR-HIS-08, PR-NFR-04 | §9, 12 |
| BR-HIS-11 | PR-HIS-03 | §9, 12 |

### 20.5 Kelompok OFF (19 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-OFF-01 | PR-SEC-01, PR-SET-04 | §11–12, 17 |
| BR-OFF-02 | PR-SEC-01 | §11–12, 17 |
| BR-OFF-03 | PR-SEC-02, PR-SEC-10 | §11–12, 17 |
| BR-OFF-04 | PR-SEC-03, PR-SEC-04 | §11–12, 17 |
| BR-OFF-05 | PR-SEC-04 | §11–12, 17 |
| BR-OFF-06 | PR-SEC-05 | §11–12, 17 |
| BR-OFF-07 | PR-SEC-06 | §11–12, 17 |
| BR-OFF-08 | PR-OFF-03, PR-OFF-04, PR-REC-09, PR-TXN-06 | §11–12, 17 |
| BR-OFF-09 | PR-HIS-09, PR-OFF-05 | §11–12, 17 |
| BR-OFF-10 | PR-OFF-01 | §11–12, 17 |
| BR-OFF-11 | PR-OFF-02, PR-OFF-13 | §11–12, 17 |
| BR-OFF-12 | PR-OFF-06 | §11–12, 17 |
| BR-OFF-13 | PR-NFR-02, PR-OFF-07, PR-TXN-05, PR-TXN-07 | §11–12, 17 |
| BR-OFF-14 | PR-OFF-08 | §11–12, 17 |
| BR-OFF-15 | PR-OFF-09 | §11–12, 17 |
| BR-OFF-16 | PR-AUTH-06, PR-AUTH-08, PR-OFF-10, PR-SEC-07, PR-SET-05 | §11–12, 17 |
| BR-OFF-17 | PR-OFF-11, PR-SEC-08 | §11–12, 17 |
| BR-OFF-18 | PR-DASH-05, PR-DASH-06, PR-OFF-12 | §11–12, 17 |
| BR-OFF-19 | PR-OFF-13, PR-SEC-06 | §11–12, 17 |

### 20.6 Kelompok RPT (11 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-RPT-01 | PR-DASH-01 | §5, 10 |
| BR-RPT-02 | PR-DASH-03, PR-RPT-03 | §5, 10 |
| BR-RPT-03 | PR-BAL-05, PR-DASH-02, PR-RPT-02 | §5, 10 |
| BR-RPT-04 | PR-RPT-02 | §5, 10 |
| BR-RPT-05 | PR-DASH-04, PR-RPT-06 | §5, 10 |
| BR-RPT-06 | PR-RPT-04 | §5, 10 |
| BR-RPT-07 | PR-RPT-05 | §5, 10 |
| BR-RPT-08 | PR-DASH-05, PR-RPT-01 | §5, 10 |
| BR-RPT-09 | PR-RPT-07 | §5, 10 |
| BR-RPT-10 | PR-NFR-05, PR-RPT-08, PR-RPT-09 | §5, 10 |
| BR-RPT-11 | PR-NFR-11, PR-RPT-10, PR-SET-02 | §5, 10 |

### 20.7 Kelompok FILE (6 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-FILE-01 | PR-FILE-01 | §13 |
| BR-FILE-02 | PR-FILE-02 | §13 |
| BR-FILE-03 | PR-FILE-03, PR-HIS-03, PR-NFR-05 | §13 |
| BR-FILE-04 | PR-FILE-04 | §13 |
| BR-FILE-05 | PR-FILE-05, PR-TXN-06 | §13 |
| BR-FILE-06 | PR-FILE-06 | §13 |

### 20.8 Kelompok UX (8 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-UX-01 | PR-TXN-01, PR-UX-03 | §3, 15–16 |
| BR-UX-02 | PR-TXN-02 | §3, 15–16 |
| BR-UX-03 | PR-SET-01 | §3, 15–16 |
| BR-UX-04 | PR-DASH-07, PR-UX-02 | §3, 15–16 |
| BR-UX-05 | PR-UX-04 | §3, 15–16 |
| BR-UX-06 | PR-SET-06, PR-UX-05 | §3, 15–16 |
| BR-UX-07 | PR-A11Y-01, PR-A11Y-02, PR-A11Y-03, PR-A11Y-04, PR-DASH-04, PR-NFR-10, PR-RPT-06 | §3, 15–16 |
| BR-UX-08 | PR-DASH-08, PR-TXN-08, PR-UX-01 | §3, 15–16 |

### 20.9 Kelompok OPS (8 kebutuhan)

| BRD ID | PRD requirement yang menampung | Bagian produk |
|---|---|---|
| BR-OPS-01 | PR-NFR-06 | §18–19 |
| BR-OPS-02 | PR-NFR-06 | §18–19 |
| BR-OPS-03 | PR-NFR-06 | §18–19 |
| BR-OPS-04 | PR-NFR-07 | §18–19 |
| BR-OPS-05 | PR-NFR-07 | §18–19 |
| BR-OPS-06 | PR-NFR-07 | §18–19 |
| BR-OPS-07 | PR-NFR-08, PR-RPT-09 | §18–19 |
| BR-OPS-08 | PR-NFR-09 | §18–19 |

**Pemeriksaan cakupan:** 96 dari 96 identitas BR- pada BRD v0.1 memiliki rujukan persyaratan PRD. Terdapat 120 identitas persyaratan PR- unik dalam PRD. Pemetaan ini bersifat indeks; satu kebutuhan BRD dapat diturunkan menjadi lebih dari satu acceptance test.
