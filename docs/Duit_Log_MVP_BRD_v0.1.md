# Duit Log MVP — Business Requirements Document (BRD)

**Versi:** 0.1 — baseline untuk peninjauan  
**Tanggal:** 21 November 2026  
**Status:** MVP scope frozen; dokumen BRD belum disetujui sebagai artefak final  
**Bahasa:** Indonesia  
**Tahap berikutnya:** Product Requirements Document (PRD), Technical Specification, dan AGENTS.md

> **Tujuan dokumen.** Menyatakan kebutuhan bisnis, batas ruang lingkup, aturan finansial, dan kriteria penerimaan Duit Log MVP secara konsisten dengan keputusan perancangan. Dokumen ini **bukan** rancangan tabel database, kontrak API, ataupun instruksi implementasi. Pilihan teknis yang telah diputuskan dicatat hanya sebagai batasan bisnis dan kualitas yang harus dihormati dalam spesifikasi lanjutan.

---

## 1. Ringkasan eksekutif

Duit Log adalah aplikasi pencatatan keuangan pribadi multi-pengguna berbasis web/PWA. Pengguna dapat memantau satu saldo utama, mencatat pemasukan dan pengeluaran, mengelola piutang per peminjam, memeriksa riwayat yang dapat diaudit, dan memperoleh laporan keuangan. Pembeda utama MVP adalah kemampuan **membuat transaksi ketika offline** dengan penyimpanan lokal terenkripsi dan sinkronisasi yang menjaga integritas saldo maupun piutang.

Duit Log bukan sistem rekening bank, layanan pembayaran, atau aplikasi akuntansi perusahaan. Saldo yang ditampilkan merupakan **catatan pengguna**, bukan hasil verifikasi mutasi bank. Meskipun begitu, perubahan data di dalam Duit Log harus deterministik, dapat ditelusuri, dan aman dari duplikasi akibat retry atau konkurensi.

**Pernyataan keberhasilan MVP:** seorang pengguna yang sudah terverifikasi dapat mencatat keuangan sehari-hari, termasuk saat koneksi terputus (jika Offline Access diaktifkan), kemudian kembali online tanpa transaksi terduplikasi, tanpa kehilangan keterkaitan piutang, dan tanpa perubahan saldo resmi yang tidak dapat dijelaskan.

## 2. Latar belakang, tujuan, dan batasan

### 2.1 Permasalahan yang diselesaikan

- Pencatatan pemasukan/pengeluaran manual sulit dirapikan dan ditelusuri ketika terjadi koreksi historis.
- Uang yang dipinjamkan kepada orang lain sering bercampur dengan laporan penghasilan/pengeluaran, sehingga kondisi keuangan terbaca keliru.
- Koneksi internet yang tidak stabil mengganggu pencatatan saat kejadian berlangsung.
- Data keuangan pada beberapa perangkat berisiko tidak sinkron, terduplikasi, atau tidak jelas mana yang sudah diterima server.
- Koreksi saldo yang tidak mempertahankan titik acuan aktual dapat menyebabkan *double counting* ketika pengguna memasukkan transaksi bertanggal lampau.

### 2.2 Tujuan bisnis

| ID | Tujuan |
|---|---|
| OBJ-01 | Memudahkan pencatatan aktivitas keuangan personal dengan alur cepat pada desktop dan mobile. |
| OBJ-02 | Menyediakan saldo utama dan total piutang terkini yang dapat ditelusuri ke aktivitas finansial. |
| OBJ-03 | Memisahkan pinjaman/pembayaran piutang dan penyesuaian saldo dari pendapatan serta pengeluaran operasional. |
| OBJ-04 | Memungkinkan pencatatan offline yang aman, dengan status sinkronisasi dan hasil rekonsiliasi yang transparan. |
| OBJ-05 | Menyediakan riwayat perubahan, koreksi, dan pelaporan yang konsisten. |
| OBJ-06 | Melindungi data antar-pengguna dan memungkinkan pemulihan operasional secara terkontrol ketika terjadi gangguan. |

### 2.3 Indikator keberhasilan dan penerimaan

Keberhasilan akan dinilai melalui pengujian dan pengamatan produk; **target numerik bisnis** seperti jumlah pengguna aktif, retensi, atau kecepatan respons rata-rata belum ditetapkan dan tidak boleh dianggap keputusan final.

- Semua invarians saldo, snapshot, piutang, dan audit lulus pengujian otomatis kritis.
- Pengiriman ulang aktivitas finansial yang sama tidak menghasilkan pengaruh uang dua kali.
- Pengguna dapat memahami perbedaan data *confirmed*, *estimated*, *draft*, dan *pending*.
- Alur pemulihan data lokal melalui Recovery Key dapat dibuktikan pada perangkat/browser yang didukung.
- Backup/PITR dan prosedur pemulihan diuji terhadap target RPO/RTO yang disepakati.

## 3. Aktor dan kepemilikan data

| Aktor | Kebutuhan dan kewenangan |
|---|---|
| Pengunjung | Registrasi, login, dan pemulihan password. |
| Pengguna belum verifikasi email | Login serta akses terbatas ke proses verifikasi email dan pengelolaan sesi dasar; tidak boleh memakai fitur finansial. |
| Pengguna terverifikasi | Mengelola data finansial miliknya, pengaturan, keamanan perangkat, dan sinkronisasi. |
| Operator pemulihan berwenang | Memverifikasi anomali, melakukan tindakan perbaikan terkontrol, dan membuka Financial Integrity Freeze dengan audit. Bukan pengguna biasa. |
| Sistem Duit Log | Memvalidasi aturan keuangan, memperbarui saldo, menjaga audit, memproses sinkronisasi, dan menangani pemulihan sesuai kewenangan. |

