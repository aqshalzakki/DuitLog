# Duit Log MVP — Technical Specification

**Versi:** 0.2 — Rust Edition; rancangan teknis untuk review, belum disetujui sebagai implementasi final  
**Tanggal:** 21 November 2026  
**Status produk:** MVP Scope Frozen · Ready for Specification (bukan Ready for Production)  
**Acuan:** `Duit_Log_MVP_BRD_v0.1.md` (96 BR); `Duit_Log_MVP_PRD_v0.1.md` (120 PR, 25 AC BRD)  
**Pembaca:** pemilik produk, backend/frontend engineer, reviewer keamanan, operator, AI Coding Agent  
**Lingkup dokumen:** rancangan kontrak teknis untuk stack Rust, **bukan** kode aplikasi, migrasi SQL yang siap dijalankan, atau bukti uji production.  
**Perubahan v0.2:** backend NestJS/TypeScript + Prisma diganti **Rust + Axum + Tokio + SQLx** atas persetujuan pemilik produk. Business rules, PRD, DB MySQL, deployment, offline security, dan scope tetap. Dokumen v0.1 dipertahankan sebagai arsip.

> **Aturan precedence.** BRD menentukan invarians bisnis dan scope. PRD menentukan pengalaman pengguna. Technical Specification menjabarkan cara memenuhi keduanya. Ketidaksesuaian tidak boleh diselesaikan AI Coding Agent dengan mengubah business rule secara diam-diam: tandai, ajukan review, dan catat keputusan. Semua nilai yang ditandai **usulan teknis** belum menjadi kesepakatan produk baru.

---

**Change log v0.2 (Rust Edition, 21 November 2026).** Menetapkan Rust + Axum + Tokio + SQLx untuk backend dan worker sebagai pengganti NestJS/Prisma; menambahkan kontrak Cargo workspace, error/async, SQLx transactions/migrations, auth middleware, pengujian Rust, dan resource-aware deployment. **Tidak mengubah** ID `BR-*`, `PR-*`, `AC-*` atau seluruh business invariants. Perubahan stack adalah keputusan eksplisit pemilik produk; nilai library, limit, dan implementasi tertentu yang belum disepakati tetap merupakan usulan.

## 1. Executive technical summary

Duit Log adalah PWA pencatatan keuangan pribadi multi-user dengan **satu saldo utama per akun**, IDR integer, transaksi Increase/Deduct, saldo aktual sebagai snapshot, piutang agregat per profil peminjam, lampiran privat, laporan resmi online-only, dan penyimpanan offline terenkripsi secara opt-in. Server adalah sumber kebenaran finansial; offline hanya dapat menghasilkan estimasi lokal dan aktivitas Pending.

### 1.1 Keputusan arsitektur yang terkunci

| Domain | Keputusan |
|---|---|
| Application backend | **Rust + Axum + Tokio** sebagai **Modular Monolith**, REST API berversi |
| Persistence | **MySQL InnoDB + SQLx**, raw/typed parameterized SQL dan migrasi terkontrol; mutasi finansial transaksional |
| Frontend | **Vue 3 + TypeScript + Vite**, Vue Router, Pinia, PWA |
| Jobs | Worker persisten dengan antrian **berbasis MySQL**; tanpa Redis wajib pada MVP |
| Object storage | S3-compatible **private** di luar VPS |
| Production | **Satu VPS + Docker Compose**; HTTPS/reverse proxy; backup dan object storage off-VPS |
| Financial consistency | Per-user pessimistic financial lock + edit optimistic version + audit + idempotency atomik |
| Money | IDR integer; representasi jaringan **decimal string** untuk nilai signed 64-bit |
| Chronology | Effective instant absolut, lalu **immutable financial sequence** server; dependensi divalidasi |
| Offline | Opt-in; encrypted IndexedDB; Hybrid Lock; PIN 6 digit; strong key wrap; Recovery Key |
| Sync | Foreground-first, partial sync, max 3 auto retries per cycle, safe result lookup |
| Reports | Online-only, server-confirmed saja; PDF/Excel seluruh detail dan summary |
| Recovery | Controlled Recovery; daily backup + PITR off-VPS; target RPO ≤1 jam/RTO ≤4 jam **harus diuji** |
| Accessibility | Target WCAG 2.2 AA; prompt-based PWA update, restore route setelah unlock |

### 1.2 Invarians P0

1. Saldo utama boleh negatif, piutang **tidak** boleh negatif pada titik manapun dalam kronologi efektif tiap peminjam.
2. Snapshot menyimpan **target saldo**, bukan delta tetap; perubahan histori sebelum snapshot mengubah delta turunannya tanpa mengubah target.
3. Tidak boleh ada commit parsial antara aktivitas, dampak saldo/piutang, materialized balance, perubahan snapshot turunan, audit, dan idempotency result.
4. Satu identitas percobaan dengan payload identik hanya memberi **satu** efek finansial, termasuk setelah respons hilang; payload berubah memakai attempt baru dan tidak menduplikasi aktivitas yang sudah confirmed.
5. Entri pending tidak masuk laporan resmi; pengaruhnya mungkin masuk estimasi hanya jika rekonstruksi lokal dapat dibuktikan benar.
6. Setiap request terlindungi oleh autentikasi dan otorisasi **owner pada server**, tidak hanya router guard UI.
7. Pada verified mismatch akun: Financial Integrity Freeze akun. Setelah restore bencana: **global Financial Recovery Mode** sampai verifikasi operator selesai.
8. Waktu absolut transaksi/snapshot tidak berubah karena perubahan timezone; pengelompokan kalender mengikuti timezone akun **terkini**.

### 1.3 Batas scope

MVP tidak mencakup multi-wallet, recurring/future scheduled payments, bank integration, payment gateway, transaksi mata uang lain, write-off piutang, auto background sync ketika browser tertutup, remote wipe yang dijamin, atau admin dashboard operasional kompleks. **Tidak membuat fitur tambahan hanya demi kemudahan implementasi.**

## 2. Struktur aplikasi dan ownership modul

### 2.1 Deployment logical view

**Browser (Vue PWA)** ⇄ **HTTPS reverse proxy** ⇄ **Axum API (Rust)** ⇄ **MySQL InnoDB**. **Rust worker** berjalan sebagai binary/proses/container terpisah menggunakan pustaka domain bersama dan database yang sama. API/worker berinteraksi dengan **private object storage** untuk bukti/ekspor. Backup & binlog disalin terukur ke media **off-VPS**, bukan hanya volume Docker lokal.

Frontend dan API disajikan melalui *same origin* HTTPS (contoh pola `https://<domain>/` dan `/api/v1/`) untuk mengurangi kompleksitas CORS/cookie, **bukan** menghilangkan kebutuhan CSRF. Reverse proxy hanya meneruskan rute yang disetujui. Tidak ada akses langsung publik ke port MySQL atau worker.

### 2.2 Boundary modul backend

| Modul | Tanggung jawab | Dilarang dilakukan |
|---|---|---|
| Identity & Sessions | registrasi, verifikasi, login, refresh, devices, reset password | menulis ledger tanpa Financial domain |
| Account & Preferences | profil, timezone, tema, onboarding state | mengubah effective instant saat timezone berubah |
| Categories | kategori default/custom, archive/restore | memutus hubungan kategori historis |
| Financial Core | ledger, snapshot, balance projections, locks, sequence, invariant | memanggil network eksternal di dalam DB transaction |
| Receivables | profil peminjam, pinjam/bayar, replay nonnegative, archive | mem-bypass Financial Core saat saldo terpengaruh |
| Transactions & Audit | detail, edit, soft delete, restore, immutable audit trail | menghapus permanen transaksi dalam MVP |
| Sync & Idempotency | operasi item, dependency, retry result, conflict, replay | membuat endpoint finansial paralel dengan aturan berbeda |
| Evidence | upload token, finalisasi, quarantine, autorisasi download | menganggap upload gagal = financial rollback |
| Reports & Exports | agregasi confirmed, filter timezone, export jobs | menghitung pending sebagai laporan resmi |
| Worker & Operations | email, export, file checks, cleanup, reconciliation, freeze/recovery | silently auto-repair mismatch tanpa prosedur |

**Aturan dependency:** semua jalur mutasi keuangan—request online biasa, sync item, restore, dan prosedur operator—memakai satu service/transaction boundary Financial Core yang sama. Controller/API tidak menentukan bisnis sendiri.

### 2.3 Rust runtime, Cargo workspace, dan batas modul (v0.2)

**Keputusan:** satu backend Rust **modular monolith**, bukan microservices. Rust API menggunakan **Axum** (HTTP routing/extractors) di atas **Tokio** (async runtime); akses MySQL memakai **SQLx**. Kode domain finansial harus tetap terlepas dari transport Axum, sehingga endpoint online, sync, worker, dan alat operator memakai implementasi aturan yang sama.

**Struktur konseptual yang direkomendasikan (nama crate/direktori masih usulan teknis):**

- *api binary*: menyusun router `/api/v1`, request/response DTO, validation, session extraction, middleware, CSRF, rate-limiting, response/error mapping, health/readiness.
- *worker binary*: poller job MySQL dan runner tugas email, export, file verification, housekeeping, serta reconciliation; **bukan** API finansial kedua.
- *domain/application library*: Financial Core, receivables, immutable audit, idempotency, unit-of-work orchestration, authorization interfaces dan business errors; jangan memanggil Axum dari domain.
- *infrastructure library*: SQLx repositories/transactions, object-storage adapter, mailer, clock, entropy, structured logging, configuration; ketergantungan diarahkan menuju kontrak domain.
- *frontend workspace*: Vue 3 / TypeScript / Vite tidak diubah oleh migrasi backend.

Gunakan **Cargo workspace** agar binary API dan worker berbagi library domain tanpa duplikasi. Bentuk workspace, jumlah crates, naming, dan DI pattern final diperiksa pada Phase 0/1; jangan membuat abstraksi generik berlebih hanya untuk mengejar 'clean architecture'. Hindari `unsafe` kecuali kebutuhan tak terelakkan telah diaudit dan disetujui; jangan memperlakukan Rust memory-safety sebagai pengganti keamanan API, transaksi SQL, atau penanganan secret.

**Async & resource constraints:** pertahankan koneksi database berhingga lewat `MySqlPool`, timeout eksplisit, cancellation-safe operations, bounded request/body size, worker concurrency rendah pada VPS 2 GB, graceful shutdown yang menyelesaikan/menandai job aktif, dan larangan blocking file/CPU-heavy processing di Tokio reactor. Gunakan `spawn_blocking` atau proses worker terisolasi untuk rendering PDF, hashing berat, atau pekerjaan CPU-bound, dengan batas konkuren dan memori. Nilai default pool/timeout/job limit adalah **usulan operasional** yang diuji pada workload satu pengguna, bukan jaminan VPS 1 GB cukup.

**DTO contract:** gunakan `serde` dengan tipe terkontrol untuk uang (`i64` dalam domain, parse string desimal secara ketat pada boundary, `i128`/checked arithmetic pada perhitungan antara bila perlu, konversi ke `i64` hanya setelah cek range). Jangan expose `i64` nominal sebagai number JSON. Waktu efektif direpresentasikan sebagai UTC instant berpresisi disepakati, dengan IANA timezone per akun untuk UI/filter, bukan timezone sistem operasi VPS.

### 2.4 Error mapping dan instrumentation Rust (v0.2)

Error domain yang dapat dipulihkan menggunakan typed error (`Result`/enums) dengan mapping deterministik ke taxonomy §7.4; jangan memakai `unwrap()`, `expect()`, panic, atau `todo!()` pada jalur request/worker production. Gunakan HTTP middleware/tracing yang tidak merekam credential, cookies, Recovery Key, payload bukti, atau data keuangan sensitif. Panic bukan mekanisme validasi bisnis. Kegagalan transient MySQL diterjemahkan ke retry terbatas dengan attempt yang sama dan unknown-outcome lookup; konflik bisnis tidak di-retry otomatis.

