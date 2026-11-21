# Fase 0 Duit Log

Eksperimen ini memakai data sintetis pada Windows. Perintah dijalankan dari direktori Duit Log. Skrip browser memakai profil sementara. Skrip MySQL membuat dua direktori data baru dan named pipe unik. Mode Prisma menambahkan listener pada loopback dan akun uji dengan hak terbatas. Hentikan server PRF manual dengan Ctrl+C setelah pengujian.

Pengujian pada 21 November 2026 menyelesaikan jalur lokal di bawah. Exit gate Fase 0 masih terbuka karena PRF belum didemonstrasikan pada authenticator fisik dan restore belum diuji dengan arsip off-VPS.

Baseline backend saat ini adalah Rust, Axum, Tokio, dan SQLx. Bukti IndexedDB, perilaku InnoDB, dan PITR lokal tetap relevan untuk v0.2. Replay JavaScript mendokumentasikan kasus uji yang dapat diulang dalam Rust. Percobaan Prisma disimpan sebagai catatan historis untuk baseline sebelumnya. [Spesifikasi teknis v0.2 Rust](../../docs/Duit_Log_MVP_Technical_Specification_v0.2_Rust.md).

## VAL-01 — Enkripsi dan pemulihan offline

| Perintah | Hasil |
| --- | --- |
| `python experiments/phase0/browser_probe.py 'C:\Program Files\Google\Chrome\Application\chrome.exe'` | Chrome 157.0.8103.80. PBKDF2 182 ms. |
| `python experiments/phase0/browser_probe.py 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'` | Edge 157.0.4341.60. PBKDF2 240 ms. |
| `python experiments/phase0/browser_probe.py --manual-prf` | Probe tersedia untuk browser dan authenticator fisik. Buka `http://localhost:8765/prf` di profil uji Chrome atau Edge. Pilih **Enroll test credential**, tutup browser, buka kembali URL pada profil yang sama, lalu pilih **Verify after restart**. Catat model authenticator, browser, OS, dan hasilnya. |

WebAuthn menerima `localhost` sebagai domain relying party untuk uji HTTP lokal. Skrip mengarahkan URL loopback berbentuk IP ke `localhost` untuk halaman PRF. [Panduan origin WebAuthn Chromium](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/content/browser/webauth/origins.md).