Setiap pengguna memiliki ruang data terisolasi. Pengguna tidak dapat melihat transaksi, piutang, kategori custom, lampiran, atau cache lokal pengguna lain. **Satu saldo utama per akun** berlaku untuk MVP; tidak ada multi-wallet.

## 4. Definisi istilah dan prinsip bisnis

| Istilah | Makna dalam Duit Log |
|---|---|
| **Confirmed** | Aktivitas telah diterima dan dikonfirmasi server sebagai bagian dari keadaan finansial resmi. |
| **Pending** | Aktivitas sudah disimpan lokal dan diminta untuk disinkronkan, tetapi belum diterima server. |
| **Draft** | Form belum disimpan sebagai aktivitas finansial; tidak memengaruhi saldo maupun piutang. |
| **Effective time** | Waktu terjadinya aktivitas menurut pencatatan pengguna; digunakan untuk perhitungan kronologis. |
| **Action time** | Waktu server ketika sebuah operasi dibuat, diedit, dihapus, atau dipulihkan; digunakan untuk audit. |
| **Financial sequence** | Urutan sekunder immutable yang ditetapkan server untuk membedakan aktivitas dengan effective timestamp sama, sambil menghormati dependensi yang sah. |
| **Ledger** | Catatan aktivitas finansial otoritatif beserta pengaruh efektifnya. |
| **Materialized balance** | Saldo terkini yang disimpan agar cepat dibaca, tetapi harus sama dengan saldo hasil ledger dan snapshot. |
| **Balance snapshot** | Nilai saldo sebenarnya pada titik waktu tertentu yang dikonfirmasi pengguna; nilainya menjadi acuan otoritatif. |
| **Adjustment delta** | Selisih terhitung untuk mencapai target snapshot, bukan pemasukan/pengeluaran biasa. |
| **Off-ledger receivable movement** | Aktivitas piutang yang mengubah saldo piutang, tetapi tidak mengubah saldo utama karena toggle pengaruh saldo dimatikan. |
| **Financial Integrity Freeze** | Pembatasan mutasi keuangan pada akun yang terdeteksi memiliki anomali integritas terverifikasi. |
| **Controlled Recovery** | Pemulihan layanan melalui backup/PITR, verifikasi operator, dan rekonsiliasi; tidak menjanjikan *zero data loss*. |

**Prinsip umum:** server merupakan sumber kebenaran resmi; data lokal hanya menampilkan estimasi ketika ada aktivitas yang belum dikonfirmasi. Kegagalan satu bagian operasi finansial tidak boleh meninggalkan perubahan sebagian.

## 5. Ruang lingkup MVP

### 5.1 In-scope — wajib pada rilis MVP

| Domain | Kemampuan utama |
|---|---|
| Akun dan sesi | Register/login email-password, verifikasi email, reset password, isolasi akun, sesi perangkat, dan pencabutan sesi. |
| Saldo utama | Opening balance opsional, Increase, Deduct, saldo negatif, balance adjustment sebagai snapshot, serta rekalkulasi kronologis. |
| Piutang | Profil peminjam, pinjaman, pembayaran, riwayat, opsi pengaruh saldo utama, arsip peminjam, dan validasi saldo piutang. |
| Transaksi | Kategori, bukti opsional, pencarian/filter, edit/delete/restore online, audit terperinci, dan Recently Deleted. |
| Dashboard | Saldo terkonfirmasi, estimasi lokal, ringkasan pemasukan/pengeluaran, total piutang, dan grafik. |
| Laporan | Income/Expense, Balance Movement, Receivables, perbandingan periode, filter dan ekspor PDF/Excel online. |
| Offline PWA | Aktivasi opsional, transaksi dan peminjam baru offline, draft terenkripsi, queue, Partial Sync, konflik, dan status koneksi. |
| Keamanan lokal | PIN, Hybrid Lock, proteksi kunci kuat, authenticator yang kompatibel / fallback passphrase, dan Recovery Key. |
| Lampiran | Satu file per transaksi, upload terpisah dari commit finansial, penyimpanan privat. |
| Operasional | Append-only audit, reconciliation, financial freeze, operator recovery, backup/PITR, dan monitoring kritis. |

### 5.2 Out-of-scope — ditunda setelah MVP