### 2.5 Boundary frontend

- **Router:** capability guards (login, email verified, lock state, online/offline capability, recovery/freeze).
- **Server state:** confirmed transactions, balance, borrower, report/export result; cache dapat tidak lengkap dan punya `lastVerifiedAt`.
- **Local encrypted state:** per-account/per-device draft, pending, evidence, cached references, key wrappers, sync metadata; **bukan Pinia plaintext persisten**.
- **Transient state:** form UI aktif, soft-lock memory state dan kunci saat unlocked. Kunci tidak berada di localStorage/Pinia yang diserialisasi.
- **Service worker:** app-shell/static assets dan lifecycle update; tidak mengakses plaintext DEK serta tidak dijadikan jalur sync finansial wajib.

## 3. Data model konseptual dan batas transaksi

**Ini adalah inventaris entitas dan invariant, bukan DDL / SQLx migration final.** Nama di bawah merupakan istilah konseptual; implementor boleh memperbaiki struktur fisik tanpa mengubah hubungan, cakupan, atau keamanan.

| Konsep data | Field/relasi penting | Constraint utama |
|---|---|---|
| Account | owner ID, email normalized, verification, timezone, onboarding | email unik; default timezone `Asia/Jakarta` |
| Device Session | account, device, token family hash, auth instant, absolute expiry, revoked | expiry absolut ≤30 hari sejak initial login |
| Financial Account State | owner, current balance, version, next sequence, freeze flag | satu per akun; row sebagai lock anchor |
| Activity (current logical version) | owner, immutable ID, kind, amount, effective instant, sequence, active/deleted, version, optional borrower/category, cash-effect | signed 64-bit safe; tenant-scoped; sequence tak berubah setelah commit |
| Snapshot | owner, effective instant, immutable sequence, target signed balance, derived delta, provenance | target otoritatif; onboarding atau adjustment server-time |
| Borrower | owner, borrower ID, name, phone/notes, archived, current receivable, version | nama boleh duplikat; current receivable ≥0 |
| Category | owner or shared defaults, name, status, version | arsip tetap melekat pada sejarah |
| Financial Audit | operation, actor, action time, before/after, changed snapshots, reason, correlation | append-only pada level aplikasi; tidak menyimpan secret |
| Idempotency / Operation Result | owner, attempt ID, client activity ID, canonical hash, status, server IDs/result | unique owner+attempt; catat hasil **satu commit** dengan efek |
| Sync dependency metadata | owner, local activity references / predecessor IDs | validasi bahwa ketergantungan sah dan milik akun sama |
| Attachment | owner, activity, object key, size, signature/type, status, version | maksimal satu aktif per activity, bucket private |
| Export Job | owner, query/filter snapshot, status, output object, expires | file tidak dapat diakses antar-akun |
| Durable Job | type, payload reference, attempts, lease/fencing, next run, status | at-least-once processing; handler idempotent |
| Recovery/Integrity State | scope global/per owner, reason, verified by, freeze/reopen timestamps | operator-only transitions with audit |

### 3.1 Physical data safety

- Semua tabel personal menyertakan `owner_id` atau mempunyai jalur relasi terverifikasi ke owner. Query by resource ID **selalu** disertai ownership scope.
- Integer finansial menggunakan tipe SQL bertanda 64-bit; validasi overflow sebelum dan selama kalkulasi. Nominal transaksi **> 0**, saldo/snapshot boleh negatif. Jangan menggunakan `FLOAT`, integer wrapping/unchecked arithmetic, JavaScript `number` untuk integer di luar rentang aman, atau serialisasi nilai besar tanpa kontrak string.
- Nilai uang di API sebagai **string desimal** (mis. `"250000"`, `"-50000"`) dengan aturan integer kanonik. Frontend berhitung integer presisi (bukan floating-point); formatter hanya saat render.
- Indeks dibutuhkan untuk `(owner, effective_at, financial_sequence)`, `(owner, status, effective_at)`, `(owner, borrower_id, effective_at, financial_sequence)`, `(owner, attempt_id)` unik, `(owner, client_activity_id)` unik untuk confirmed creation; audit by `(owner, action_at)`. Rancangan indeks diverifikasi terhadap query plans dan locking nyata.
- Hapus keuangan = **soft delete**; catatan historis, audit, dan keterkaitan bukti yang dibutuhkan tetap dipertahankan. Tidak ada TTL otomatis untuk Recently Deleted pada MVP.
- Perubahan versi/edit logical activity disimpan lewat version increment; before/after yang dibutuhkan audit tidak boleh hilang setelah update.
- Semua timestamp server disimpan sebagai instan UTC/representasi offset-unambiguous; pilih satu presisi database yang konsisten, dengan konversi eksplisit di boundary. Zona waktu adalah **IANA timezone ID**. Jangan interpretasikan waktu lokal ambigu saat DST tanpa offset/disambiguation.

### 3.2 SQLx, migrations, dan transaksi MySQL (v0.2)

- **SQLx adalah akses SQL async, bukan pengganti ORM yang mengelola relasi otomatis seperti Prisma**. Hubungan owner, FK, unique constraints, indexes, cascade restrictions, dan invarians relasi harus secara eksplisit dinyatakan dalam migrasi dan diuji dengan MySQL nyata. Semua parameter request harus dibind, bukan string interpolation SQL.
- Gunakan `sqlx::migrate`/`sqlx-cli` atau mekanisme SQLx migration yang konsisten, **versioned forward migration**, checksum/riwayat perubahan, pemeriksaan sebelum deploy, dan backup/rollback playbook untuk perubahan destruktif. **Tidak** menjalankan migrasi berbahaya otomatis ketika API baru start pada production.
- Untuk query macros (`query!`, `query_as!`) jika dipilih, CI/build harus menyediakan `DATABASE_URL` ke database build dengan schema migrasi benar **atau** metadata offline yang dibangkitkan/diperiksa sesuai versi SQLx. Compile-time verification bukan bukti query benar secara domain, race-safe, tenant-safe, atau optimal.
- Pessimistic lock memakai `SELECT ... FOR UPDATE` pada **baris account financial state** di dalam satu transaksi `MySql` yang sama, lalu baca state dan validasi mutasi setelah lock diperoleh. Pemilihan isolation level (mis. default `REPEATABLE READ` vs `READ COMMITTED`) harus diuji: jangan membangun read snapshot lama sebelum lock atau mengasumsikan `SELECT` non-locking selalu melihat data terkini. Index dan urutan lock harus deterministik untuk mencegah deadlock lintas borrower/snapshot.
- Periksa `commit`/`rollback` error dan outcome ambiguous; **jangan** menganggap `drop` transaction/pool timeout sebagai bukti rollback/commit yang sudah diketahui klien. Idempotency record, audit, sequence, ledger dan projections harus satu commit yang sama; cek outcome endpoint untuk kehilangan respons.
- Handler dan background job hanya boleh menerima interface financial mutation yang menjaga lock dan audit; query SQL langsung untuk mengubah saldo di luar boundary finansial adalah pelanggaran spesifikasi.

### 3.3 Projection dan sumber kebenaran

Daftar aktivitas confirmed yang *aktif secara logis* + snapshot bertarget + sequencing menghasilkan **ledger view** otoritatif; current balance dan borrower receivable adalah **materialized projections** untuk pembacaan cepat. Audit adalah catatan peristiwa perubahan, bukan pengganti penghitungan ledger. Perhitungan ulang membangun kembali hasil dari sumber finansial yang sama dan membandingkannya dengan projections.

Mutasi yang mengganti history wajib merekalkulasi bagian terdampak (atau seluruh rentang akun untuk MVP jika aman secara performa), di bawah lock, dan mempersamakan **seluruh** projections/snapshot deltas sebelum commit. Implementor **tidak boleh** menyimpan saldo sebagai penjumlahan incremental sederhana yang mengabaikan snapshot/backdate.

## 4. Financial Core: ordering, snapshot, piutang

### 4.1 Urutan otoritatif

Urutan kronologis untuk satu akun: **`(effective_instant ASC, immutable_financial_sequence ASC)`**. Sequence diberikan server ketika operasi pertama kali **berhasil commit**, dari counter milik akun yang diambil di bawah pessimistic financial lock. Sequence melekat pada aktivitas/adjustment dan **tidak ditentukan ulang** saat edit effective timestamp, delete atau restore. Action/audit time terpisah. Jika dependensi tidak mungkin dipenuhi pada urutan tersebut, operation **ditolak/conflict**, bukan waktu atau sequence digeser diam-diam.

Aktivitas client offline belum mempunyai server sequence; urutan local hanya sementara dan tidak mengklaim sama dengan urutan final. Dependensi eksplisit wajib divalidasi sebelum item child dievaluasi, termasuk borrower yang dibuat offline. Jika dua aktivitas dengan effective instant sama dan pembayaran depend pada pinjaman, server boleh memproses parent terlebih dulu dalam graf dependensi; jika urutan final masih tidak sah, reject. Historical edit tetap memakai sequence yang semula sehingga invariant diuji ulang pada sejarah baru.

### 4.2 Ledger delta per jenis

| Jenis | Delta cash | Delta receivable | Termasuk income/expense? |
|---|---:|---:|---|
| Increase | `+amount` | 0 | Income |
| Deduct | `-amount` | 0 | Expense |
| Loan, affect balance ON | `-amount` | `+amount` | Tidak |
| Loan, affect balance OFF | 0 | `+amount` | Tidak |
| Repayment, affect balance ON | `+amount` | `-amount` | Tidak |
| Repayment, affect balance OFF | 0 | `-amount` | Tidak |
| Snapshot adjustment | delta hasil rekalkulasi | 0 | Tidak |
| Draft / Pending | tidak masuk server official | tidak masuk official | Tidak |

### 4.3 Aturan snapshot authoritative

- Pada onboarding: **diisi Rp0 pun berarti snapshot** pada instant server onboarding. **Lewati** berarti basis awal Rp0 **tanpa snapshot**.
- Balance Adjustment online menerima **target saldo sebenarnya**; effective instant **server sekarang**, tidak bisa backdate. Target bisa negatif. Preview UI tidak mengunci hasil; service menghitung ulang di dalam transaksi saat commit.
- Evaluasi ledger: mulai basis Rp0; urutkan seluruh activity aktif dan snapshot; apply delta activity; ketika menjumpai snapshot target `S`, hitung `delta = S − balance_before_snapshot` (cek overflow), lalu hasil pada titik itu **persis S**. Lanjutkan aktivitas berikutnya.
- Ketika activity historis berubah, delta setiap snapshot terdampak dihitung ulang; `target` tetap. Jika ada beberapa snapshot, masing-masing target otoritatif; hanya perubahan setelah snapshot terakhir yang memengaruhi saldo kini tanpa diserap snapshot berikutnya.
- Snapshot tidak dicampur income/expense; tampilkan mutasi adjustment di Balance Movement dan History dengan label berbeda; audit rekalkulasi delta wajib menyebut operasi pemicu dan before/after.
- Snapshot pada instant identik dengan transaksi dibedakan menggunakan sequence server. Saat snapshot baru dibuat dengan server timestamp, sequence diberikan sesuai commit order. Jika activity baru belakangan diberi effective instant tepat sama, financial sequence baru dapat menempatkannya **sesudah** snapshot.

**Uji ilustratif:** snapshot onboarding Rp1.000.000 pada 12:00, lalu Deduct Rp100.000 bertanggal 10:00 yang baru dikomit malam hari: `delta` snapshot bertambah Rp100.000, saldo akhir tetap Rp1.000.000. Jika Deduct effective 13:00, saldo akhir menjadi Rp900.000.

### 4.4 Piutang nonnegative sepanjang kronologi

