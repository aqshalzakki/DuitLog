# Fase 1 · Kontrak autentikasi

Kontrak Fase 1 mengikuti BR-AUTH-01–08, PR-AUTH-01–08, PR-SEC-09, PR-SET-03 dan PR-NFR-01. Acceptance terkait tercantum di PRD §4.3. Onboarding saldo, mutasi keuangan, penyimpanan offline dan sinkronisasi mengikuti fase masing-masing.

| Method dan path di `/api/v1` | Input dan hasil |
| --- | --- |
| POST /auth/register | `name`, `email`, `password`. Respons 202 sama untuk email baru dan terdaftar. Sesi awal dibuat melalui login sebelum memasukkan kode verifikasi. |
| POST /auth/login | `email`, `password`, opsional `deviceName`. 204 dan cookie sesi. Ambil profil melalui `GET /me`. |
| POST /auth/verify-email | `token`, sesi aktif, token terikat pemilik. |
| POST /auth/resend-verification | Sesi aktif. |
| POST /auth/forgot-password | `email`. Respons 202 sama untuk email dikenal dan tidak dikenal. |
| POST /auth/reset-password | `token`, `password`. Reset mencabut seluruh sesi akun target. |
| POST /auth/refresh | Cookie refresh. Rotasi mengganti kedua cookie dalam satu transaksi. Refresh yang sudah dipakai mencabut sesi perangkat. |
| POST /auth/logout | Cabut sesi perangkat ini dan hapus cookie. |
| POST /auth/logout-all | Cabut sesi akun dan hapus cookie. |
| GET /me | Profil dari sesi akses. |
| GET /sessions | Daftar perangkat milik sesi aktif. |
| DELETE /sessions/{id} | Cabut perangkat berdasarkan ID dan pemilik sesi. 404 untuk ID asing atau tidak tersedia. |
| GET /account/verified | Probe capability terlindungi untuk Fase 1. 403 sebelum verifikasi email. |

API memakai JSON camelCase, error `code`, `message`, `requestId` dan `fieldErrors` saat validasi gagal. Semua request mutasi membawa `Origin` yang sama dengan origin aplikasi dan header `X-Duit-CSRF: 1`. Cookie akses dan refresh bersifat HttpOnly, Secure dan SameSite Strict. Token email berupa kode yang dimasukkan pada halaman aplikasi. Ketentuan 30 hari absolut mengikuti BR-AUTH-06. Nilai timeout, validasi input dan rate limit di implementasi ini adalah pilihan Fase 1 untuk uji lokal.

## Menjalankan di pengembangan lokal

**Cara cepat untuk mencoba di browser:** `python tests/dev_local.py`. Skrip ini menjalankan:
- MySQL pribadi di `.dev-local/` pada `127.0.0.1:3307` (data bertahan antar-run; `--reset` mengosongkan);
- relay SMTP palsu yang mencetak kode verifikasi/reset ke terminal dan `.dev-local/mail.log`;
- migrasi, API, worker, dan Vite di `http://localhost:5173`.

Ctrl+C menghentikan semuanya. Kalau jendela terminal ditutup paksa, proses anak (mysqld, api, worker, node) bisa tertinggal dan memegang port 3307/3000/5173; hentikan proses itu dulu sebelum menjalankan ulang. `--smoke` adalah cek mandiri: mendaftarkan satu akun, menunggu kodenya, lalu berhenti. Hanya untuk pengembangan: root MySQL di folder ini tanpa kata sandi.

Siapkan MySQL khusus pengembangan dan relay SMTP uji lokal. Masukkan nilai konfigurasi berikut sebagai environment variable untuk proses terkait.

| Variable | Nilai lokal atau fungsi |
| --- | --- |
| `DATABASE_URL` | DSN MySQL khusus pengembangan. Jalankan migrasi dengan akun yang memiliki izin skema. API dan worker dapat menggunakan akun runtime terpisah. |
| `DUIT_APP_ORIGIN` | `http://localhost:5173`. Buka Vue dengan origin ini. |
| `DUIT_API_ADDR` | Default `127.0.0.1:3000`. Vite memakai proxy ke alamat ini. |
| `DUIT_MAIL_KEY` | 32 byte acak dalam Base64url tanpa padding. Pakai nilai yang sama untuk API dan worker. Simpan melalui konfigurasi lokal yang terlindungi. |
| `DUIT_MAIL_FROM` | Alamat pengirim untuk worker. |
| `DUIT_SMTP_MODE`, `DUIT_SMTP_HOST`, `DUIT_SMTP_PORT` | Mode `local` memakai `127.0.0.1:1025`. Untuk relay nyata, worker meminta STARTTLS serta `DUIT_SMTP_USERNAME` dan `DUIT_SMTP_PASSWORD`. |