- Multi-wallet atau banyak rekening dalam satu akun.
- Transaksi berulang otomatis, penjadwalan transaksi masa depan, dan recurring reminders.
- Penghapusan kewajiban piutang/*write-off* atau pengampunan utang otomatis.
- Push notification wajib dan sinkronisasi background saat aplikasi telah ditutup/Hard Lock.
- Admin dashboard operasional yang kompleks; prosedur operator terbatas cukup untuk MVP.
- Koneksi bank otomatis, transfer uang sungguhan, payment gateway, serta fitur pembayaran antar-pengguna.
- Mata uang selain IDR dan pecahan desimal nominal.

Penambahan fitur baru setelah *scope freeze* memerlukan persetujuan eksplisit; AI Coding Agent tidak boleh memperluas ruang lingkup secara mandiri.

## 6. Kebutuhan bisnis terperinci

Semua pernyataan beridentitas **BR-** di bawah ini adalah persyaratan yang harus dapat ditelusuri ke PRD, Technical Specification, dan acceptance tests.

### 6.1 Akun, autentikasi, dan sesi

| ID | Persyaratan bisnis |
|---|---|
| BR-AUTH-01 | Pengguna dapat mendaftar menggunakan nama, email, dan password, lalu login dengan email/password. |
| BR-AUTH-02 | Pengguna harus memverifikasi email sebelum memakai fitur finansial; sebelum verifikasi hanya alur autentikasi/verifikasi dan pengelolaan sesi dasar yang diizinkan. |
| BR-AUTH-03 | Sistem mendukung verifikasi email, pengiriman ulang email verifikasi, dan reset password melalui email. |
| BR-AUTH-04 | Seluruh data finansial, kategori personal, riwayat, dan bukti terisolasi berdasarkan pemilik akun. |
| BR-AUTH-05 | Pengguna dapat melihat dan mencabut sesi perangkat; logout perangkat dan logout semua perangkat harus membatalkan akses server terkait. |
| BR-AUTH-06 | Masa sesi login persisten maksimal **30 hari absolut** sejak login awal; rotasi refresh token tidak memperpanjang tenggat absolut tersebut. |
| BR-AUTH-07 | Pencabutan sesi tidak diklaim sebagai penghapusan data lokal jarak jauh; perangkat offline dapat belum mengetahui pencabutan sampai terhubung kembali. |
| BR-AUTH-08 | PIN Offline Access bukan kredensial autentikasi server dan tidak boleh memberi akses API tanpa sesi server valid. |

### 6.2 Saldo utama, transaksi, dan snapshot

| ID | Persyaratan bisnis |
|---|---|
| BR-FIN-01 | Setiap akun mempunyai satu saldo utama yang dapat bernilai negatif. Mata uang **IDR bilangan bulat tanpa desimal**. |
| BR-FIN-02 | Pengguna dapat mencatat **Increase** dan **Deduct** dengan nominal positif, tanggal efektif wajib (default hari ini), dan waktu default saat ini yang dapat diedit. Judul, kategori, deskripsi, serta bukti bersifat opsional. |
| BR-FIN-03 | Transaksi dengan effective timestamp lebih jauh dari waktu server saat validasi ditolak; hanya aktivitas sekarang atau masa lalu yang diperbolehkan. |
| BR-FIN-04 | Saldo awal saat onboarding opsional. Jika diisi, termasuk **Rp0**, nilai tersebut merupakan snapshot saldo sebenarnya pada titik waktu onboarding. |
| BR-FIN-05 | Jika pengguna melewati saldo awal, saldo dimulai dari Rp0 **tanpa snapshot**; transaksi historis yang valid dapat mengubah saldo terkini. |
| BR-FIN-06 | Balance Adjustment menerima **target saldo sebenarnya**, bukan hanya delta; proses hanya online dan effective time adjustment menggunakan waktu server saat dikonfirmasi. Target saldo boleh negatif. |
| BR-FIN-07 | Backdate sebelum snapshot mengubah rekonstruksi sejarah dan adjustment delta, tetapi **tidak boleh mengubah target snapshot atau saldo terkini yang terlindungi snapshot** apabila tidak ada pengaruh sesudah snapshot. |
| BR-FIN-08 | Setiap snapshot berikutnya tetap menjadi titik acuan otoritatif; perubahan histori sebelumnya menghitung ulang delta yang terdampak dengan audit terperinci. |
| BR-FIN-09 | Adjustment dan aktivitas piutang tidak dihitung sebagai pemasukan/pengeluaran biasa; hanya dampaknya yang relevan dimasukkan dalam mutasi saldo. |
| BR-FIN-10 | Ledger menjadi sumber kebenaran finansial; materialized balance harus diperbarui atomik dan dapat direkonsiliasi terhadap ledger/snapshot. |
| BR-FIN-11 | Aktivitas finansial akun yang sama diproses terkoordinasi agar transaksi serentak tidak saling menimpa; edit transaksi yang didasarkan pada versi lama ditolak. |
| BR-FIN-12 | Aktivitas dengan effective timestamp identik memakai financial sequence server yang immutable serta validasi dependensi; riwayat tetap deterministik. |
| BR-FIN-13 | Mutasi saldo, piutang, snapshot terkait, audit, dan catatan hasil operasi harus berhasil seluruhnya atau gagal seluruhnya. |
| BR-FIN-14 | Bila mismatch ledger vs materialized balance telah diverifikasi, akun terkait masuk Financial Integrity Freeze hingga perbaikan berwenang berhasil diverifikasi. |

### 6.3 Piutang

| ID | Persyaratan bisnis |
|---|---|
| BR-REC-01 | Satu akun piutang digunakan secara agregat **per profil peminjam**. Dua orang boleh memiliki nama sama; identitas profil tetap berbeda. |
| BR-REC-02 | Nama peminjam wajib; nomor telepon dan catatan opsional. |
| BR-REC-03 | Pinjaman meningkatkan total piutang; pembayaran menguranginya. Keduanya mempunyai histori pada profil peminjam yang sama. |
| BR-REC-04 | Pinjaman secara default mengurangi saldo utama, dan pembayaran secara default menambah saldo utama. Toggle **pengaruh saldo** dapat dimatikan pada setiap aktivitas tanpa menghilangkan efek pada piutang. |
| BR-REC-05 | Piutang tidak boleh negatif pada **titik mana pun** dalam urutan waktu efektif, termasuk setelah edit/delete/restore atau sync transaksi historis. |
| BR-REC-06 | Pembayaran yang melampaui piutang yang tersedia pada kronologi efektif ditolak; operasi ditolak secara utuh, bukan sebagian. |
| BR-REC-07 | Status peminjam/akun piutang dihitung otomatis: **Paid** jika sisa Rp0, **Unpaid** jika sisa lebih dari Rp0. |
| BR-REC-08 | Profil peminjam tetap tersedia setelah lunas. Arsip dilakukan manual dan hanya jika sisa piutang Rp0. |
| BR-REC-09 | Aktivitas baru pada peminjam arsip membutuhkan reaktivasi manual. Koreksi historis yang membuat sisa positif pada profil arsip mengaktifkan kembali profil tersebut dengan audit. |
| BR-REC-10 | Perubahan yang menyebabkan riwayat piutang tidak valid ditolak, disertai penjelasan konflik; pengguna memperbaiki transaksi terkait terlebih dahulu. |
| BR-REC-11 | Penghapusan/piutang diputihkan (*write-off*) tidak termasuk MVP. |

### 6.4 Kategori, riwayat, dan audit

| ID | Persyaratan bisnis |
|---|---|
| BR-HIS-01 | Kategori transaksi bersifat opsional. Sistem menyediakan kategori bawaan serta kategori personal yang dapat dibuat, diedit, diarsipkan, dan dipulihkan. |
| BR-HIS-02 | Kategori arsip tidak dapat dipilih untuk transaksi baru, tetapi tetap melekat pada transaksi historis dan tetap muncul pada laporan historis. |
| BR-HIS-03 | Transaksi tanpa kategori ditampilkan sebagai **Tanpa Kategori** untuk keperluan laporan. |
| BR-HIS-04 | Aktivitas offline baru yang ketika sync merujuk kategori yang sudah diarsipkan ditandai Conflict dan membutuhkan pemilihan kategori aktif atau tanpa kategori; jangan diganti diam-diam. |
| BR-HIS-05 | Transaction History utama mencakup seluruh aktivitas finansial, termasuk piutang yang tidak memengaruhi saldo utama; status pending dan no-balance-impact harus ditandai. |
| BR-HIS-06 | History diurutkan menurut effective timestamp dengan tie-breaker deterministik, sementara Audit History menggunakan waktu aksi. |
| BR-HIS-07 | Transaksi confirmed hanya dapat diedit, dihapus secara logis, atau dipulihkan ketika online dan setelah validasi versi serta aturan finansial. |
| BR-HIS-08 | Recently Deleted tidak kedaluwarsa otomatis; transaksi tetap dapat direstore selama aturan finansial terpenuhi. Penghapusan permanen transaksi finansial tidak disediakan pada MVP. |
| BR-HIS-09 | Alasan penghapusan **opsional**; identitas pelaku, aksi, waktu, dan perubahan data wajib masuk audit. |
| BR-HIS-10 | Audit bersifat **append-only pada level aplikasi**, mencatat kondisi sebelum/sesudah serta perubahan otomatis setiap snapshot yang terdampak dan kaitan dengan operasi pemicu. |
| BR-HIS-11 | Pengguna dapat mencari/memfilter riwayat berdasarkan konten, jenis, kategori, tanggal, nominal, dan status relevan, serta melihat detail bukti. |

### 6.5 PWA, draft, dan sinkronisasi offline

| ID | Persyaratan bisnis |
|---|---|
| BR-OFF-01 | Offline Access **opsional** dan ditawarkan ketika onboarding; pengguna dapat mengaktifkannya kemudian di Settings. |
| BR-OFF-02 | Pengaktifan Offline Access memerlukan login online pertama yang berhasil dan email terverifikasi. |
| BR-OFF-03 | Ketika Offline Access diaktifkan, PIN App Lock **6 digit**, proteksi kunci enkripsi kuat (authenticator kompatibel atau passphrase kuat), dan Recovery Key **wajib**. |
| BR-OFF-04 | **Hybrid Lock:** Soft Lock setelah 5 menit tidak aktif dapat dibuka dengan PIN selama DEK masih tersedia pada sesi aktif; Hard Lock memerlukan pembukaan kunci yang lebih kuat atau Recovery Key. |
| BR-OFF-05 | Browser/aplikasi restart, logout, pergantian akun, atau hilangnya kunci dari memori memicu Hard Lock. |
| BR-OFF-06 | Offline Access harus divalidasi server ulang paling lambat setelah **7 hari**; kedaluwarsa tidak menghapus data pending lokal. |
| BR-OFF-07 | Recovery Key harus benar-benar dapat memulihkan akses ke **data lokal yang masih ada**, bukan sekadar mereset PIN; tidak dapat mengembalikan data browser yang telah terhapus. |
| BR-OFF-08 | Saat Offline Access aktif, pengguna dapat membuat Increase, Deduct, pinjaman, pembayaran piutang, dan profil peminjam baru secara offline. Peminjam baru disinkronkan sebelum aktivitas yang bergantung padanya. |
| BR-OFF-09 | Transaksi pending dapat diedit/dibatalkan sebelum pengiriman; selama status Syncing, perubahan lokal ditahan sampai hasil operasi jelas. |
| BR-OFF-10 | Draft form **tidak** memengaruhi saldo/piutang. Dengan Offline Access aktif, draft tersimpan terenkripsi dan dapat dilanjutkan; tanpa Offline Access, draft hanya dijaga selama sesi aplikasi aktif. |
| BR-OFF-11 | Bounded offline cache boleh membatasi riwayat dan data referensi, tetapi tidak boleh menghapus otomatis draft, pending, atau bukti pending semata-mata akibat batas cache. |
| BR-OFF-12 | Sync menggunakan **Partial Sync**: aktivitas valid diterima otomatis terhadap kondisi server terbaru; konflik dan dependensinya ditahan, sedangkan aktivitas independen tetap diproses. |
| BR-OFF-13 | Pengiriman ulang aktivitas yang sama tidak boleh menghasilkan efek finansial ganda; timeout setelah pengiriman menimbulkan status **hasil belum diketahui** sampai server diperiksa. |
| BR-OFF-14 | Error sementara di-retry maksimal **3 kali per siklus** dengan backoff; konflik bisnis menunggu koreksi pengguna. |
| BR-OFF-15 | Sinkronisasi utama bersifat **foreground-first** saat PWA aktif, unlocked, online, dan sesi valid; Hard Lock menahan sinkronisasi. Background Sync opsional. |
| BR-OFF-16 | Pengguna dapat logout meskipun ada pending setelah peringatan. Pending tetap dilindungi dan hanya terbuka untuk akun asal; tidak boleh dikirim memakai sesi pengguna lain. |
| BR-OFF-17 | Penghapusan data offline secara sengaja diizinkan meski ada pending, dengan konfirmasi ekstra tentang risiko kehilangan data permanen. |
| BR-OFF-18 | UI membedakan saldo terkonfirmasi dengan estimasi lokal. Estimasi menghormati snapshot; bila data cache tidak cukup untuk perhitungan andal, tampilkan bahwa estimasi tidak tersedia. |
| BR-OFF-19 | Offline cache dan lampiran lokal terproteksi; kehilangan storage browser tidak boleh diklaim dapat dipulihkan dengan Recovery Key saja. |

### 6.6 Dashboard, laporan, dan ekspor

| ID | Persyaratan bisnis |
|---|---|
| BR-RPT-01 | Dashboard selalu memperlihatkan **saldo utama saat ini** dan **total piutang saat ini**, terlepas dari periode filter statistik. |
| BR-RPT-02 | Filter statistik dan Reports mendukung harian, mingguan, bulanan, tahunan, dan rentang tanggal custom. |
| BR-RPT-03 | Total pemasukan/pengeluaran tidak mencakup penyaluran/pembayaran piutang maupun balance adjustment. |
| BR-RPT-04 | Reports memiliki kelompok **Income/Expense**, **Balance Movement**, dan **Receivables**, termasuk saldo pembuka/penutup historis sesuai aturan masing-masing. |
| BR-RPT-05 | Grafik MVP meliputi pemasukan vs pengeluaran, pengeluaran menurut kategori, dan tren saldo historis. |
| BR-RPT-06 | Perbandingan periode disertakan: periode berjalan yang belum selesai dibandingkan dengan durasi setara pada periode sebelumnya; periode historis lengkap dibandingkan dengan periode penuh. |
| BR-RPT-07 | Custom range dibandingkan dengan rentang sebelumnya yang sama panjang; jika baseline sebelumnya 0 dan nilai sekarang positif, tampilkan **Baru**; jika keduanya 0, tampilkan **0%**. Label tanggal pembanding harus jelas. |
| BR-RPT-08 | Reports resmi **online-only** dan tidak mencakup pending lokal. Data Dashboard offline yang di-cache harus diberi waktu pembaruan dan label keterbatasan. |
| BR-RPT-09 | Export Reports tersedia dalam **PDF dan Excel**, mencakup ringkasan dan **seluruh detail transaksi sesuai filter**, bukan hanya halaman daftar yang sedang dibuka. |
| BR-RPT-10 | Ekspor mencantumkan waktu pembuatan dan tidak memasukkan binary bukti transaksi. File ekspor hanya dapat diakses pemilik yang sah. |
| BR-RPT-11 | Perhitungan periode dan pengelompokan harian mengikuti zona waktu akun yang sedang aktif; perubahan zona waktu tidak mengubah instant historis dan harus disertai peringatan dampaknya. |

### 6.7 Bukti transaksi dan file

| ID | Persyaratan bisnis |
|---|---|
| BR-FILE-01 | Setiap transaksi dapat memiliki **maksimal satu** lampiran opsional. |
| BR-FILE-02 | Format yang diterima adalah **JPG, PNG, WebP, atau PDF**, dengan ukuran maksimal **10 MB**. |
| BR-FILE-03 | Berkas server disimpan privat; hanya pemilik yang terotorisasi dapat membuka atau mengunduhnya. |
| BR-FILE-04 | Pengunggahan bukti dipisahkan dari financial commit. Kegagalan upload tidak membatalkan transaksi confirmed dan tidak boleh memicu penggandaan transaksi. |
| BR-FILE-05 | Bukti pending yang disimpan offline dilindungi dengan enkripsi lokal; status file dan status transaksi ditampilkan terpisah. |
| BR-FILE-06 | File yang belum lolos validasi keamanan tidak boleh dianggap bukti yang tersedia; proses validasi dan pembersihan file temporer harus disediakan. |

### 6.8 Pengalaman pengguna, aksesibilitas, dan preferensi

| ID | Persyaratan bisnis |
|---|---|
| BR-UX-01 | Desktop memakai sidebar, mobile memakai bottom navigation dengan tombol **+** di tengah untuk Increase, Deduct, Tambah Piutang, dan Terima Pembayaran. |
| BR-UX-02 | Form mobile mendukung pengalaman layar penuh, input nominal yang nyaman, detail opsional, serta penanda status draft/simpan. |
| BR-UX-03 | Pengguna dapat memilih tema **Light, Dark, System**. |
| BR-UX-04 | Sync Center tersedia melalui indikator sinkronisasi; status Pending, Syncing, Synced, Conflict, dan Blocked dibedakan secara jelas. |
| BR-UX-05 | Setelah unlock, pengguna dikembalikan ke halaman sebelumnya jika akses masih diizinkan. |
| BR-UX-06 | PWA menggunakan **Prompt-Based Update**; tidak boleh melakukan reload paksa ketika ada pekerjaan/form aktif tanpa pemeriksaan keamanan draft dan pending. |
| BR-UX-07 | Target aksesibilitas adalah **WCAG 2.2 Level AA** untuk alur utama; warna bukan satu-satunya pembeda status, navigasi keyboard dan pembaca layar diperhatikan. |
| BR-UX-08 | Empty state, loading, offline state, validasi form, serta pesan error harus menjelaskan keadaan sebenarnya dan tindakan berikutnya. |

### 6.9 Operasional, keandalan, dan pemulihan

| ID | Persyaratan bisnis |
|---|---|
| BR-OPS-01 | Deployment MVP menggunakan **Single VPS + Docker Compose**; object storage dan backup berada di luar VPS. |
| BR-OPS-02 | Backup database dilakukan harian dengan kemampuan **Point-in-Time Recovery (PITR)**. |
| BR-OPS-03 | Target awal **RPO maksimal 1 jam** dan **RTO maksimal 4 jam**, keduanya wajib dibuktikan lewat pengujian pemulihan. |
| BR-OPS-04 | Setelah database restore, Financial Recovery Mode menahan mutasi finansial dan sinkronisasi sampai integritas ledger, audit, serta transaksi terkonfirmasi diperiksa. |
| BR-OPS-05 | Controlled Recovery tidak menjanjikan zero data loss atau pemulihan semua transaksi terkonfirmasi apabila bukti durabelnya ikut hilang. |
| BR-OPS-06 | Financial Integrity Freeze hanya dapat diselesaikan dan dibuka oleh operator berwenang melalui verifikasi/perbaikan terkontrol dengan audit. |
| BR-OPS-07 | MySQL-backed persistent jobs dan worker menangani pekerjaan asinkron yang sesuai tanpa keharusan memakai Redis di MVP. |
| BR-OPS-08 | Proses backup, worker, storage, API, kegagalan sync, dan anomali finansial harus dapat dipantau; log teknis tidak memuat rahasia autentikasi atau kunci lokal. |

## 7. Aturan lintas-domain dan batas konsistensi

### 7.1 Klasifikasi aktivitas dan dampak finansial

| Aktivitas | Saldo utama | Total piutang | Income/Expense resmi |
|---|---:|---:|---|
| Increase | Bertambah | Tetap | Income |
| Deduct | Berkurang | Tetap | Expense |
| Pinjaman dengan pengaruh saldo ON | Berkurang | Bertambah | Tidak dihitung |
| Pinjaman dengan pengaruh saldo OFF | Tetap | Bertambah | Tidak dihitung |
| Pembayaran dengan pengaruh saldo ON | Bertambah | Berkurang | Tidak dihitung |
| Pembayaran dengan pengaruh saldo OFF | Tetap | Berkurang | Tidak dihitung |
| Balance Adjustment | Menyesuaikan ke snapshot | Tetap | Tidak dihitung |
| Draft | Tetap | Tetap | Tidak dihitung |
| Pending belum confirmed | Hanya estimasi lokal yang relevan | Hanya estimasi lokal yang relevan | Tidak dihitung dalam laporan resmi |

### 7.2 Invarians yang tidak boleh dilanggar

1. Saldo utama boleh negatif, tetapi **piutang tidak boleh negatif pada setiap langkah kronologis**.
2. Snapshot mempertahankan saldo targetnya ketika aktivitas efektif lebih awal ditambah, diedit, dihapus, atau direstore.
3. Audit dan pengaruh finansial dari satu operasi tidak boleh terpisah akibat commit parsial.
4. Riwayat confirmed tidak boleh ditimpa diam-diam oleh perubahan versi lama.
5. Satu aktivitas offline yang diterima server tidak boleh menghasilkan mutasi finansial ganda ketika retry.
6. Pending tidak otomatis dihitung sebagai pemasukan/pengeluaran resmi.
7. Perubahan zona waktu tidak mengubah effective instant yang telah dicatat.
8. Seluruh perubahan keuangan akun yang sedang berada dalam Financial Integrity Freeze ditahan sesuai kebijakan.

### 7.3 Keterbatasan yang harus disampaikan secara jujur

- Data yang belum tersinkron dapat hilang jika storage browser dihapus atau rusak. Recovery Key tidak menggantikan backup.
- Pencabutan sesi saat perangkat offline tidak menjamin pemblokiran langsung sampai perangkat terhubung kembali; masa offline 7 hari juga bukan pengganti real-time revocation.
- Browser tidak selalu menjamin background execution atau ketahanan storage; sinkronisasi utama dilakukan ketika aplikasi aktif dan unlocked.
- Saldo dan laporan adalah hasil pencatatan pengguna, bukan bukti saldo rekening bank.
- RPO/RTO adalah target operasional, bukan jaminan bahwa setiap transaksi yang pernah dikonfirmasi pasti dapat dipulihkan.

## 8. Perjalanan pengguna utama

### 8.1 Onboarding dan aktivasi offline

Pengunjung mendaftar, memverifikasi email, lalu menentukan saldo awal (termasuk opsi melewati). Offline Access ditawarkan tetapi tidak diwajibkan. Jika dipilih, pengguna mengaktifkan PIN lokal, perlindungan kunci kuat, serta menyimpan dan mengonfirmasi Recovery Key sebelum menikmati akses offline. Instalasi PWA dapat dilakukan kemudian.

### 8.2 Catat transaksi harian

Pengguna membuka Quick Add, memilih Increase/Deduct, mengisi nominal dan informasi opsional, lalu menyimpan. Ketika online dan server mengonfirmasi, saldo confirmed diperbarui. Saat offline dengan akses yang sah, data tersimpan sebagai pending dan dapat memengaruhi estimasi, bukan saldo confirmed.

### 8.3 Kelola piutang

Pengguna membuat/memilih peminjam, mencatat pinjaman atau pembayaran, serta menentukan apakah pergerakan tersebut memengaruhi saldo utama. Riwayat per peminjam, sisa piutang, status Paid/Unpaid, dan riwayat audit tetap tersedia. Tindakan yang akan menyebabkan piutang historis negatif ditolak.

### 8.4 Koreksi transaksi historis

Pengguna mengedit/delete/restore transaksi confirmed ketika online. Server melakukan validasi versi, kronologi piutang, dan rekalkulasi snapshot terdampak secara atomik, lalu menampilkan hasil terbaru. Audit menyimpan rincian perubahan yang relevan.

### 8.5 Offline lalu kembali online

Pengguna membuat beberapa transaksi dan mungkin peminjam baru. Ketika koneksi kembali dan aplikasi unlocked dengan sesi valid, sistem menyinkronkan berdasarkan dependensi. Transaksi valid diproses; konflik dipertahankan lokal dengan penyebab dan tindakan perbaikan yang jelas. Jika respons hilang, aplikasi memeriksa hasil operasi sebelumnya agar tidak mencatat dua kali.

### 8.6 Laporan dan ekspor

Pengguna memilih periode/filter saat online, membandingkan pemasukan/pengeluaran, memeriksa mutasi saldo atau piutang, lalu mengekspor PDF/Excel. Data pending tidak ikut laporan resmi. Perubahan timezone akun dapat mengubah pengelompokan kalender; pengguna mendapat peringatan.

### 8.7 Insiden dan pemulihan

Jika ditemukan anomali saldo, mutasi akun terkait ditahan. Operator berwenang melakukan verifikasi dan perbaikan terkontrol dengan audit. Setelah bencana server, sistem tetap berada dalam Financial Recovery Mode sampai hasil restore dan transaksi yang sebelumnya dikonfirmasi direkonsiliasi.

## 9. Kriteria penerimaan bisnis prioritas

| ID | Skenario penerimaan | Hasil yang harus terjadi |
|---|---|---|
| AC-01 | Pengguna melewati saldo awal lalu mencatat transaksi historis yang valid. | Saldo awal secara efektif Rp0 tanpa snapshot; saldo sekarang berubah sesuai aktivitas. |
| AC-02 | Pengguna mengonfirmasi saldo awal Rp0, kemudian memasukkan transaksi efektif sebelum onboarding. | Target snapshot Rp0 tetap; tidak ada double counting terhadap saldo sekarang. |
| AC-03 | Pengeluaran historis sebelum adjustment diubah. | Delta snapshot terdampak dihitung ulang; target snapshot dan saldo pascasnapshot tetap benar; audit lengkap. |
| AC-04 | Dua request Deduct masuk hampir bersamaan pada akun sama. | Keduanya diproses konsisten dan tidak terjadi lost update. |
| AC-05 | Dua perangkat mengedit versi transaksi yang sama. | Perubahan berbasis versi lama ditolak tanpa menimpa perubahan terbaru. |
| AC-06 | Pinjaman dengan toggle pengaruh saldo OFF dicatat. | Piutang bertambah; saldo utama dan income/expense tidak berubah; history tetap mencatat aktivitas. |
| AC-07 | Pembayaran historis membuat saldo piutang negatif di satu titik. | Operasi ditolak utuh, termasuk pengaruh saldo utama dan audit perubahan yang tidak jadi dilakukan. |
| AC-08 | Peminjam lunas kemudian diarsipkan. | Profil tetap dapat dilihat; aktivitas baru memerlukan reaktivasi; koreksi yang membuat sisa positif mengaktifkan kembali profil. |
| AC-09 | Kategori yang dipakai transaksi lama diarsipkan. | Kategori lama tetap melekat pada history/report; tidak dapat dipilih pada transaksi baru. |
| AC-10 | Pending offline memakai kategori yang kemudian diarsipkan di perangkat lain. | Sync menandai Conflict; pengguna memperbaiki kategori tanpa perubahan diam-diam. |
| AC-11 | Pengguna membuat transaksi dengan effective time di masa depan. | Server menolak transaksi dan menjelaskan kesalahan waktu. |
| AC-12 | Pengguna menutup form dengan Offline Access aktif. | Draft terenkripsi dapat dilanjutkan setelah Hard Unlock dan tidak memengaruhi saldo. |
| AC-13 | Pengguna tanpa Offline Access keluar dari sesi aplikasi. | Draft hanya dijanjikan selama sesi aktif; tidak ada klaim pemulihan persisten. |
| AC-14 | Server berhasil commit tetapi respons sync hilang. | Retry/status check mengembalikan hasil sebelumnya; hanya satu mutasi finansial yang tercatat. |
| AC-15 | Satu dari beberapa transaksi offline konflik. | Aktivitas valid dan independen tetap synced; konflik serta dependensinya tertahan. |
| AC-16 | User logout atau berganti akun saat mempunyai pending. | Peringatan tampil, pending tetap dilindungi, dan tidak terlihat/tersinkron lewat akun lain. |
| AC-17 | Pengguna lupa PIN tetapi memiliki Recovery Key dan data lokal masih ada. | Akses ke data terenkripsi dapat dipulihkan melalui jalur sah, tanpa menghapus pending. |
| AC-18 | Hard Lock setelah restart browser. | PIN saja tidak cukup; memerlukan authenticator kompatibel, passphrase kuat, atau Recovery Key. |
| AC-19 | Offline Access melewati tujuh hari tanpa validasi server. | Aktivitas offline dikunci sampai validasi online, pending tidak dihapus. |
| AC-20 | Reports dibuka offline. | Halaman menjelaskan kebutuhan koneksi; tidak menampilkan laporan parsial sebagai laporan resmi. |
| AC-21 | Bukti gagal diunggah setelah financial commit berhasil. | Transaksi tetap confirmed; bukti memiliki status gagal/pending yang dapat diperbaiki. |
| AC-22 | Ledger dan materialized balance terbukti berbeda. | Mutasi akun dibekukan; hanya operator berwenang dapat melakukan pemulihan terverifikasi dengan audit. |
| AC-23 | Database dipulihkan dari backup/PITR. | Mutasi dan sync ditahan sampai rekonsiliasi dan verifikasi operator diselesaikan. |
| AC-24 | PWA memperoleh versi baru saat draft/pending ada. | Tidak ada reload paksa; data lokal tetap aman atau update ditunda dengan alasan jelas. |
| AC-25 | Account timezone diganti. | Instant transaksi tidak berubah; grup tanggal laporan menyesuaikan zona waktu baru dengan peringatan. |

## 10. Persyaratan nonfungsional dan release gates

### 10.1 Keamanan dan privasi

- Auth dan otorisasi server wajib berlaku pada setiap sumber data finansial; pengguna tidak dapat mengakses sumber milik orang lain melalui ID atau URL.
- Browser menyimpan data offline sensitif dalam bentuk terenkripsi; PIN 6 digit sendiri **tidak** menjadi satu-satunya pelindung kunci enkripsi.
- Recovery Key harus diuji benar-benar dapat membuka data terenkripsi, dengan fallback passphrase ketika authenticator/PRF tidak didukung.
- Upload bukti harus privat, divalidasi, dan hanya dapat dibaca pihak berwenang.
- Session revocation, logout, perubahan akun, serta siklus hidup lock tidak boleh mengungkap data pengguna lain.

### 10.2 Keandalan dan konsistensi

- Tidak ada *known critical defect* pada invarians ledger, piutang, snapshot, idempotency, atau isolasi akun ketika rilis.
- Konflik/timeout tidak boleh disamakan dengan kegagalan commit yang sudah diketahui.
- Setiap pengubahan finansial atomik dan dapat diaudit; materialized balance dapat diverifikasi dari ledger.
- Pekerjaan background harus persisten dan aman terhadap restart/retry sesuai jenis pekerjaannya.

### 10.3 Aksesibilitas dan kompatibilitas

- Target **WCAG 2.2 AA** untuk alur utama; dukungan keyboard, screen reader, dan interaksi mobile merupakan bagian kriteria penerimaan.
- Pengalaman diuji pada browser desktop modern, Android PWA, dan iOS Home Screen Web App; fitur authenticator hanya digunakan jika benar-benar didukung.
- Bila kemampuan kriptografi perangkat tidak tersedia, fallback passphrase kuat harus tetap dapat digunakan.

### 10.4 Pengujian pemulihan

- Backup harian, off-VPS PITR, serta alur Financial Recovery Mode diuji dalam *restore drill*.
- Target RPO ≤1 jam dan RTO ≤4 jam harus **diukur dan dinyatakan sebagai target**, bukan jaminan tanpa pengujian.
- Transaksi yang pernah terkonfirmasi tetapi hilang akibat titik pemulihan tidak boleh direplay otomatis tanpa rekonsiliasi yang sah.

## 11. Ketergantungan, risiko, dan keputusan untuk spesifikasi lanjutan

| Topik | Risiko/ketergantungan | Penanganan yang disepakati atau arah lanjut |
|---|---|---|
| Perlindungan kunci PWA | Dukungan WebAuthn PRF tidak seragam. | Uji kompatibilitas; authenticator jika didukung, fallback passphrase kuat dan Recovery Key wajib. |
| Penyimpanan lokal browser | Storage dapat dibersihkan/korup. | Hindari klaim backup, tampilkan peringatan dan mekanisme penghapusan sadar risiko. |
| Timestamp offline | Jam perangkat mungkin tidak akurat. | Validasi ulang di server; effective time tidak diganti otomatis; konflik dijelaskan. |
| Snapshot dan backdate | Delta adjustment dapat berubah setelah koreksi. | Validasi kronologis, rekalkulasi atomik, detailed audit. |
| Sync dan retry | Timeout/respons hilang dapat menyebabkan status tak pasti. | Identitas operasi stabil, idempotency, status check, retry terbatas. |
| Recovery database | Binlog terbaru dapat hilang pada bencana. | Controlled Recovery, RPO/RTO yang diuji, verifikasi operator, tanpa janji zero loss. |
| Pengelolaan operator | Financial Freeze perlu jalur perbaikan sah. | Prosedur operator berotorisasi; detail implementasi diselesaikan dalam Technical Specification. |
| Volume ekspor dan job | File besar/job berulang dapat membebani VPS tunggal. | MySQL-backed worker persisten, pengelolaan kapasitas dan status pekerjaan. |

**Detail yang sengaja belum dijadikan kebijakan bisnis baru:** masa retensi file export sementara; batas data cache numerik; aturan pembatasan kapasitas upload simultan; durasi access token pendek yang spesifik; batas nominal maksimal yang lebih sempit dari representasi integer aman; jenis notifikasi operator; format final response API. Detail-detail itu dapat ditentukan pada PRD/Technical Specification melalui default yang aman, tanpa mengubah aturan bisnis.

## 12. Tata kelola perubahan dan kesiapan tahap berikutnya

1. **Baseline BRD:** seluruh keputusan ruang lingkup di atas digunakan sebagai sumber kebutuhan bisnis untuk PRD dan spesifikasi teknis. BRD versi ini masih memerlukan tinjauan agar kesalahan perumusan dapat dikoreksi, **bukan** membuka kembali scope tanpa alasan.
2. **Traceability:** identitas BR- dan AC- dipertahankan di PRD, Technical Specification, test matrix, dan instruksi AI Coding Agent.
3. **Definition of Done:** suatu kemampuan dinyatakan selesai hanya jika alur utama, validasi, kondisi gagal, keamanan relevan, dan pengujian penerimaan terpenuhi.
4. **Scope changes:** usulan fitur di luar MVP ditempatkan dalam backlog Post-MVP dan memerlukan persetujuan eksplisit untuk masuk cakupan.
5. **Feasibility gates sebelum implementasi penuh:** uji enkripsi/recovery offline, konkurensi/snapshot/ledger, dan pemulihan database/sinkronisasi tanpa duplikasi.

### 12.1 Status persetujuan

| Item | Status |
|---|---|
| MVP scope | Disepakati dan dibekukan pada tahap diskusi |
| Keputusan bisnis/arsitektur yang dirujuk | Telah ditetapkan pada diskusi sebelumnya |
| BRD v0.1 sebagai teks dokumen | Draft baseline untuk ditinjau; belum ditandatangani/disetujui secara formal |
| PRD, Technical Specification, AGENTS.md | Belum disusun dalam tahap ini |

---

**Akhir BRD v0.1 — Duit Log MVP.**