- Satu profil peminjam = satu rangkaian agregat; nama duplikat tidak digabung.
- Replay activity loan/repayment **aktif** per peminjam berdasarkan chronology server; saldo mulai Rp0, akumulasi **tidak boleh < 0 pada satu prefix manapun**. Ini diperiksa untuk create, edit, delete, restore, historical backdate, dan sync.
- Pembayaran di atas outstanding saat titik efektifnya menolak **keseluruhan** mutasi, termasuk cash impact; tidak ada partial payment otomatis.
- Archived borrower hanya boleh diarsip saat outstanding akhir = 0; aktivitas baru pada archived borrower ditolak sampai reaktivasi. Jika koreksi historis membuat archived borrower kembali outstanding > 0, unarchive **otomatis** dengan audit.
- Status Paid/Unpaid selalu **turunan** outstanding (0 vs >0), tidak disimpan sebagai kebenaran mandiri yang bisa menyimpang.
- Aktivitas pinjam/bayar yang toggle cash OFF tetap masuk History, memiliki receivable effect, namun **tidak** mengubah cash balance atau laporan income/expense.

### 4.5 Atomic financial mutation protocol

Urutan konseptual (tanpa implementasi kode):

1. Validasi sesi, verifikasi email, otorisasi owner, status global recovery; parse nominal dan instant secara aman; cek request identity.
2. Mulai DB transaction; ambil **exclusive lock pada account financial state** sebagai anchor konsisten untuk seluruh mutasi user, termasuk borrower/archive bila berdampak pada invariant. Cek freeze ulang **di bawah lock**.
3. Cari status idempotency untuk `(owner, attemptId)`. Bila committed + hash cocok, kembalikan hasil terdahulu; hash berbeda = immutable-key conflict. Periksa pula `(owner, clientActivityId)` agar aktivitas baru yang pernah confirmed tidak dikomit dua kali lewat attempt berbeda.
4. Validasi resource/version/dependency, chronological future limit, archived category, owner, dan aturan domain. Assign financial sequence hanya pada **successful new commit**.
5. Terapkan perubahan logis Activity/Snapshot/Borrower; replay ledger dan receivable terdampak; jika negative receivable, overflow, atau aturan sejarah gagal => rollback.
6. Perbarui projections, delta snapshot, audit setiap perubahan dan recalculation, version token, serta operation result/idempotency **dalam transaksi DB yang sama**.
7. Commit. Baru setelah commit lakukan response, enqueue/notification nonkritikal (atau tulis durable job atomik bila menjadi prasyarat operasi).

**Tidak melakukan** network I/O, upload ke object storage, email, atau rendering PDF saat DB transaction terbuka. Deadlock/timeout harus rollback, dipetakan ke retriable error, dan jika aman di-retry di backend dengan batas terukur pada **identitas operasi yang sama**. Timeout yang hasil commit-nya belum jelas harus memakai status lookup terlebih dahulu, bukan menjalankan bisnis dua kali.

### 4.6 Optimistic concurrency, freeze, reconciliation

- Edit/delete/restore confirmed mensyaratkan `expectedVersion`; mismatch menghasilkan `VERSION_CONFLICT` dengan ID/version terbaru (tanpa membocorkan data). Perbaikan histori dapat memengaruhi banyak snapshot/borrower; validasi **seluruh** after-state sebelum commit.
- Per-user financial lock menserialisasi write untuk satu user; write user lain tidak ikut dibekukan. Global Financial Recovery Mode menolak semua mutasi yang berpengaruh finansial dan seluruh sync saat restore.
- Scheduled reconciliation memverifikasi ledger replay vs current balance/receivable dan target snapshot. Selisih yang **terverifikasi** menyebabkan freeze akun dan audit. Tidak boleh silent auto-fix. Audit dan diagnosis harus dapat dibaca operator secara terkendali.
- Unlock freeze hanya melalui prosedur operator terautentikasi/berotorisasi, dengan reason, bukti pemeriksaan, tindakan repair terkontrol, re-verifikasi, actor/time, dan audit. User biasa tidak memiliki tombol unfreeze.

### 4.7 Pola eksekusi aman untuk Axum + SQLx (v0.2)

Setiap handler Axum hanya mem-parse input, memvalidasi identity/authorization dan memanggil application service; **tidak boleh** menyalin aturan ledger ke handler HTTP. Financial Core harus menerima satu `&mut Transaction<'_, MySql>` (atau abstraction unit-of-work setara) yang memastikan seluruh query finansial memakai koneksi/transaksi yang sama; pengelolaan lifetime/borrowing Rust tidak boleh disiasati dengan pemecahan transaksi yang membuat sebagian state commit lebih dulu.

Saat memperbarui `financial_sequence`, gunakan counter/lock milik akun di dalam transaksi; retry akibat deadlock tidak boleh menghasilkan lebih dari satu activity confirmed. Overflow financial balance dan receivable harus diperiksa eksplisit. Ketika transaksi SQLx melewati `await` untuk query DB di dalam transaksi, cek timeout, cancellation, dan durasi lock; **jangan await** upload S3, SMTP, HTTP eksternal, atau rendering report sebelum transaksi commit.

Pengujian wajib memakai **MySQL InnoDB nyata** untuk concurrency, deadlock, isolation, row-level locking, snapshot replay, dan idempotency. Test dengan hanya mock repository tidak menjadi bukti kelulusan financial gate. Rust compiler mencegah beberapa kelas memory bug, bukan race logis di database.

## 5. Waktu, zona waktu, dan batas periode

- Setiap transaction activity menyimpan `effectiveInstant` absolut. `actionAt` server disimpan terpisah untuk audit; waktu penerimaan dan waktu pemrosesan sync boleh berbeda.
- Input tanggal/jam berdasarkan timezone akun aktif dan dikonversi dengan informasi offset/disambiguasi bila DST menghasilkan jam ambigu/tidak ada; **jangan** menerka instan ambigu.
- Jika timezone akun berubah: instant lama tetap, label tanggal/jam dan grouping harian/periodic report berubah, termasuk cache invalidate; tampilkan peringatan PRD dan audit perubahan setting.
- Waktu server menentukan larangan future transaction **pada acceptance**, meski browser offline awalnya mengandalkan jam perangkat. Future saat sync → `INVALID_FUTURE_EFFECTIVE_TIME` conflict tanpa rewrite otomatis.
- Offline authorization 7 hari sejak verifikasi online terakhir tidak dapat dijamin anti-pemalsuan jika jam perangkat dimanipulasi. Simpan signed/authenticated server validation metadata sebagai tamper-evident context, gunakan available monotonic time saat runtime aktif, mendeteksi clock rollback/jump, dan **fail-closed** saat anomali sampai online revalidation; jangan mengklaim browser offline memiliki trusted secure clock.
- Range laporan menggunakan **interval setengah terbuka `[startInstant, endInstant)`** yang diperoleh dari batas tanggal lokal dalam timezone akun sekarang. Historical opening balance = nilai tepat sebelum `startInstant`; closing = nilai sesudah seluruh event `effectiveInstant < endInstant`. Kegiatan persis pada awal periode masuk periode itu; persis pada batas akhir masuk periode berikutnya.
- Minggu memakai konvensi minggu lokal **Senin–Minggu** (usulan teknis yang perlu tercermin konsisten pada UI). Untuk periode berjalan gunakan elapsed local calendar span dibanding periode sebelumnya setara; custom range membandingkan rentang kalender sebelumnya sepanjang rentang yang dipilih; timezone/DST diuji sehingga label batas periode tidak menyesatkan.

## 6. Authentication, session, dan security server

### 6.1 Identity

- Registrasi nama/email/password; normalisasi email dan kebijakan password anti-credential stuffing; hash password modern dengan konfigurasi teruji. Email verification token sekali pakai, berdurasi terbatas, disimpan hashed, resend rate-limited; API keuangan ditolak sebelum verifikasi.
- Reset password memakai token sekali pakai/berkedaluwarsa, respons tidak membeberkan apakah email terdaftar; token tidak disimpan mentah dan tidak dicetak di log. Session revocation policy saat reset harus eksplisit diuji.
- Login persisten maksimum **30 hari absolut** sejak initial login per device; rotasi refresh token tidak memperpanjang absolute deadline. Short access token, refresh rotation + reuse detection, server-side session registry, manual device revocation.
- Cookies memakai `HttpOnly`, `Secure`, pengaturan `SameSite` yang sesuai, host/domain/path ketat, perlindungan CSRF untuk mutating requests dan rate limits. Jangan meletakkan bearer credential/refresh token pada IndexedDB plaintext/localStorage.
- Logout dengan pending: peringatan pada UI, revoke server jika online; local account cache tetap encrypted dan Hard Lock. Jika offline, session server belum tentu segera dicabut—UI harus menyatakan keterbatasan.

### 6.2 Authorization

- Seluruh ID dikondisikan owner dari authenticated session, **bukan** dari `ownerId` kiriman klien. API mengembalikan 404/403 secara konsisten untuk resource yang tak berhak; jangan mengungkap keberadaan milik pengguna lain.
- Export/attachment preview via endpoint terotorisasi, short-lived signed URL terikat object key dan permission; bucket tidak public. URL tidak dicatat di log atau dibocorkan ke referrer.
- Operator recovery memiliki jalur otorisasi terpisah, akses minimal, audit, serta kontrol akses teruji. **Tidak** ada general-purpose SQL editing interface pada MVP.

### 6.3 Error dan logging safety

- Pesan error klien tidak membocorkan existence user, secret, stack trace, raw SQL, object key, atau detail diagnosis operator. `requestId` untuk korelasi.
- API, worker dan audit mencatat actor, target, before/after finansial yang perlu, waktu server dan origin; **tidak** mencatat password, PIN, DEK, Recovery Key, raw auth tokens, atau isi bukti.
- Rate limit dan anti-abuse untuk login/reset/resend serta upload; threshold numerik adalah **usulan operasional** dan diuji sebelum production.

### 6.4 Auth implementation boundary Rust (v0.2)

Di Axum, authentication extraction/middleware membentuk typed principal yang diambil **hanya dari sesi server tervalidasi**, bukan `owner_id` kiriman klien; repository menerima authorized owner context. CSRF berlaku pada request yang mengandalkan cookie; konfigurasi SameSite tidak otomatis menghilangkannya. Refresh rotation serta token-reuse detection memerlukan penyimpanan state MySQL dan operasi atomik. Secret hashing/verification (contoh Argon2id) harus menggunakan parameter yang ditinjau dan rate limiting; tugas CPU-bound ditempatkan pada executor yang tepat agar tidak memblokir Tokio. Error otorisasi tidak boleh membocorkan keberadaan resource milik akun lain.

## 7. REST API v1: contracts dan status

**Base path:** `/api/v1`. Semua endpoint finansial memerlukan authenticated, verified session, owner authorization, dan check global/per-account freeze sesuai capability. Semua write finansial menggunakan service Financial Core yang sama, baik dipanggil biasa maupun melalui Sync.

### 7.1 Common contract

- API JSON `camelCase`; waktu absolut RFC 3339 ber-offset eksplisit (direkomendasikan UTC `Z`); timezone akun sebagai IANA ID. Nominal bertanda/amount memakai **decimal string**, tidak pernah floating point.
- Setiap mutation request membawa `clientActivityId` (immutable identitas aksi pengguna) dan `attemptId` (identitas **percobaan payload**), dari UUID/identifier acak kuat; untuk perubahan confirmed sertakan `expectedVersion`.
- `requestId`/correlation ID dipakai untuk debugging, **bukan** pengganti idempotency key. One financial activity may have multiple attempts only when a rejected/conflicted payload corrected; new attempt must not create second copy of already confirmed activity.
- Semua success mutation yang diketahui mengembalikan `operationId`/`attemptId`, `resourceId`, resource `version` jika relevan, `effectiveAt`, `financialSequence` setelah committed, dan authoritative `financialStateVersion`/server-known balance jika perlu.
- Semua error: `code` machine-readable, `message` aman, `requestId`, optional `fieldErrors`, optional `retryable`, optional `conflictDetails` terbatas owner. HTTP status membantu tetapi **outcome unknown** tidak dapat disamakan dengan confirmed rejection.
- Pagination memakai cursor stabil berdasarkan urutan `(effectiveAt, sequence, id)` dan filter server-side dengan owner; search/results menandai `hasMore` dan tidak mengklaim cache lengkap.