```powershell
cargo run --locked --bin api -- migrate
cargo run --locked --bin api
cargo run --locked --bin worker
npm.cmd ci --prefix frontend
npm.cmd run dev --prefix frontend
```

Jalankan API, worker, dan Vite di terminal terpisah dengan konfigurasi proses yang sesuai. Migrasi dijalankan secara eksplisit. API menggunakan maksimum empat koneksi dan worker satu. Akses berlangsung 15 menit dengan refresh terikat tenggat 30 hari dari login awal. Request login dan reset dibatasi per koneksi sumber dan alamat. Saat berada di belakang reverse proxy, batas per IP sementara memakai alamat proxy sampai ada konfigurasi trusted-proxy yang diverifikasi.

Argon2id berjalan dalam task blocking dengan dua slot. Token sesi hanya tersimpan sebagai SHA-256. Worker menurunkan kode email dari kunci HMAC dan ID challenge. Pendaftaran dan permintaan pemulihan menyimpan challenge serta job dalam satu transaksi MySQL. Perubahan kata sandi mengonsumsi challenge dan mencabut semua sesi dalam transaksi yang sama. Query refresh, reset, dan pencabutan perangkat memakai satu transaksi SQLx dan mengunci akun sebelum memperbarui sesi. Lease job dan Message-ID yang stabil membantu retry. Jika relay menerima pesan sebelum worker sempat mencatat sukses, retry dapat mengirim email yang sama dengan kode yang sama.

## Verifikasi

`cargo build --locked`, `cargo fmt --all -- --check`, dan `npm.cmd run build --prefix frontend` memeriksa build serta format. Uji lokal berikut memakai instance MySQL 8.x Windows sementara, relay SMTP sintetis, Postman lokal bila tersedia, dan Chrome opsional. Browser E2E memakai modul Python `websocket-client` yang sudah terpasang.

```powershell
python -B tests/phase1_auth.py --browser 'C:\Program Files\Google\Chrome\Application\chrome.exe'
```

Suite memakai acceptance PRD §4.3 untuk pengujian sesi belum terverifikasi, tenggat absolut, pencabutan perangkat, dan error aman. Cakupan browser berfokus pada alur autentikasi, label, keyboard, dan viewport kecil. Audit WCAG 2.2 AA menyeluruh, pengiriman SMTP eksternal, reverse proxy produksi, serta seluruh kasus offline/financial/sync menunggu pekerjaan di fase terkait.

| Pemeriksaan | Hasil lokal |
| --- | --- |
| `cargo build --locked` dan `cargo fmt --all -- --check` | Lulus di Windows. |
| `cargo clippy --locked --offline --all-targets -- -D warnings` | Lulus. |
| `cargo check --locked` dalam image Rust 1.95 Linux amd64 | Lulus. |
| `npm.cmd run build --prefix frontend` | Typecheck dan build Vite lulus. Instalasi lockfile melaporkan nol vulnerability npm. |
| `python -B tests/phase1_auth.py --browser …` | Lulus. Migrasi idempoten saat dijalankan ulang. Uji mencakup CSRF, cookie, email sekali pakai dan kedaluwarsa, retry SMTP sementara, pemilik perangkat, batas 30 hari, refresh paralel dan reuse, serta pencabutan setelah reset. Postman memverifikasi health check dan Chrome menguji register, login, verifikasi, reload, dan logout di viewport kecil. |

Audit OSV memeriksa 210 crate pada lockfile. Satu advisory menyangkut `libsqlite3-sys` opsional di luar graf build MySQL Windows dan Linux. [Advisory RustSec](https://rustsec.org/advisories/RUSTSEC-2026-0459.html).