Probe membedakan **PRF disabled** (`enabled: false`) dari **PRF result unavailable** (browser tidak mengembalikan status). Jika muncul salah satunya, catat browser, OS, dan authenticator yang dipilih. Uji kombinasi lain apabila tersedia. Kombinasi yang gagal menggunakan jalur passphrase kuat dan Recovery Key. PRF baru terverifikasi setelah **Verify after restart** berhasil membuka ciphertext. [Spesifikasi ekstensi PRF WebAuthn](https://www.w3.org/TR/webauthn-3/#prf-extension).

Hasil manual yang dilaporkan pengguna pada 21 November 2026 adalah **PRF disabled (platform)**. Pendaftaran mengembalikan `enabled: false` untuk kredensial pada authenticator bawaan. Nama dan versi browser, versi OS, serta model authenticator belum tercatat. Pengujian berhenti pada pendaftaran sehingga verifikasi PRF setelah restart belum dijalankan untuk kombinasi ini. Jalur passphrase kuat dan Recovery Key telah lulus uji browser lokal di bawah.

Kedua browser headless menyimpan draft, pending dan lampiran sintetis di IndexedDB. Transaksi overwrite yang sengaja dibatalkan mempertahankan data sebelumnya. Proses browser kedua memulihkan ketiga record dengan passphrase dan Recovery Key secara terpisah. Percobaan PIN saja, Recovery Key salah, konteks akun lain, dan ciphertext rusak ditolak.

Probe mencoba PBKDF2-HMAC-SHA-256 dengan 600.000 iterasi, salt acak 16 byte, AES-256-GCM, nonce acak 12 byte, dan konteks autentikasi yang mengikat perangkat, akun, tipe record, identitas record, serta versi skema. DEK dihasilkan secara acak. IndexedDB hanya menyimpan ciphertext, parameter, dan wrapped DEK. Passphrase dan Recovery Key fixture sudah diketahui kedua proses uji supaya restart dapat diulang. Parameter KDF masih perlu diukur pada perangkat target sebelum dipilih untuk aplikasi.

Jejak spesifikasi BR-OFF-03–07, BR-OFF-19, PR-SEC-02–06, PR-SEC-10, PR-TXN-06, dan AC-12/17/18. Uji ini membuktikan jalur kriptografi dan penyimpanan fixture. Alur aplikasi Hybrid Lock, validasi tujuh hari, isolasi antarsesi, storage quota nyata, PRF fisik, dan browser/perangkat target masih perlu dibuktikan.

## VAL-02 — Lock, replay, dan persistensi finansial

| Perintah | Pemeriksaan |
| --- | --- |
| `node experiments/phase0/replay_probe.mjs` | Rp0 eksplisit versus lewati, dua target snapshot, edit historis, tie sequence, prefix piutang per profil, pinjaman cash-off, dan overflow signed 64-bit. |
| `python experiments/phase0/mysql_probe.py` | MySQL 8.0.30, dua debit paralel satu akun, lock timeout 1205, deadlock 1213, rollback, query plan, dan restore. |
| `python experiments/phase0/mysql_probe.py --sqlx` | Lulus. Instance loopback membuat akun uji dengan hak tabel minimum serta CA sementara. Harness mengisi `DATABASE_URL` hanya untuk `cargo run --locked` sehingga SQLx memeriksa query lock saat kompilasi terhadap skema uji nyata. |
| `python experiments/phase0/mysql_probe.py --prisma` | Uji historis Prisma 6.19.3 untuk transaksi interaktif, presisi `BIGINT`, dan rollback. Memerlukan Node.js dan akses registry npm untuk instalasi sementara. |

Pada Node.js 24.21.0, satu pengukuran replay in-memory memberi 0,9 ms untuk 1.000 event, 3,9 ms untuk 10.000 event dan 36,4 ms untuk 100.000 event. Waktu ini hanya mencakup pengurutan dan replay di memori. Di MySQL, dengan 10.000 event milik akun lain, query urutan kronologis memakai indeks `PRIMARY` tanpa filesort. Lock timeout membatalkan transaksi saat klien uji berhenti, dan InnoDB memilih satu korban deadlock. Dua debit menghasilkan saldo –30, tiga baris aktivitas termasuk snapshot, dua audit, dan dua hasil operasi. Percobaan dengan identitas duplikat gagal secara atomik. Batas retry, status operasi aplikasi, beban I/O di bawah lock, dan indeks per peminjam belum diukur.

### Hasil SQLx v0.2

- Rust 1.95.0, SQLx 0.9.0, Tokio 1.54.1, dan MySQL 8.0.30. Paket dipatok untuk probe. Dua debit paralel menghasilkan saldo `9007199254740963`, sequence 1 dan 2, serta tepat dua aktivitas, audit, dan hasil operasi. Mengulang attempt identik mengembalikan sequence awal. Attempt dengan nominal berbeda ditolak.
- `REPEATABLE READ` mempertahankan snapshot yang dibuat oleh read biasa sebelum lock, bahkan setelah `SELECT ... FOR UPDATE` membaca state yang lebih baru. Pada skenario yang sama, read berikutnya di `READ COMMITTED` melihat aktivitas baru. Probe debit mengambil lock sebelum read biasa. Isolation level aplikasi masih keputusan terbuka. [MySQL InnoDB consistent reads](https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html).
- Lock timeout 1205, pembatalan future yang menunggu lock, deadlock 1213, dan duplicate audit 1062 tidak meninggalkan perubahan parsial. Debit akun lain dapat selesai selama lock pertama dipegang. Retry setelah rollback memakai attempt yang sama. Probe membatalkan transaksi setelah timeout klien dan memeriksa hasil setelah koneksi dapat dipakai lagi.
- Query kronologis untuk akun kecil memakai `PRIMARY` tanpa filesort. Pembacaan dan validasi 10.000 baris terurut via SQLx memerlukan 44,64 ms. Replay Rust in-memory pada build debug memerlukan 0,58 / 6,87 / 117,51 ms untuk 1.000 / 10.000 / 100.000 event. Pengukuran ini tidak mencakup beban produksi atau replay di bawah lock. Indeks piutang belum diuji pada skema final.
- Query lock lolos verifikasi kompilasi dengan database uji aktif. Metadata SQLx offline dan verifikasi query skema aplikasi masih perlu ditentukan. `cargo fmt --check --manifest-path experiments/phase0/sqlx-probe/Cargo.toml` lulus. Audit OSV menemukan advisory untuk `libsqlite3-sys` dan `rustix` di lockfile. Keduanya berada di luar graf build Windows yang diuji. [Advisory libsqlite3-sys](https://rustsec.org/advisories/RUSTSEC-2026-0459.html) · [Advisory rustix](https://rustsec.org/advisories/RUSTSEC-2026-0486.html).

Probe historis Prisma lulus. Instalasi sementara dipatok pada 6.19.3 untuk CLI dan Client. `npm audit --json` melaporkan tingkat tinggi pada `prisma`, `@prisma/config`, `deepmerge-ts`, dan `effect`.

Jejak spesifikasi BR-FIN-04–08, BR-FIN-10–13, BR-REC-01/04/05, BR-OFF-13, PR-BAL-01/04/06, PR-NFR-02/03, dan AC-01–04/06/07/14. Pemeriksaan AC-14 terbatas pada penolakan duplikat dan atomicity tabel hasil operasi. Belum ada API untuk mengambil hasil sebelumnya.

## VAL-03 — PITR lokal

Probe MySQL membuat dump konsisten dengan koordinat binlog, mencatat debit lanjutan, merotasi binlog, lalu mencatat debit berikutnya di file yang sengaja tidak disalin. Skrip memeriksa SHA-256 salinan lokal dan checksum binlog, kemudian memulihkan dump dan menerapkan rentang event berposisi dalam instance baru. Pemulihan memeriksa aktivitas, saldo, snapshot, audit, dan hasil operasi. [Manual MySQL tentang pemulihan berdasarkan posisi event](https://dev.mysql.com/doc/refman/8.0/en/point-in-time-recovery-positions.html).

Pada uji lengkap dengan Prisma, restore dan pemeriksaan data selesai dalam 7,72 detik dengan rentang `probe-bin.000001:297721..298419`. Saldo pada backup –30 menjadi –35 setelah binlog diterapkan. Saldo pada sumber sempat mencapai –42, tetapi debit terakhir dan hasil operasinya tidak ditemukan di database hasil restore karena binlog lanjutannya tidak disalin. Skrip tidak memutar ulang operasi yang hilang. Pengukuran lokal mencakup startup instance restore, pemulihan dan pemeriksaan data sintetis.

Uji ulang sesudah probe SQLx lulus dan menyelesaikan restore lokal dalam 5,73 detik dengan rentang `probe-bin.000001:301951..302649`.

### Drill arsip terenkripsi

`python -B experiments/phase0/pitr_archive_probe.py` menggunakan MySQL 8.0.30 dan `cryptography==50.0.2` yang sudah tersedia. `--archive-dir` menerima direktori yang sudah ada, misalnya mount staging terpisah yang telah disetujui. Skrip membuat subdirektori uji unik. Seluruh data berasal dari fixture dan seluruh instance bersifat sementara.

Skrip membuat backup konsisten dan dua binlog tertutup, lalu menyimpan masing-masing bersama manifest sebagai AES-256-GCM. Nama arsip dan jenis file terikat pada tag autentikasi. Kunci acak hanya hidup selama satu eksekusi probe. Direktori data instance sumber sintetis dihapus sebelum restore. Restore menolak segmen yang hilang, rusak atau tertukar, serta kunci yang salah. Replay memvalidasi checksum MySQL dan berhenti di posisi commit terakhir dalam arsip. [MySQL PITR berdasarkan posisi event](https://dev.mysql.com/doc/refman/8.0/en/point-in-time-recovery-positions.html) · [Dokumentasi AES-GCM](https://cryptography.io/en/stable/hazmat/primitives/aead/).

Saldo pulih ke 62 dari dua snapshot bertarget 100 dan 70, piutang pulih ke 20, dan empat pasangan audit/hasil operasi cocok dengan ledger. Debit terakhir sebesar 7 sudah dikonfirmasi pada sumber, tetapi berada dalam binlog ketiga yang belum diarsipkan. Debit itu tetap hilang setelah restore. Database hasil restore memakai named pipe lokal dengan TCP dinonaktifkan, dan harness memverifikasi kondisi tersebut.

Drill pertama mencatat 0,18 detik dari commit terakhir yang bisa dipulihkan sampai arsip siap, celah pemulihan sintetis 0,28 detik, dan 9,73 detik dari simulasi insiden hingga verifikasi. Uji ulang dengan `--archive-dir` menunjuk direktori lokal terpisah dan selesai dalam 12,64 detik. Direktori tersebut berisi tepat empat berkas terenkripsi. Kedua pengujian memulihkan `probe-bin.000001:4155` sampai `probe-bin.000002:857`. Audit OSV untuk `cryptography 50.0.2`, `cffi 2.1.1`, dan `pycparser 3.12` tidak mengembalikan advisory saat diuji.

Jejak spesifikasi BR-OPS-01–06, PR-NFR-06/07, dan AC-23. Untuk menyelesaikan gate diperlukan arsip binlog off-VPS yang benar-benar berjalan, uji restore sampai sign-off operator, serta bukti bahwa global hold memblokir mutasi dan sync. RPO dan RTO operasional memerlukan pengukuran di lingkungan target.

### Drill staging Biznet Gio

Perintah berikut lulus pada 21 November 2026. Profil berasal dari konfigurasi lokal Boto3. Drill membuat subprefix unik, mengunggah empat objek AES-256-GCM, menghapus direktori data sumber sintetis, lalu membaca kembali arsip dari Biznet Gio untuk restore ke instance MySQL baru. [Profil Boto3](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html#shared-credentials-file).

```powershell
python -B experiments/phase0/pitr_archive_probe.py --s3-endpoint https://nos.wjv-1.neo.id --s3-bucket uitog-ucker --s3-prefix staging/duitlog-pitr/ --s3-profile duitlog-pitr --s3-region idn
```

| Bukti | Hasil |
| --- | --- |
| Lokasi objek | `s3://uitog-ucker/staging/duitlog-pitr/duit-drill-dedf78528cb24db58a5d2fed9cd3f0f3/` |
| Objek terverifikasi | `backup.sql.aead` (6.228 byte), `probe-bin.000001.aead` (4.930 byte), `probe-bin.000002.aead` (932 byte), `manifest.aead` (294 byte) |
| Akses | `HEAD` dengan profil uji berhasil. `GET` tanpa kredensial ditolak dengan HTTP 403 untuk keempat objek. |
| Titik pemulihan | `probe-bin.000001:4155` hingga `probe-bin.000002:857`, tercatat pada 16:07:37 UTC+7. |
| Integritas | Saldo 62, dua snapshot, piutang 20, dan empat pasangan audit/hasil operasi cocok. Debit terkonfirmasi di binlog yang belum tersalin tidak diputar ulang. |
| Waktu fixture | 0,28 detik dari commit terakhir yang bisa dipulihkan sampai arsip siap, 0,38 detik celah pemulihan sintetis, dan 8,06 detik dari insiden sintetis hingga verifikasi. |

Objek terenkripsi tetap tersimpan di bucket. Kunci sementara hanya tersedia selama run. Uji ini memakai satu profil untuk upload dan restore serta satu host untuk koordinasi. Bukti ini menunjukkan round-trip ke arsip off-host. Penyimpanan kunci lintas host, pemisahan IAM, jadwal dan kontinuitas arsip, retensi, referensi object storage, global hold API/sync, serta RPO/RTO operasional masih terbuka.

## VAL-04 — Build dan penggunaan sumber daya Rust

Probe lokal menjalankan image release Linux amd64 dengan Rust 1.95.0, Axum 0.8.9, SQLx 0.9.0 dan worker Tokio 1.54.1. Dockerfile memakai build multi-stage, base image dipatok dengan digest, dan API serta worker berjalan sebagai pengguna non-root. Pengujian memakai MySQL 8.4.13 di jaringan proyek Docker khusus dengan batas kontainer 1.024 MiB untuk MySQL serta 256 MiB masing-masing untuk API dan worker. Swap dinonaktifkan pada ketiga kontainer.

```powershell
docker build --tag duit-phase0-resource:val04 --file experiments/phase0/resource-probe/Dockerfile experiments/phase0/resource-probe
python -B experiments/phase0/resource-probe/run_probe.py
cargo fmt --check --manifest-path experiments/phase0/resource-probe/Cargo.toml
```

API memakai pool maksimum empat koneksi dan worker satu. Delapan klien membuat request laporan sintetis. Worker membaca batch 1.000 baris dengan urutan sequence dan memakai kanal berkapasitas dua batch. Penulisan XLSX memakai mode constant-memory pada task blocking. SQLx mengembalikan koneksi ke pool di antara pengambilan batch dan penulisan file. Nominal ditulis sebagai string desimal agar Excel mempertahankan nilai di atas rentang integer aman. Harness membaca ulang seluruh bagian worksheet dan memeriksa urutan, presisi nominal, jumlah baris, serta bahwa baris milik akun lain tidak ikut diekspor. [Mode constant-memory rust_xlsxwriter](https://docs.rs/rust_xlsxwriter/0.103.0/rust_xlsxwriter/performance/index.html).

| Kontainer | Memori idle setelah seed | Puncak memori sejak kontainer mulai | Batas |
| --- | ---: | ---: | ---: |
| MySQL | 481,0 MiB | 496,5 MiB | 1.024 MiB |
| API | 5,2 MiB | 13,2 MiB | 256 MiB |
| Worker | 4,7 MiB | 23,4 MiB | 256 MiB |

Pengukuran memakai cgroup v2 dan mencakup cache yang dibebankan ke kontainer. Ketiga kontainer mencatat nol OOM kill. API memberi 399 respons valid dalam tiga detik dengan p95 92,02 ms. Selama jendela pengujian ekspor, API memberi 201 respons valid dengan p95 90,64 ms. File XLSX 150.000 baris siap terdeteksi dalam 1,83 detik dan berukuran 1.931.419 byte. Ini hasil satu uji lokal pada Docker Desktop dengan batas memori kontainer. Waktu deteksi ekspor mencakup pemicu dan polling harness.

Build dengan digest terkunci, pengukuran, dan pemeriksaan format Rust lulus. Runtime image berukuran sekitar 89,6 MB menurut `docker image inspect`. Audit OSV memeriksa 172 crate di lockfile, termasuk 146 di graf Linux, dan tidak mengembalikan advisory pada saat uji. Paket OS di image belum diaudit. Harness membersihkan kontainer dan volume untuk proyek uji setelah selesai.

Jejak spesifikasi BR-RPT-09, BR-OPS-07 dan PR-RPT-07. Eksperimen menguji kelengkapan baris dan tekanan memori Excel pada data sintetis yang tidak berubah saat ekspor. PDF, konsistensi saat transaksi berubah, job durabel, kontrol akses, backup/recovery bersamaan, dan RAM host VPS 2 GB masih perlu diuji untuk aplikasi dan lingkungan target.