### 7.2 Daftar endpoint konseptual

| Grup | Method dan path | Hasil utama / aturan |
|---|---|---|
| Auth | `POST /auth/register`, `POST /auth/login` | registrasi, sesi awal, email pending |
| Auth | `POST /auth/verify-email`, `POST /auth/resend-verification` | token sekali pakai, rate limited |
| Auth | `POST /auth/forgot-password`, `POST /auth/reset-password` | token pemulihan lewat email |
| Auth | `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all` | rotasi dan revoke sesi; absolute expiry |
| Sessions | `GET /sessions`, `DELETE /sessions/{id}` | daftar/revoke perangkat milik akun |
| Account | `GET /me`, `PATCH /me/preferences` | timezone IANA, tema, profile; audit setting |
| Onboarding | `GET /onboarding`, `POST /onboarding/opening-balance`, `POST /onboarding/skip-opening-balance` | keputusan sekali saat onboarding; snapshot jika isi termasuk `0` |
| Financial summary | `GET /financial-state` | confirmed current balance/receivables, version, timestamp, freeze/recovery status |
| Activities | `GET /activities`, `GET /activities/{id}` | history semua jenis; cursor/filter; owner scope |
| Activities | `POST /activities` | Increase/Deduct/Loan/Repayment lewat Financial Core; exact once |
| Activities | `PATCH /activities/{id}`, `DELETE /activities/{id}` | edit dan soft delete **online-only**, expected version |
| Activities | `POST /activities/{id}/restore` | restore online-only dengan replay dan audit |
| Balance | `POST /balance-adjustments` | snapshot saldo target dengan waktu server; online-only |
| Borrowers | `GET /borrowers`, `POST /borrowers`, `GET /borrowers/{id}`, `PATCH /borrowers/{id}` | owner-scoped borrower; create offline sync mampu |
| Borrowers | `POST /borrowers/{id}/archive`, `POST /borrowers/{id}/reactivate` | online-only; validasi outstanding |
| Categories | `GET /categories`, `POST /categories`, `PATCH /categories/{id}` | aktif/custom/default; nama/ownership |
| Categories | `POST /categories/{id}/archive`, `POST /categories/{id}/restore` | online-only; historical link tetap |
| Audit | `GET /audit` | timeline by actionAt; actor dan before/after terotorisasi |
| Sync | `POST /sync/items`, `GET /operations/{attemptId}` | partial item results, dependency, replay status |
| Upload | `POST /activities/{id}/evidence/prepare`, `POST /activities/{id}/evidence/finalize` | token upload privat dan pemeriksaan object |
| Upload | `GET /activities/{id}/evidence`, `DELETE /activities/{id}/evidence` | akses evidence dan operasi yang diizinkan; audit |
| Reports | `GET /reports/income-expense`, `/reports/balance-movement`, `/reports/receivables` | confirmed-only; online-only; timezone-aware |
| Exports | `POST /exports`, `GET /exports/{id}`, `GET /exports/{id}/download` | durable job dan download terotorisasi |
| Offline validation | `POST /offline-access/validate` | pemeriksaan sesi/eligibility dan refresh bukti validasi server |
| Integrity | `GET /integrity-status` | status terbatas untuk user; no operator detail leak |
| Operator restricted | recovery-specific action endpoints/workflow **dipisah** dari public user namespace | verifikasi/repair/unfreeze dengan privileged identity dan audit |

**Catatan:** path di atas adalah **proposal API v1 yang siap direview**, bukan endpoint yang sudah diimplementasi. Nama route bisa diselaraskan saat kontrak final disetujui; semantik dan otorisasi tidak boleh berubah. Untuk dua route update archive/restore, gunakan method/version consistency; jangan overload endpoint yang tidak idempotent tanpa operation identity.

### 7.3 Shape inti aktivitas (konseptual)

| Field | Kebutuhan |
|---|---|
| `kind` | `INCREASE`, `DEDUCT`, `LOAN`, `REPAYMENT`; adjustment punya endpoint sendiri |
| `amount` | string integer IDR positif; tanpa tanda koma, notasi ilmiah, atau desimal |
| `effectiveAt` | absolute instant; tidak lebih besar dari waktu server saat acceptance |
| `title`, `description` | opsional; escape saat render; bukan identity/dedup key |
| `categoryId` | opsional; kategori aktif untuk create baru |
| `borrowerId` / `localBorrowerRef` | wajib untuk Loan/Repayment; owner dan dependensi valid |
| `affectCashBalance` | Loan/Repayment, default true; tidak digunakan untuk Increase/Deduct |
| `clientActivityId`, `attemptId` | random unique identifiers untuk idempotency/deduplication |
| `expectedVersion` | wajib untuk update/delete/restore confirmed |

Server memvalidasi kombinasi field: `borrowerId` tidak boleh membuat Increase berubah jadi aktivitas piutang. Kategori arsip pada create menjadi conflict; restore historis mempertahankan kategori lama. Bytes evidence **tidak** digabung ke financial commit.

### 7.4 Error taxonomy

| Code | HTTP usulan | Perilaku klien |
|---|---:|---|
| `AUTH_REQUIRED` / `SESSION_EXPIRED` | 401 | login ulang, pending encrypted tetap |
| `EMAIL_UNVERIFIED` | 403 | tampilkan verifikasi email |
| `FORBIDDEN_RESOURCE` | 403/404 | tidak bocorkan keberadaan akun lain |
| `VALIDATION_ERROR` / `INVALID_AMOUNT` | 422 | error per field; no commit |
| `INVALID_FUTURE_EFFECTIVE_TIME` | 422 | conflict bila sync; user edit |
| `VERSION_CONFLICT` | 409 | tampilkan current version; no overwrite |
| `CATEGORY_ARCHIVED` | 409 | pilih kategori aktif/tanpa kategori |
| `BORROWER_ARCHIVED` / `RECEIVABLE_NEGATIVE` | 409 | koreksi sesuai riwayat |
| `DEPENDENCY_BLOCKED` | 409/424 | tahan child sampai parent sah |
| `IDEMPOTENCY_PAYLOAD_MISMATCH` | 409 | jangan retry attempt sama dengan payload lain |
| `ALREADY_CONFIRMED_ACTIVITY` | 409 atau prior result | jangan mencatat aktivitas dua kali |
| `FINANCIAL_INTEGRITY_FROZEN` | 423 | block perubahan akun |
| `FINANCIAL_RECOVERY_ACTIVE` | 503 | global block finansial/sync |
| `TEMPORARY_FAILURE` | 429/503 | bounded retry dengan backoff/jitter |
| `OUTCOME_UNKNOWN` | client-derived | check operation status; bukan bukti gagal |
| `EVIDENCE_REJECTED` | 422 | bukti saja gagal, keuangan tetap confirmed |

**Outcome unknown:** bila lookup status tidak mendapatkan data saat recovery/server tidak pasti, klien tidak menganggap otomatis belum committed. Pertahankan attempt identity dan jangan menciptakan activity kedua.

### 7.5 Pagination, caching, dan financial state

- Pagination cursor stabil `(effectiveAt, sequence, ID)`; filter dengan owner dan date-instant range. Jangan mengandalkan offset halaman untuk menjamin chronology di tengah concurrent inserts.
- `financialStateVersion` menandai dasar cache verified untuk mendeteksi perubahan server pada perangkat lain, bukan pengganti checking per-operation result.
- API finance/auth memakai kebijakan cache private/no-store yang tepat. Service worker tidak boleh menyimpan response API sensitif di HTTP cache biasa. Offline cache disimpan eksplisit sebagai ciphertext.
- Reports/export job membekukan parameter filter dan timezone yang digunakan saat pembuatan; perubahan timezone setelah itu tidak mengubah export yang sudah terbit.

## 8. Idempotency, Sync Engine, dan dependency graph

### 8.1 Dua tingkat identitas

- `clientActivityId`: tetap melekat pada satu aksi user dari Pending sampai Synced; uniqueness owner+activity mencegah double create meski corrected attempt berbeda.
- `attemptId`: identitas **satu payload canonical**; retry transport menggunakan attempt ID sama dan hash sama, mengembalikan result terdahulu. Payload dikoreksi setelah confirmed rejection → attempt baru, clientActivityId tetap.
- Canonical hash harus deterministic terhadap tipe uang, timestamp normalized, booleans, null, dan version. Jangan meng-hash display string/urutan key JSON yang berubah-ubah.
- Operation result COMMITTED, audit, dan ledger berada dalam satu commit MySQL. Klaim PROCESSING yang yatim harus dapat dipulihkan aman, bukan dianggap committed.
- Response hilang → lookup `GET /operations/{attemptId}` dahulu. Dalam keadaan database recovery, missing record bukan bukti aman membuat ID baru.

### 8.2 Local queue states

| State | Bisa edit/cancel? | Transisi inti |
|---|---|---|
| `DRAFT` | Ya | Pending / discard |
| `PENDING` | Ya jika belum dispatch | Syncing / cancel |
| `SYNCING` | Tidak | Synced / Conflict / Checking outcome / Retry waiting |
| `CHECKING_OUTCOME` | Tidak | Synced / Conflict / tetap unknown |
| `RETRY_WAITING` | Tidak jika outcome masih mungkin diterima | retry same attempt / resolution |
| `CONFLICT` | Ya setelah definitive rejection | corrected new attempt / cancel |
| `BLOCKED` | bergantung parent | Pending jika dependency resolved |
| `SYNCED` | tidak via local edit | Confirmed online mutations only |

Evidence punya state terpisah: `LOCAL_ENCRYPTED`, `UPLOAD_PENDING`, `UPLOADING`, `QUARANTINED`, `AVAILABLE`, `FAILED`. Transaksi Synced + bukti Failed adalah state sah.

### 8.3 Partial Sync protocol

1. Syarat: app foreground, unlocked, online, session verified, Offline Access still valid, bukan global recovery maupun account integrity freeze.
2. Bangun directed dependency graph per owner; borrower baru di-sync sebelum loan/payment anak. Detect cycles/missing refs sebagai Blocked/Conflict.
3. Kirim activity siap dengan original clientActivityId, attemptId dan payload. Batch transport boleh, tetapi **commit terpisah per item** agar satu error tidak menolak item independen.
4. Server memvalidasi terhadap keadaan terbaru; item valid otomatis accepted; business conflict tidak diretry otomatis; anak item conflict menjadi Blocked.
5. Success: simpan server ID/financial sequence/result, update local state ke Synced. Evidence di-upload belakangan secara independen.
6. Timeout/network unclear: Checking outcome dan lookup attempt sama. Temporary errors: max **3 auto attempts per cycle**, exponential backoff + jitter, tanpa retry business conflict.
7. Reconcile financial confirmed state dengan pending remaining. Jika cache tidak cukup untuk menghitung estimasi, tunjukkan status estimasi unavailable.

Foreground-first adalah jalur wajib MVP; Hard Lock, logout, dan aplikasi tertutup **tidak** diwajibkan menjalankan background sync.

### 8.4 Multi-tab, account isolation, dan conflict resolution

- Setiap encrypted local namespace scoped owner+device, account B tidak bisa membaca/menyinkronkan pending owner A.
- Tab menyampaikan lock/logout/update signal dan menggunakan lease + fencing untuk mencegah tab sama-sama sync item. **Server idempotency** tetap penentu utama jika lease/tab gagal.
- Pending yang belum dispatch dapat diedit dengan clientActivityId sama. Setelah network attempt dikirim, edit/cancel terkunci sampai hasil definitif; jika payload corrected, gunakan new attempt.
- Konflik archived category → pilih active/null. Jam device future → user koreksi. Historical receivable negative → user koreksi operasi terkait. Borrower archived → reaktivasi **online-only**. Expired session → reauth owner yang sama. Freeze → menunggu operator.

## 9. Offline encryption, Hybrid Lock, dan Recovery Key

### 9.1 Threat model dan keterbatasan

Enkripsi at-rest melindungi draft, pending, bounded confirmed cache dan evidence dari pembacaan storage tanpa unlock sah. Ini **tidak** menjamin keamanan terhadap browser/OS yang dikompromikan, XSS ketika data unlocked, hardware keylogger, atau storage yang sudah dihapus. PIN 6 digit adalah mekanisme **Soft Lock** ketika kunci masih aktif di memori; tidak menjadi satu-satunya pelindung ciphertext.

### 9.2 Key architecture

- Saat Offline Access diaktifkan, buat **DEK acak kuat per akun per perangkat**. Enkripsi record/chunk dengan authenticated encryption (contoh Web Crypto AES-GCM), nonce unik, dan AAD mengikat owner, record ID, schema version, dan tipe data.
- Persist hanya **wrapped DEK**, bukan raw DEK. Tiga jalur independen harus dapat membuka existing ciphertext: authenticator compatible **WebAuthn PRF** bila benar-benar tersedia; **strong passphrase KDF** sebagai fallback; **high-entropy Recovery Key** wajib.
- Dukungan WebAuthn/passkey/biometrik tidak otomatis berarti extension PRF dapat digunakan. Capability harus diuji pada browser **dan authenticator aktual**; jika gagal, fallback passphrase tetap disediakan sejak setup.
- Strong passphrase wrapper memakai random salt dan KDF parameter yang didokumentasikan, diaudit dan diuji pada perangkat target. **Usulan:** Argon2id pada implementasi yang teruji atau fallback Web Crypto yang sesuai; jangan menggunakan PIN 6 digit sebagai masukan KDF satu-satunya.
- Recovery Key dibuat dari RNG kriptografis (bukan kata sandi pengguna), ditampilkan sekali dengan verifikasi penyimpanan, tidak disimpan mentah di backend/log/email. Recovery Key **harus mampu unwrap DEK dan decrypt draft/pending yang masih ada** setelah browser restart.
- Rotasi passphrase, authenticator atau Recovery Key mengganti wrapper secara crash-safe tanpa menghapus ciphertext. Bila Recovery Key hilang tetapi masih ada jalur unlock yang sah, user boleh membuat pengganti; bila semua jalur hilang, data lokal mungkin tidak terpulihkan.

### 9.3 Hybrid Lock state machine

| Kondisi | Implementasi yang wajib |
|---|---|
| Setup tidak lengkap | Offline Access tetap nonaktif; jangan klaim setup sebagian aman |
| Unlocked active session | DEK hanya pada memori aktif, plaintext diminimalkan |
| Idle 5 menit, DEK masih di memori | **Soft Lock**: PIN dapat membuka; seluruh informasi sensitif disembunyikan |
| Browser/app restart, logout, account switch, memory DEK hilang | **Hard Lock**: PRF/passphrase/Recovery Key diperlukan, PIN tidak cukup |
| Lupa PIN | Strong unlock yang sah, kemudian set ulang PIN tanpa menghapus pending |
| Lewat 7 hari dari server validation | Block offline feature hingga verifikasi online; ciphertext pending tetap |
| Sesi server >30 hari absolut | Login ulang sebelum API/sync; local unlock bukan sesi server |
| Session revoked saat offline | Tidak bisa dijanjikan langsung terdeteksi; next server access ditolak |

Kebijakan lock tidak boleh bergantung hanya pada event penutupan browser yang bisa tidak dipanggil. Tab lain tidak boleh terus menampilkan decrypted owner A setelah logout/switch-account. PIN failed-attempt UI throttling hanya pertahanan tambahan, **bukan** pengganti kriptografi DEK.

### 9.4 Encrypted IndexedDB dan cache

- Store encrypted per owner+device untuk draft, pending, evidence, bounded recent confirmed history, borrower/category reference, sync metadata, crypto key wrappers dan migration checkpoint. Metadata identitas yang sensitif ikut dienkripsi sejauh memungkinkan.
- Teks status “Tersimpan offline” hanya setelah IndexedDB write transaction **berhasil commit** untuk seluruh payload yang diperlukan; storage quota/transaction failure tidak boleh menampilkan sukses palsu.
- Data pending/draft/evidence pending **tidak di-evict otomatis** oleh bounded cache policy. Bila storage tidak cukup, tolak save yang tidak lengkap dan jelaskan risiko, jangan silent loss.
- Cache confirmed dari server diberi lastVerifiedAt + financial state version; bila snapshot/kronologi tidak lengkap, **Estimasi belum tersedia** daripada sekadar confirmed plus angka pending mentah.
- Ciphertext integrity/tag harus diperiksa; corrupted record tidak boleh silent fallback ke data kosong. Migration storage dienkripsi bersifat versioned dan crash-safe; sebelum overwrite, data lama harus bisa dipulihkan bila migrate gagal.
- Clear Offline Data ketika ada pending memerlukan konfirmasi ekstra terkait kehilangan permanen. Recovery Key tidak memulihkan ciphertext yang sudah dihapus.

### 9.5 PWA update lifecycle

- Service worker mendapat versi baru, tetapi UI hanya menawarkan **Prompt-Based Update**. Tidak boleh memaksa reload di tengah dirty form, Syncing/Checking outcome, migration, atau local draft yang belum commit.
- Sebelum update: pastikan state draft/pending durable, versi schema store kompatibel, dan route pemulihan Hard Lock masih dapat digunakan. Setelah restart berlaku Hard Lock.
- Migrasi local ciphertext harus idempotent dan crash-safe; fail → pertahankan ciphertext lama dan pesan terarah. Jangan memanggil immediate worker takeover tanpa mempertimbangkan tab/client aktif.

## 10. Evidence dan private object storage

### 10.1 Financial commit terpisah upload

- Satu file opsional per aktivitas: JPG, PNG, WebP, PDF, **maksimal 10 MB**. Validasi UI untuk kenyamanan dan validasi server untuk keamanan: size, MIME, magic/signature, decode/structure, dan kebijakan malware scanning bila tersedia.
- Setelah activity confirmed, `prepare` membuat short-lived restricted upload permission ke private key yang acak/owner-scoped; `finalize` memeriksa object size/type/hash lalu status `QUARANTINED` sampai verified. Hanya `AVAILABLE` dapat preview/download.
- Upload/scan gagal **tidak** rollback atau mengulangi commit finansial. Retry file menggunakan file-operation identity sendiri dan tidak membuat new activity.
- Evidence pending offline tetap dalam ciphertext sampai financial commit diterima. Jangan hapus local source sebelum server mengonfirmasi file `AVAILABLE`.
- Activity yang soft-deleted mempertahankan sejarah dan bukti sesuai kebutuhan audit; jangan membuang object yang masih direferensikan.

### 10.2 Security & recovery object storage

Private bucket (tanpa public ACL), least-privilege credentials, random object name, signed link berumur pendek, server-side authorization untuk semua download, dan cleanup sementara yang tidak menghapus object diperlukan. Object store terpisah VPS **bukan** backup yang otomatis memadai: atur versioning/backup dan uji restore referensi file bersama restore database.

## 11. Reports, comparatives, dan exports

### 11.1 Semantik per laporan

| Kelompok | Definisi |
|---|---|
| Income/Expense | Increase sebagai income, Deduct sebagai expense; exclude Loan, Repayment, Snapshot Adjustment dan Pending |
| Balance Movement | opening at range start + semua signed cash movements termasuk piutang cash ON dan snapshot delta = closing at range end |
| Receivables | per-borrower opening, loan, repayment, closing; setiap prefix nonnegative; nama duplikat tetap profil berbeda |
| Dashboard | confirmed current balance dan total receivable tidak terpengaruh period filter; statistik yang terfilter saja berubah |

Semua laporan **online-only** dan berbasis server confirmed logical state, tidak memasukkan Draft/Pending/Deleted. Nilai tanggal dikelompokkan memakai timezone akun terkini. Kategori null = “Tanpa Kategori”; kategori arsip historis tetap muncul.

### 11.2 Period comparison

Periode berjalan yang belum selesai dibanding previous elapsed calendar portion sepadan; periode selesai dibanding previous full period. Custom range dibanding immediately preceding calendar range dengan panjang setara, rentang tanggal pembanding ditampilkan eksplisit. Jika baseline 0 dan current positif tampil **Baru**; dua-duanya 0 tampil **0%**. Ambiguitas hasil persentase (mis. baseline nol dengan current negatif) ditangani lewat state yang dijelaskan, tidak memaksakan pembagian nol. Grafik punya alternatif teks/tabel aksesibel.

### 11.3 Consistency saat export async

- Job export menyimpan filter, timezone, requester owner, format PDF/XLSX, dan version/watermark sumber data.
- Worker mengambil dataset **konsisten** dari confirmed logical view; gunakan consistent DB read dengan materialization atau pendekatan lain yang telah dibuktikan, lalu render file di luar DB transaction. **Jangan** mencampur summary pada waktu A dengan detail pada waktu B saat concurrent edits.
- File mencakup summary + **seluruh detail terfilter**, tidak hanya halaman yang sedang dilihat. Binary bukti tidak ditanamkan dalam PDF/Excel; generatedAt, period bounds, timezone dan data-as-of diberi label.
- Private export object dan download hanya pemilik sah, short expiry dan cleanup aman. **Usulan operasional non-final:** signed link 24 jam dan temporary failed files cleanup 48 jam; ukuran/retensi perlu diuji sesuai kapasitas VPS.
- Selama global recovery atau integritas belum dapat dipercaya, export resmi baru **ditunda**, dengan penjelasan status, bukan menyajikan laporan seolah terverifikasi.

## 12. MySQL-backed worker dan durable jobs

| Jenis job | Trigger dan ketentuan |
|---|---|
| Email verify/reset | hasil auth, token sekali pakai, rate-limit dan retry aman |
| Report export | immutable filter dataset, idempotent per exportJobId, private output |
| Evidence scan/finalize | object ada, verify content, status terpisah financial |
| Temporary cleanup | tidak menghapus object yang masih direferensi/unknown outcome |
| Scheduled reconciliation | compare ledger/projections; verified mismatch → freeze, bukan silent repair |
| Backup freshness / operational alerts | pemantauan off-VPS binlogs, backup, queue, disk, storage |

Queue database memiliki status, attempt count, lease/ownership, fencing dan retry/backoff; handler diasumsikan **at-least-once**, maka efek eksternal/non-idempotent harus dilindungi. Worker restart tidak membuat job hilang. Jika suatu durable job intent wajib menjadi bagian commit finansial, tulis record job **atomik** bersama commit. Network I/O/email/storage/PDF rendering tidak boleh dijalankan di dalam financial DB transaction.

### 12.1 Rust durable worker pattern (v0.2)

Worker Rust/Tokio menggunakan tabel job yang sama dengan API dan handler application/domain bersama. Lease/fencing token, penjadwalan ulang, dan hasil sukses dicatat secara transaksional. Untuk mengambil pekerjaan secara konkuren, `FOR UPDATE SKIP LOCKED` dapat dievaluasi pada MySQL yang didukung, **hanya untuk job queue**, bukan untuk melewati lock integritas finansial. Worker wajib tahan terhadap crash antara efek eksternal dan tanda completed; gunakan idempotency per jenis pekerjaan dan outbox/state retry sesuai kebutuhan. Pengiriman SMTP/operasi S3/render PDF dilakukan **di luar** transaksi DB panjang. Export PDF/Excel memakai streaming atau file temporer dengan batas ukuran/memori, bukan seluruh dataset di-buffer sebagai satu objek besar pada VPS kecil.

## 13. Production topology, observability, PITR, dan Controlled Recovery

### 13.1 Deployment Single VPS

- Docker Compose menjalankan reverse proxy HTTPS, frontend static hosting, **Rust Axum API binary**, **Rust worker binary**, dan MySQL InnoDB dalam private network. Tidak mengekspos MySQL/worker ke publik. Database persistent volume, least-privilege DB accounts, secrets di luar image dan repository.
- Private S3-compatible object storage dan backup **off-VPS**. Dev, staging, production terpisah; gunakan sanitized/non-production data untuk testing. Deploy harus meninjau backward API compatibility PWA yang mungkin belum update.
- Health/readiness checks, log terstruktur dengan request ID tanpa secrets/PII yang tidak perlu, metrics API/database/worker/queue, penggunaan disk, backup freshness, binlog gap, object storage health, financial mismatch/freeze alerts.
- Schema migration dilakukan terkontrol dengan backup dan compatibility plan; rollback aplikasi tidak boleh secara otomatis merusak ciphertext local versi sebelumnya. Security/dependency scans dan disaster drill termasuk release tasks.

**Build/deploy Rust:** gunakan reproducible, pinned Rust toolchain dan `Cargo.lock` untuk aplikasi; jalankan `cargo build --release` dalam builder/CI, kirim hanya binary terbangun + sertifikat/runtime minimum ke image final; jangan kompilasi source Rust di VPS kecil. API dan worker dapat berbagi versi image/binary jika entrypoint dipisahkan, namun tetap kontainer terpisah dengan resource limit. Build target/libc/TLS (musl vs glibc, OpenSSL vs rustls) adalah keputusan kompatibilitas yang diverifikasi pada CI/target image, bukan asumsi. Frontend Vue tetap dibangun menjadi aset statis pada build pipeline.

**Resource policy:** VPS 2 GB adalah kandidat eksperimen untuk satu pengguna, bukan baseline yang dijamin; ukur RAM idle, import/replay ledger, query laporan, worker PDF, backup dan recovery disk. Tetapkan connection pool, MySQL buffer pool, concurrency job, log rotation dan alert low disk berdasarkan hasil test. Pertahankan opsi upgrade VPS ke 4 GB bila release gates/load test gagal.

### 13.2 Daily backup + PITR off-VPS

- Daily **consistent database backup**, disertai MySQL binary logs yang dikirim/copy teratur off-VPS sehingga **target RPO ≤1 jam** masuk akal pada disk/VPS total loss. Menyimpan binlog hanya pada VPS yang sama bukan mitigasi cukup.
- Backup mencakup ledger, snapshots, audit, idempotency outcomes, borrower/account state, jobs, sessions, freeze/recovery metadata, dan referensi evidence/export. Backup encrypted, integrity checked, off-VPS IAM terpisah, retention & restore capability diuji.
- Restoration harus memeriksa ketersediaan object storage versi yang direferensikan agar file yang disebut DB tidak diam-diam hilang. Pengujian RTO dihitung dari mulai insiden/pemulihan sampai fungsi siap **sesudah** integrity sign-off; target **≤4 jam belum terbukti**.
- PITR tidak menjamin semua confirmed transaction pulih: binlog yang belum terarsip off-VPS mungkin hilang dan record idempotency untuk commit tersebut juga hilang.

### 13.3 Global Financial Recovery Mode

1. Operator memulai recovery dengan **global hold**: block financial mutation dan semua sync. Read-only history hanya jika aman dan diberi banner; export resmi baru ditahan sampai selesai validasi.
2. Restore backup + semua available valid binlog ke **titik pemulihan yang terukur**; catat `recoveredThrough`, backup IDs dan bukti integritas.
3. Verifikasi ledger replay vs materialized balance, snapshot deltas, seluruh prefix receivable, audit correlation, operation idempotency uniqueness, evidence references, dan durable jobs/sessions.
4. Rekonsiliasi transaksi yang mungkin pernah confirmed **sesudah** titik pemulihan. Bukti device acknowledgment, logs off-VPS atau sumber lain hanya dipakai setelah diverifikasi; **jangan replay otomatis** transaksi `Synced` yang tidak ada di DB hasil restore.
5. Operator berwenang menyelesaikan temuan atau mencatat ketidakpastian/kehilangan yang tidak bisa dipulihkan; controlled repair harus punya actor, alasan, bukti, before/after dan audit. Tidak ada klaim zero data loss ataupun pemulihan commit yang bukti durabelnya ikut hilang.
6. Setelah verifikasi menyeluruh dan sign-off operator, buka global hold. Financial Integrity Freeze **per akun** yang masih terbuka tetap berlaku. Sync kembali melewati validasi bisnis terkini.

**Dua mode berbeda:** Financial Integrity Freeze = spesifik akun ketika mismatch ledger/projection terverifikasi; Global Financial Recovery Mode = tingkat sistem setelah restore. Keduanya dapat aktif bersamaan.

### 13.4 Operator-only recovery workflow

MVP memakai proses restricted operator (mis. CLI/admin-only service yang diautentikasi dan diotorisasi), **bukan dashboard admin penuh**. Tidak ada tombol unfreeze bagi user. Operator log memuat alasan, lokasi insiden, langkah verifikasi, bukti, perubahan terkontrol, approval/sign-off, dan waktu server. Direct ad hoc DB editing bukan jalur normal dan tidak boleh melewati audit.

## 14. Frontend routing, UX, dan accessibility contract

### 14.1 Capability-based routes

| Route family usulan | Guard/kebijakan |
|---|---|
| `/login`, `/register`, `/forgot-password` | public/auth |
| `/verify-email` | authenticated unverified basic session |
| `/onboarding/*` | verified; opening balance/offline activation capability |
| `/app/dashboard`, `/app/transactions`, `/app/borrowers`, `/app/sync` | verified online atau authorized unlocked offline cache |
| `/app/reports`, `/app/exports` | verified dan **online-only**, no official offline cache |
| `/app/settings`, `/app/categories`, `/app/audit` | verified; mutasi tertentu online-only |
| `/unlock`, `/local-recovery` | Hybrid Lock dan strong key recovery |

Guard precedence: **owner isolation → Hard/Soft Lock → local access expiry dan server session → global/account freeze → online-only page capability → pending operation state**. Setelah unlock kembali ke route awal hanya jika masih sah. Jangan masukkan nominal/PII pada URL, browser title saat locked, atau notifikasi publik.

### 14.2 UX contracts

- Desktop: sidebar Dashboard, Transactions, Piutang, Reports, Sync Center, Settings, Audit. Mobile: bottom nav Home, Transaksi, tombol `+`, Piutang, Laporan; Sync Center melalui header.
- Quick Add: Increase, Deduct, Tambah Piutang, Terima Pembayaran. Balance Adjustment di flow tersendiri online-only, meminta target saldo, bukan delta.
- History: confirmed + pending dengan label jelas; tab History, Draft, Recently Deleted; show no-balance-impact receivable dan snapshot adjustment sebagai jenis terpisah.
- Dashboard: confirmed cash/receivables selalu saat ini, statistik dan grafik mengikuti filter. Offline summary selalu pakai timestamp last verified, dengan estimated balance hanya jika cache mencukupi.
- Form mobile fullscreen dan sticky controls aman dari keyboard/safe area. Prompt-Based Update tak force reload draft aktif. Theme Light/Dark/System.
- Konflik, storage failure, unknown result dan freeze harus mempunyai tindakan/penjelasan permanen; jangan bergantung hanya pada toast. Empty state cache incomplete tidak sama dengan histori benar-benar kosong.

### 14.3 WCAG 2.2 Level AA

Semua flow utama harus diuji keyboard, screen reader, focus management dialog, semantic form labels/errors, dynamic status announcement tanpa lompatan fokus, chart alternatives, reflow dan zoom, non-color distinction, reduced motion, dan mobile safe areas. Kontrol sentuh penting direkomendasikan target desain 44×44 CSS px **sebagai preferensi kenyamanan**, bukan klaim minimum normatif WCAG 2.2 AA. Automated accessibility tooling tidak menggantikan review manual.

## 15. Quality strategy dan acceptance

### 15.1 Test layers

| Jenis | Kewajiban pembuktian |
|---|---|
| Unit & property-based | integer overflow, chronological sequence, snapshot replay, nonnegative receivable at all prefixes, date grouping, sync state machine |
| Integration MySQL | per-user lock, deadlock rollback/retry, optimistic versioning, audit/idempotency atomicity, job leases |
| API contract | owner scope, errors, decimal-string money, timezones, consistent paging/filters |
| Browser E2E | offline create/restart, Hard Lock, Recovery Key, two tabs, cache/quota failure, PWA update, Reports offline restriction |
| Security | IDOR/tenant isolation, CSRF, refresh reuse/revoke, XSS, file type validation, secret logging |
| Accessibility | keyboard, screen reader, high zoom, touch-safe layout, WCAG 2.2 AA |
| Disaster recovery | off-VPS binlog, restore drill, controlled reconciliation, RPO/RTO measurement |

### 15.2 Rust test and static analysis strategy (v0.2)

- Unit/domain: `cargo test` terhadap ledger replay, piutang nonnegative seluruh prefix, snapshot adjustment, ordering + dependencies, range/overflow, strict money string parsing, error taxonomy; tambahkan **property-based tests** memakai crate yang dipilih pada implementasi (mis. `proptest`) tanpa menganggap acak = lengkap.
- Integration: MySQL di container khusus test dengan migrasi dari awal; test SQLx lock isolation, missing/invalid FK, unique idempotency, per-owner scope, deadlock rollback, status lookup setelah ambiguous response. Eksekusi paralel memakai database terisolasi untuk mencegah flaky financial tests.
- Quality: `cargo fmt --check`, `cargo clippy --all-targets --all-features` dengan kebijakan lint yang disepakati, `cargo test`, dependency security/advisory review, build release; tidak boleh menyatakan command sukses tanpa menjalankannya.
- API contract: periksa JSON money-as-string, timezone, status dan error mapping yang sama dengan PRD; jalankan browser Playwright secara terpisah dari tes backend.
- Load/memory: ukur RSS Axum API/worker/MySQL dan latency pada VPS 2 GB ketika concurrent requests, export, dan recovery; bandingkan dengan target operasional. Tidak boleh menyimpulkan kebutuhan VPS 1 GB cukup hanya dari bahasa Rust.

### 15.3 Fault-injection design

- Simulasikan dua request Deduct bersamaan, concurrent edit dari dua device, deadlock/timeout, crash sebelum/sesudah commit, lost HTTP response, retry identik, changed payload same attempt, dan idempotency record restore gap.
- Generate urutan activity acak (positive/cash OFF/negative cash allowed, timestamp equal, adjustment, delete, restore) lalu bandingkan materialized balance dengan ledger replay; pastikan piutang tidak negatif pada prefix mana pun.
- Simulasikan browser restart setelah draft/pending encrypted, Recovery Key hilang, PRF tidak tersedia, storage quota penuh, corrupt AEAD tag, user switch account dua tab, 7-day expiry, dan PWA update saat syncing.
- Uji file upload gagal setelah commit, scan rejection, ekspor saat concurrent edit, dan restore DB ketika object storage berisi orphan/missing reference.
- Semua hasil diuji terhadap state **persisted** dan audit, bukan hanya toast/HTTP 200.

### 15.4 Acceptance matrix: 25 skenario BRD

| AC | Kriteria integrasi yang dibuktikan |
|---|---|
| AC-01 | Skip opening balance → tidak ada snapshot dan historical mutation mengubah saldo |
| AC-02 | Opening Rp0 eksplisit → snapshot melindungi current balance dari backdate sebelumnya |
| AC-03 | Edit historical sebelum snapshot → delta berubah, target tetap, audit ada |
| AC-04 | Concurrent Deduct → tidak ada lost update, tepat dua aktivitas |
| AC-05 | Stale version edit → ditolak, history terbaru tak tertimpa |
| AC-06 | Loan cash OFF → piutang naik, cash/income tidak berubah |
| AC-07 | Historical repayment membuat piutang negatif → all-or-nothing rejection |
| AC-08 | Borrower archived lunas; correction positif → auto-reactivate dengan audit |
| AC-09 | Kategori archived → tersimpan pada history lama, tidak selectable di create |
| AC-10 | Pending memakai kategori yang archived di perangkat lain → conflict |
| AC-11 | Future effective time → server reject tanpa rewrite timestamp |
| AC-12 | Encrypted draft setelah restart → strong Hard Unlock dan restore |
| AC-13 | Offline Access off → draft hanya sesi aktif, tidak dijanjikan persisten |
| AC-14 | Lost response after commit → same attempt returns prior result, no double effect |
| AC-15 | Partial Sync → independent items commit, conflicted descendants blocked |
| AC-16 | Logout/account switch pending → warning, encrypted/isolated, tidak cross-sync |
| AC-17 | Lupa PIN + Recovery Key → decrypt ciphertext lokal yang masih ada |
| AC-18 | Restart browser → PIN saja tidak dapat melewati Hard Lock |
| AC-19 | >7 hari tanpa verifikasi server → offline block, pending retained |
| AC-20 | Reports offline → online-only message, bukan cached official report |
| AC-21 | Evidence upload fail → activity confirmed, evidence retry terpisah |
| AC-22 | Verified ledger mismatch → account freeze, operator-only repair/unfreeze |
| AC-23 | Restore PITR → global recovery hold, verifikasi dan rekonsiliasi operator |
| AC-24 | PWA update saat draft/pending → no forced reload; safe migration/hold |
| AC-25 | Change timezone → fixed instant, grouping lokal berubah + warning |

### 15.5 Release gates (P0)

- **G1 Financial:** seluruh invariant saldo/snapshot/piutang, locking, audit, property tests lulus; tidak ada known critical defect.
- **G2 Sync:** idempotency, unknown outcome, partial sync, dependency dan dua tab diuji tanpa duplicate financial effect.
- **G3 Offline Security:** Hard Unlock/Recovery Key decrypt dan fallback di browser target lulus; jika tidak tersedia, jangan klaim Offline Access aman.
- **G4 Privacy & Accessibility:** cross-account isolation, session revoke, private files, form/navigasi WCAG 2.2 AA diuji.
- **G5 Disaster Recovery:** restore drill dilakukan, hasil RPO/RTO diukur, global hold/verifikasi operator berjalan; target yang gagal tidak boleh disajikan sebagai sudah terpenuhi.

Belum ada benchmark numerik tentang throughput/concurrency/latency yang disetujui. Kapasitas, alert thresholds, dan rate limits harus ditentukan berdasarkan measurement pada fase operasional sebelum production, bukan angka rekaan.

## 16. Architecture Decision Register dan technical defaults

| ID | Status | Keputusan / kebutuhan validasi |
|---|---|---|
| ADR-01 | **Frozen (revisi v0.2 disetujui)** | Rust + Axum + Tokio modular monolith, MySQL/SQLx, Vue PWA, single VPS Docker Compose |
| ADR-01A | **Frozen (v0.2)** | Cargo workspace dengan API Axum dan worker Rust berbagi aturan domain; SQLx migrasi MySQL; frontend Vue, alur finansial, sync dan operasional tetap |
| ADR-02 | **Frozen** | satu saldo utama IDR integer, boleh negatif; piutang tidak boleh negatif |
| ADR-03 | **Frozen** | authoritative snapshot target, opening optional, adjustment server time |
| ADR-04 | **Frozen** | pessimistic per-user lock, version conflict, immutable financial sequence |
| ADR-05 | **Frozen** | partial sync, exact-once financial effect, 3 retries/cycle, foreground-first |
| ADR-06 | **Frozen** | optional offline + PIN/strong wrapping/Recovery Key, Hybrid Lock, seven-day validation |
| ADR-07 | **Frozen** | Reports online-only, pending excluded, account timezone current |
| ADR-08 | **Frozen** | Controlled Recovery, RPO ≤1 jam/RTO ≤4 jam target diuji, operator hold/unfreeze |
| ADR-09 | **Frozen** | prompt-based PWA update, previous route after unlock, WCAG 2.2 AA target |
| VAL-01 | **Feasibility gate** | browser/authenticator WebAuthn PRF, KDF/wrapping, Recovery Key restart lintas target |
| VAL-02 | **Feasibility gate** | SQLx/MySQL locking + transaction isolation, timeout/deadlock, sequence/replay scaling, query plans, compile-time query validation setup |
| VAL-04 | **Feasibility gate** | Rust image/build toolchain, API/worker MySQL pool, export memory pressure dan penggunaan RAM di VPS 2 GB |
| VAL-03 | **Feasibility gate** | verified off-VPS binlog interval, measured PITR, transaction acknowledged lost scenarios |
| DEF-01 | **Usulan teknis, belum disetujui** | access token ±15 menit; export link ±24 jam; temp cleanup ±48 jam |
| DEF-02 | **Usulan teknis, belum disetujui** | minggu Senin–Minggu; final API naming/cursor schema; strong KDF parameters |
| DEF-03 | **Usulan teknis, belum disetujui** | cache size/quota, rate limits, worker retry max, monitoring thresholds, operator access mechanism |
| DEF-04 | **Usulan teknis, belum disetujui** | Cargo crate boundaries, exact Rust/SQLx/Axum versions, SQLx compile-time verification mode, pool/timeout/worker concurrency, SQL isolation level |

**Escalation rule:** jika feasibility gate gagal, AI Agent tidak boleh menghilangkan perlindungan atau memodifikasi product scope secara diam-diam. Temuan dan fallback harus ditinjau sebelum slice terdampak dinyatakan dapat diimplementasikan.

## 17. AI Coding Agent implementation sequence (tanpa menghasilkan kode pada dokumen ini)

1. **Fase 0 — Feasibility spikes.** Validasi browser encryption/recovery, MySQL concurrency & snapshot replay, PITR/Controlled Recovery. Hasil adalah bukti eksperimen dan batasan, bukan checklist kosong.
2. **Fase 1 — Foundation & Auth.** Rust Cargo workspace, Axum + Tokio app shell, Vue app shell, API v1, SQLx migrations, sessions, verifikasi email, owner-scope tests.
3. **Fase 2 — Financial Core.** Ledger, snapshot, piutang, financial lock/version, audit, idempotency primitives, property-based tests.
4. **Fase 3 — Sync.** Partial Sync, operation lookup, dependency, conflicts, multi-tab coordination, injected failure tests.
5. **Fase 4 — Offline PWA & Key Security.** Encrypted IndexedDB, Hybrid Lock, Recovery Key/strong fallback, migration/restart tests.
6. **Fase 5 — Product flows.** Dashboard, History, Categories, Borrowers, Reports, routing, accessibility, UX states, responsive flows.
7. **Fase 6 — File & jobs.** Evidence private upload/scan, worker queue, exports with consistent dataset and access controls.
8. **Fase 7 — Production hardening.** Compose staging/prod, monitoring, backup/PITR and restore drill, security/a11y/regression, sign-off.

**Definition of Done per slice:** requirement BR/PR/AC traceable; API/browser success and failure states tested; owner isolation; input validation; rollback/retry if relevant; append-only audit if financial; accessibility when UI; no known critical mismatch. AI Agent dilarang menandai selesai semata-mata karena endpoint mengembalikan sukses.

## 18. Platform documentation references

Referensi untuk validasi implementasi, bukan bukti sudah lulus uji produksi. Dependency versions harus dipin dan diperiksa pada tahap coding.

1. Rust + Cargo: <https://doc.rust-lang.org/book/> dan <https://doc.rust-lang.org/cargo/>.
2. Axum routing/state/middleware: <https://docs.rs/axum/latest/axum/>.
3. Tokio runtime, task execution: <https://docs.rs/tokio/latest/tokio/>.
4. SQLx MySQL transactions, migrations, query macros: <https://docs.rs/sqlx/latest/sqlx/> dan <https://github.com/transact-rs/sqlx/blob/main/FAQ.md>.
5. MySQL 8.4, point-in-time recovery and binary logging: <https://dev.mysql.com/doc/refman/8.4/en/point-in-time-recovery.html> dan <https://dev.mysql.com/doc/refman/8.4/en/binary-log.html>.
6. MDN WebAuthn extension/PRF: <https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API/WebAuthn_extensions>.
7. MDN ServiceWorker update lifecycle: <https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerGlobalScope/skipWaiting>.
8. OWASP File Upload Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html>.
9. W3C WCAG 2.2 Recommendation: <https://www.w3.org/TR/WCAG22/>.

---

## Lampiran A — Traceability requirement BRD → PRD → Technical Specification

Indeks ini merupakan **pemetaan cakupan**. Identitas BRD dan PRD berasal dari dua dokumen baseline. Setiap baris mengarah ke bagian teknis yang menjadi dasar implementation tests; penetapan nama kelas/endpoint/migration tidak menggantikan kewajiban membuktikan AC.

| BRD ID | PRD IDs yang merinci | Rujukan teknis |
|---|---|---|
| `BR-AUTH-01` | PR-AUTH-01 | §6, §7, §9, §14–15 |
| `BR-AUTH-02` | PR-AUTH-02 | §6, §7, §9, §14–15 |
| `BR-AUTH-03` | PR-AUTH-03 | §6, §7, §9, §14–15 |
| `BR-AUTH-04` | PR-AUTH-08, PR-NFR-01 | §6, §7, §9, §14–15 |
| `BR-AUTH-05` | PR-AUTH-04, PR-SET-03 | §6, §7, §9, §14–15 |
| `BR-AUTH-06` | PR-AUTH-05, PR-AUTH-06 | §6, §7, §9, §14–15 |
| `BR-AUTH-07` | PR-SEC-09 | §6, §7, §9, §14–15 |
| `BR-AUTH-08` | PR-AUTH-07 | §6, §7, §9, §14–15 |
| `BR-FIN-01` | PR-TXN-03 | §3–5, §7, §15 |
| `BR-FIN-02` | PR-TXN-04 | §3–5, §7, §15 |
| `BR-FIN-03` | PR-OFF-14 | §3–5, §7, §15 |
| `BR-FIN-04` | PR-BAL-01 | §3–5, §7, §15 |
| `BR-FIN-05` | PR-BAL-01 | §3–5, §7, §15 |
| `BR-FIN-06` | PR-BAL-02, PR-BAL-03 | §3–5, §7, §15 |
| `BR-FIN-07` | PR-BAL-04 | §3–5, §7, §15 |
| `BR-FIN-08` | PR-BAL-04, PR-HIS-08 | §3–5, §7, §15 |
| `BR-FIN-09` | PR-BAL-05 | §3–5, §7, §15 |
| `BR-FIN-10` | PR-NFR-03 | §3–5, §7, §15 |
| `BR-FIN-11` | PR-BAL-06, PR-HIS-04 | §3–5, §7, §15 |
| `BR-FIN-12` | PR-NFR-11 | §3–5, §7, §15 |
| `BR-FIN-13` | PR-HIS-05, PR-NFR-02, PR-TXN-05 | §3–5, §7, §15 |
| `BR-FIN-14` | PR-NFR-03 | §3–5, §7, §15 |
| `BR-REC-01` | PR-REC-01 | §3–4, §7–8, §15 |
| `BR-REC-02` | PR-REC-01 | §3–4, §7–8, §15 |
| `BR-REC-03` | PR-REC-02 | §3–4, §7–8, §15 |
| `BR-REC-04` | PR-REC-03 | §3–4, §7–8, §15 |
| `BR-REC-05` | PR-REC-04, PR-REC-05 | §3–4, §7–8, §15 |
| `BR-REC-06` | PR-REC-05 | §3–4, §7–8, §15 |
| `BR-REC-07` | PR-REC-06 | §3–4, §7–8, §15 |
| `BR-REC-08` | PR-REC-07 | §3–4, §7–8, §15 |
| `BR-REC-09` | PR-REC-08 | §3–4, §7–8, §15 |
| `BR-REC-10` | PR-OFF-14 | §3–4, §7–8, §15 |
| `BR-REC-11` | PR-REC-10 | §3–4, §7–8, §15 |
| `BR-HIS-01` | PR-CAT-01, PR-CAT-05 | §3–4, §7, §14–15 |
| `BR-HIS-02` | PR-CAT-02, PR-HIS-07 | §3–4, §7, §14–15 |
| `BR-HIS-03` | PR-CAT-03 | §3–4, §7, §14–15 |
| `BR-HIS-04` | PR-CAT-04, PR-OFF-14 | §3–4, §7, §14–15 |
| `BR-HIS-05` | PR-HIS-01, PR-TXN-08 | §3–4, §7, §14–15 |
| `BR-HIS-06` | PR-HIS-02 | §3–4, §7, §14–15 |
| `BR-HIS-07` | PR-HIS-04, PR-HIS-05 | §3–4, §7, §14–15 |
| `BR-HIS-08` | PR-HIS-06 | §3–4, §7, §14–15 |
| `BR-HIS-09` | PR-HIS-05 | §3–4, §7, §14–15 |
| `BR-HIS-10` | PR-HIS-08, PR-NFR-04 | §3–4, §7, §14–15 |
| `BR-HIS-11` | PR-HIS-03 | §3–4, §7, §14–15 |
| `BR-OFF-01` | PR-SEC-01, PR-SET-04 | §7–9, §14–15 |
| `BR-OFF-02` | PR-SEC-01 | §7–9, §14–15 |
| `BR-OFF-03` | PR-SEC-02, PR-SEC-10 | §7–9, §14–15 |
| `BR-OFF-04` | PR-SEC-03, PR-SEC-04 | §7–9, §14–15 |
| `BR-OFF-05` | PR-SEC-04 | §7–9, §14–15 |
| `BR-OFF-06` | PR-SEC-05 | §7–9, §14–15 |
| `BR-OFF-07` | PR-SEC-06 | §7–9, §14–15 |
| `BR-OFF-08` | PR-OFF-03, PR-OFF-04, PR-REC-09, PR-TXN-06 | §7–9, §14–15 |
| `BR-OFF-09` | PR-HIS-09, PR-OFF-05 | §7–9, §14–15 |
| `BR-OFF-10` | PR-OFF-01 | §7–9, §14–15 |
| `BR-OFF-11` | PR-OFF-02, PR-OFF-13 | §7–9, §14–15 |
| `BR-OFF-12` | PR-OFF-06 | §7–9, §14–15 |
| `BR-OFF-13` | PR-NFR-02, PR-OFF-07, PR-TXN-05, PR-TXN-07 | §7–9, §14–15 |
| `BR-OFF-14` | PR-OFF-08 | §7–9, §14–15 |
| `BR-OFF-15` | PR-OFF-09 | §7–9, §14–15 |
| `BR-OFF-16` | PR-AUTH-06, PR-AUTH-08, PR-OFF-10, PR-SEC-07, PR-SET-05 | §7–9, §14–15 |
| `BR-OFF-17` | PR-OFF-11, PR-SEC-08 | §7–9, §14–15 |
| `BR-OFF-18` | PR-DASH-05, PR-DASH-06, PR-OFF-12 | §7–9, §14–15 |
| `BR-OFF-19` | PR-OFF-13, PR-SEC-06 | §7–9, §14–15 |
| `BR-RPT-01` | PR-DASH-01 | §5, §11, §14–15 |
| `BR-RPT-02` | PR-DASH-03, PR-RPT-03 | §5, §11, §14–15 |
| `BR-RPT-03` | PR-BAL-05, PR-DASH-02, PR-RPT-02 | §5, §11, §14–15 |
| `BR-RPT-04` | PR-RPT-02 | §5, §11, §14–15 |
| `BR-RPT-05` | PR-DASH-04, PR-RPT-06 | §5, §11, §14–15 |
| `BR-RPT-06` | PR-RPT-04 | §5, §11, §14–15 |
| `BR-RPT-07` | PR-RPT-05 | §5, §11, §14–15 |
| `BR-RPT-08` | PR-DASH-05, PR-RPT-01 | §5, §11, §14–15 |
| `BR-RPT-09` | PR-RPT-07 | §5, §11, §14–15 |
| `BR-RPT-10` | PR-NFR-05, PR-RPT-08, PR-RPT-09 | §5, §11, §14–15 |
| `BR-RPT-11` | PR-NFR-11, PR-RPT-10, PR-SET-02 | §5, §11, §14–15 |
| `BR-FILE-01` | PR-FILE-01 | §7, §10, §12, §15 |
| `BR-FILE-02` | PR-FILE-02 | §7, §10, §12, §15 |
| `BR-FILE-03` | PR-FILE-03, PR-HIS-03, PR-NFR-05 | §7, §10, §12, §15 |
| `BR-FILE-04` | PR-FILE-04 | §7, §10, §12, §15 |
| `BR-FILE-05` | PR-FILE-05, PR-TXN-06 | §7, §10, §12, §15 |
| `BR-FILE-06` | PR-FILE-06 | §7, §10, §12, §15 |
| `BR-UX-01` | PR-TXN-01, PR-UX-03 | §9, §14–15 |
| `BR-UX-02` | PR-TXN-02 | §9, §14–15 |
| `BR-UX-03` | PR-SET-01 | §9, §14–15 |
| `BR-UX-04` | PR-DASH-07, PR-UX-02 | §9, §14–15 |
| `BR-UX-05` | PR-UX-04 | §9, §14–15 |
| `BR-UX-06` | PR-SET-06, PR-UX-05 | §9, §14–15 |
| `BR-UX-07` | PR-A11Y-01, PR-A11Y-02, PR-A11Y-03, PR-A11Y-04, PR-DASH-04, PR-NFR-10, PR-RPT-06 | §9, §14–15 |
| `BR-UX-08` | PR-DASH-08, PR-TXN-08, PR-UX-01 | §9, §14–15 |
| `BR-OPS-01` | PR-NFR-06 | §12–13, §15 |
| `BR-OPS-02` | PR-NFR-06 | §12–13, §15 |
| `BR-OPS-03` | PR-NFR-06 | §12–13, §15 |
| `BR-OPS-04` | PR-NFR-07 | §12–13, §15 |
| `BR-OPS-05` | PR-NFR-07 | §12–13, §15 |
| `BR-OPS-06` | PR-NFR-07 | §12–13, §15 |
| `BR-OPS-07` | PR-NFR-08, PR-RPT-09 | §12–13, §15 |
| `BR-OPS-08` | PR-NFR-09 | §12–13, §15 |

## Lampiran B — Peta cakupan 120 product requirements

Setiap ID PRD dipetakan ke bagian desain teknis (sejumlah kebutuhan UX dipecah lintas backend/frontend). Detail acceptance dan wording tetap mengikuti PRD v0.1.

| Kelompok PRD | Jumlah | ID lengkap | Bagian teknis |
|---|---:|---|---|
| `PR-A11Y` | 4 | `PR-A11Y-01`, `PR-A11Y-02`, `PR-A11Y-03`, `PR-A11Y-04` | §14–15 |
| `PR-AUTH` | 8 | `PR-AUTH-01`, `PR-AUTH-02`, `PR-AUTH-03`, `PR-AUTH-04`, `PR-AUTH-05`, `PR-AUTH-06`, `PR-AUTH-07`, `PR-AUTH-08` | §6–7, §14–15 |
| `PR-BAL` | 6 | `PR-BAL-01`, `PR-BAL-02`, `PR-BAL-03`, `PR-BAL-04`, `PR-BAL-05`, `PR-BAL-06` | §4–5, §7, §15 |
| `PR-CAT` | 5 | `PR-CAT-01`, `PR-CAT-02`, `PR-CAT-03`, `PR-CAT-04`, `PR-CAT-05` | §3, §7, §14 |
| `PR-DASH` | 8 | `PR-DASH-01`, `PR-DASH-02`, `PR-DASH-03`, `PR-DASH-04`, `PR-DASH-05`, `PR-DASH-06`, `PR-DASH-07`, `PR-DASH-08` | §5, §11, §14 |
| `PR-FILE` | 6 | `PR-FILE-01`, `PR-FILE-02`, `PR-FILE-03`, `PR-FILE-04`, `PR-FILE-05`, `PR-FILE-06` | §10, §15 |
| `PR-HIS` | 9 | `PR-HIS-01`, `PR-HIS-02`, `PR-HIS-03`, `PR-HIS-04`, `PR-HIS-05`, `PR-HIS-06`, `PR-HIS-07`, `PR-HIS-08`, `PR-HIS-09` | §4, §7, §14 |
| `PR-NFR` | 11 | `PR-NFR-01`, `PR-NFR-02`, `PR-NFR-03`, `PR-NFR-04`, `PR-NFR-05`, `PR-NFR-06`, `PR-NFR-07`, `PR-NFR-08`, `PR-NFR-09`, `PR-NFR-10`, `PR-NFR-11` | §1–15 |
| `PR-OFF` | 14 | `PR-OFF-01`, `PR-OFF-02`, `PR-OFF-03`, `PR-OFF-04`, `PR-OFF-05`, `PR-OFF-06`, `PR-OFF-07`, `PR-OFF-08`, `PR-OFF-09`, `PR-OFF-10`, `PR-OFF-11`, `PR-OFF-12`, `PR-OFF-13`, `PR-OFF-14` | §8–9, §14–15 |
| `PR-REC` | 10 | `PR-REC-01`, `PR-REC-02`, `PR-REC-03`, `PR-REC-04`, `PR-REC-05`, `PR-REC-06`, `PR-REC-07`, `PR-REC-08`, `PR-REC-09`, `PR-REC-10` | §4, §7–8, §15 |
| `PR-RPT` | 10 | `PR-RPT-01`, `PR-RPT-02`, `PR-RPT-03`, `PR-RPT-04`, `PR-RPT-05`, `PR-RPT-06`, `PR-RPT-07`, `PR-RPT-08`, `PR-RPT-09`, `PR-RPT-10` | §5, §11, §15 |
| `PR-SEC` | 10 | `PR-SEC-01`, `PR-SEC-02`, `PR-SEC-03`, `PR-SEC-04`, `PR-SEC-05`, `PR-SEC-06`, `PR-SEC-07`, `PR-SEC-08`, `PR-SEC-09`, `PR-SEC-10` | §6, §9, §14–15 |
| `PR-SET` | 6 | `PR-SET-01`, `PR-SET-02`, `PR-SET-03`, `PR-SET-04`, `PR-SET-05`, `PR-SET-06` | §5, §6, §9, §14 |
| `PR-TXN` | 8 | `PR-TXN-01`, `PR-TXN-02`, `PR-TXN-03`, `PR-TXN-04`, `PR-TXN-05`, `PR-TXN-06`, `PR-TXN-07`, `PR-TXN-08` | §4, §7, §14 |
| `PR-UX` | 5 | `PR-UX-01`, `PR-UX-02`, `PR-UX-03`, `PR-UX-04`, `PR-UX-05` | §8, §14–15 |

**Validasi traceability:** 96/96 ID BRD ditemukan di indeks PRD dan tercakup di Lampiran A. 120/120 ID PRD ditemukan di Lampiran B. Seluruh 25 acceptance `AC-01`–`AC-25` dijabarkan pada §15.4. Ini validasi **cakupan rujukan dokumen**, bukan bukti implementasi sudah benar.

