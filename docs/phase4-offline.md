# Fase 4 · Offline vault (slice 1)

Slice ini mengikuti BR-OFF-02–07, 17, 19, PR-SEC-02–06, 08, AC-17–19 dan Tech Spec §9.2–9.4. Sebagian: BR-OFF-01/16, PR-SEC-01/07 dan AC-16. Penawaran saat onboarding dan peringatan logout bila ada pending belum dibuat (UI Fase 5). **Fase 4 dan gate G3 belum selesai.** Masih terbuka: WebAuthn PRF, service worker dan prompt-based update (§9.5), migrasi store terenkripsi, dan pengukuran KDF di perangkat target. Engine sync klien sudah ada (bagian terakhir dokumen ini).

**PRF ditunda.** Fase 0 mencatat `PRF disabled (platform)` di authenticator bawaan perangkat pemilik, jadi jalur wajib di slice ini adalah passphrase kuat + Recovery Key. Wrapper disimpan sebagai set berkunci (`passphrase`, `recovery`), sehingga wrapper PRF dapat ditambahkan nanti tanpa migrasi. Gate PRF Fase 0 tetap terbuka. Catatan Fase 0 juga belum memuat nama dan versi browser, versi OS, serta model authenticator. Data itu hanya bisa dilengkapi pemilik.

## Desain

| Bagian | Implementasi |
| --- | --- |
| DEK | AES-256-GCM acak per akun per perangkat (`frontend/src/vault/crypto.ts`). Hanya ada di memori JS tab ini sebagai `CryptoKey` non-extractable. Tidak pernah ke IndexedDB, Pinia state, localStorage, BroadcastChannel atau log. Reload atau tab baru = Hard Lock. |
| Wrapper | Passphrase: PBKDF2-SHA-256, salt 16 byte, 600.000 iterasi. Recovery Key: 256 bit acak, Crockford base32 52 karakter, langsung sebagai KEK. AAD wrapper mengikat schema, owner, device dan jenis wrapper. |
| Record | IndexedDB `duitlog-vault-<owner>`, store `meta` dan `records`. Setiap record AES-GCM dengan nonce 12 byte baru dan AAD `[schema, owner, device, type, id]`. Enkripsi selesai dulu, lalu semua `put` dalam satu transaksi `durability: 'strict'`. Simpan dianggap berhasil hanya setelah `oncomplete`. |
| PIN | Hash PBKDF2 (100.000 iterasi) dienkripsi di bawah DEK, jadi hanya terbaca setelah unlock kuat. PIN membuka Soft Lock selama DEK masih di memori dan tidak mendekripsi apa pun. 5 PIN salah → Hard Lock. |
| Soft Lock | 5 menit tanpa input, dicek berdasarkan timestamp pada timer, `focus` dan `visibilitychange`. Halaman di-unmount, bukan ditutup overlay. |
| Hard Lock | Restart, reload, tab baru, `pagehide` (termasuk masuk back/forward cache), logout, 401, atau akun lain. Logout atau login di tab lain ikut mengunci tab ini. |
| 7 hari | `verifiedAt` dan `seenAt` dienkripsi. Lewat 7 hari atau jam mundur lebih dari 5 menit dari `seenAt` → baca dan tulis ditahan, ciphertext tetap. Hanya respons `/me` live dari owner sama yang memperbarui. |
| Offline boot | localStorage hanya menyimpan UUID owner vault yang terakhir dibuka (`duitlog.offline.owner`), ditulis saat setup dan setiap unlock kuat. Bila server tidak terjangkau (bukan 401), `/offline` tetap terbuka ke Hard Lock. |
| Database | Dibuat hanya saat setup. Pengguna tanpa Akses Offline tidak mendapat database IndexedDB. Open yang ter-block dilaporkan sebagai error penyimpanan. Tab lain melepas koneksinya saat vault dihapus. Browser diminta `navigator.storage.persist()` saat setup, tetapi boleh menolak. |
| Setup | Tidak ada yang tersimpan sebelum Recovery Key diketik ulang. Meta ditulis dengan `add`, sehingga setup tidak pernah menimpa vault yang ada. Vault tanpa wrapper tetapi dengan record → status `corrupt`, tanpa setup baru. |
| Rotasi | Ganti passphrase atau Recovery Key memerlukan passphrase saat ini. DEK di-unwrap extractable sementara, lalu meta diganti dalam satu tulis atomik. Ciphertext tidak disentuh. |
| Hapus | Ketik `HAPUS`. Menghapus database owner ini saja. |

**Usulan, dapat direview:** parameter PBKDF2, aturan passphrase (≥12 karakter, tidak memuat PIN), batas 5 percobaan PIN, toleransi jam 5 menit.

Hook uji `window.__duitVault` hanya ada pada build DEV. Build produksi diperiksa: 0 kemunculan di `frontend/dist`.

## Verifikasi

```powershell
python -B tests/phase1_auth.py --financial --browser 'C:\Program Files\Google\Chrome\Application\chrome.exe' --offline
```

Chrome headless dengan profil sementara yang di-restart betulan (`Browser.close`, profil sama). Jam digeser lewat skrip CDP yang mengganti `Date.now`, tanpa kode jam di aplikasi.

| Kasus | Hasil |
| --- | --- |
| Setup | Tidak ada database sebelum setup. PIN, passphrase, Recovery Key dikonfirmasi. IndexedDB mentah dan localStorage tidak berisi plaintext maupun `CryptoKey`. Nilai uang `9007199254740993` utuh. |
| Soft Lock | Halaman ter-unmount setelah 5 menit dan akses record `LOCKED`. PIN salah ditolak, PIN benar membuka. 5 kali salah → Hard Lock. |
| Hard Lock (AC-18) | Restart dengan API diblokir: halaman Hard Lock, input PIN tidak ada, Recovery Key salah ditolak, Recovery Key benar membuka semua record. |
| Recovery Key (AC-17) | Lupa PIN → unlock dengan Recovery Key → PIN baru. PIN lama ditolak, PIN baru membuka. |
| Rotasi | Passphrase dan Recovery Key lama gagal, yang baru membuka, record utuh. |
| 7 hari (AC-19) | Lewat 7 hari dan jam mundur: baca dan tulis `EXPIRED`, jumlah record tetap, terbuka lagi setelah validasi online. |
| Integritas | Ciphertext yang diubah → `CORRUPTED`, bukan kosong. Ciphertext yang dipindah ke ID lain dalam vault yang sama → `CORRUPTED` (AAD). Meta dihapus → status `corrupt` tanpa form setup, jumlah record tetap. |
| Dua tab | Tab baru mulai Hard Lock. Logout di tab lain mengunci tab ini. Hapus vault saat tab lain membukanya tetap selesai, dan tab lain menampilkannya sebagai hilang. |
| 401 | Semua sesi dicabut dari luar → aksi berikutnya mendapat 401 → Hard Lock. |
| Isolasi akun (AC-16) | Akun B punya vault sendiri. Record A yang disalin ke store B ditolak (`CORRUPTED`). Hapus memerlukan `HAPUS` dan hanya menghapus vault B. Vault A tetap terbuka dengan passphrase A. Restart offline sesudahnya tetap menemukan vault A. |
| Kuota | **Tidak teruji.** `Storage.overrideQuotaForOrigin` tidak membuat tulis 8 MB gagal di Chrome 157 headless. |
| `npm run build`, `npm audit` | Lulus, 0 vulnerability. |
| Stabilitas | Sebelum perbaikan, pembuatan database saat navigasi kadang macet (2 dari 4 run). Sesudah perbaikan: suite offline lulus 8 kali berturut-turut dan suite penuh (`--financial --browser --offline`) lulus 2 kali. Race klik "Keluar" di smoke Fase 1 juga diperbaiki. |

Belum dijalankan: PRF, kuota penuh nyata, browser selain Chrome desktop, perangkat mobile target, pengukuran PBKDF2 di HP, audit aksesibilitas manual. Enkripsi ini tidak melindungi dari XSS saat data terbuka, browser/OS yang disusupi, atau storage yang sudah terhapus (§9.1).

## Engine sync klien

Mengikuti BR-OFF-09, 12–15, sebagian BR-OFF-16 (pending tidak dikirim lewat sesi akun lain), PR-OFF-04–09 dan Tech Spec §8.2–8.3. Kode: `frontend/src/sync/engine.ts` (Pinia `useSync`), halaman `/sync` (`SyncPage.vue`).

| Bagian | Implementasi |
| --- | --- |
| Antrean | Setiap item adalah record vault `pending` dengan ID = `clientActivityId`, jadi terenkripsi seperti record lain. Payload disimpan sekali saat enqueue sebagai field wire yang diizinkan saja, dan dikirim ulang apa adanya. Uang selalu string desimal. `Number` ditolak. |
| State | `PENDING`, `SYNCING`, `CHECKING_OUTCOME`, `RETRY_WAITING`, `CONFLICT`, `BLOCKED`, `SYNCED`. `SYNCING` ditulis sebelum request dikirim. Bila tab mati di tengah, item itu dicek lewat `GET /operations/{attemptId}` pada siklus berikutnya. |
| Hasil | Dipetakan menurut `status`, bukan `code`. `CONFIRMED` → `SYNCED`. `REJECTED`/`INVALID` → `CONFLICT`. `BLOCKED` → `BLOCKED`. `RETRYABLE TEMPORARY_FAILURE` → `RETRY_WAITING`. Freeze/recovery → `PENDING` dan siklus berhenti. `OUTCOME_UNKNOWN`, `FAILED` atau status tak dikenal → `CHECKING_OUTCOME`. |
| Envelope | Hanya penolakan ber-`code` berstatus 4xx, atau 503 `FINANCIAL_RECOVERY_ACTIVE`/`TEMPORARY_FAILURE`, yang dianggap bukti tidak ada item yang diproses. Item kembali `PENDING` (atau `RETRY_WAITING` untuk `TEMPORARY_FAILURE`/429). Sisanya (500, timeout, error jaringan, 5xx tanpa `code`) berarti hasil tidak diketahui: `CHECKING_OUTCOME`, lalu lookup. 404 lookup → kirim ulang attempt yang sama. |
| Siklus | Hanya saat tab terlihat, online, vault terbuka dan belum kedaluwarsa, email terverifikasi, dan sesi milik owner vault. Maksimal 3 percobaan per siklus dengan backoff eksponensial + jitter. Konflik bisnis tidak pernah dikirim ulang otomatis. Child `BLOCKED` yang parent lokalnya `CONFLICT` juga tidak dikirim. Pemicu: unlock, event `online`, tab terlihat, timer 30 detik, dan setelah enqueue. Setelah siklus gagal, timer menunggu cooldown. |
| Owner | Envelope membawa `owner` vault. Server menolak bila sesi milik akun lain (`SESSION_OWNER_MISMATCH`), dan klien langsung Hard Lock tanpa mengubah item. |
| Multi-tab | Satu siklus per owner lewat Web Lock `duitlog-sync-<owner>` (`ifAvailable`). Tab lain melewatkan siklusnya. Idempotensi server tetap pengaman terakhir. |
| Koreksi dan batal | Hanya untuk `PENDING`, `CONFLICT`, `BLOCKED`, di bawah lock yang sama. Koreksi selalu memakai attemptId baru dengan clientActivityId sama. Item yang jawabannya pernah hilang (`unsure`) tidak bisa diubah sampai lookup memberi `CONFIRMED`/`REJECTED`, atau lookup 404 setelah 10 menit, karena batch server tetap berjalan setelah request hilang. Batal parent yang masih punya child ditolak. |
| Lock vault | Item terdekripsi hanya ada di memori selama vault terbuka, dan dikosongkan pada Soft/Hard Lock. Lock di tengah siklus menghentikannya. Record yang gagal didekripsi ditampilkan sebagai rusak, bukan antrean kosong. |

**Usulan, dapat direview:** "3 retry per siklus" ditafsirkan sebagai 3 percobaan total. Juga: backoff 500 ms × 2ⁿ dengan jitter, cooldown 60 detik berlipat sampai 15 menit, timeout kirim 20 detik dan lookup 10 detik, settle 10 menit, timer 30 detik, item `SYNCED` dihapus setelah 24 jam, batas 8 KiB per item dan potongan batch 50 item / 60 KiB. `ALREADY_CONFIRMED_ACTIVITY` ditampilkan sebagai `CONFLICT`, bukan dianggap tersinkron, supaya pengguna memeriksa isiannya.

Hook uji `window.__duitSync` hanya ada pada build DEV (0 kemunculan di `frontend/dist`).

### Verifikasi

`tests/phase4_sync_client.py`, dijalankan oleh `--offline`. Chrome headless memakai API dan MySQL sungguhan. Intersepsi lewat CDP `Fetch`, offline lewat `Network.emulateNetworkConditions`.

| Kasus | Hasil |
| --- | --- |
| Offline → online | Ditulis offline: borrower, loan via `borrowerClientId`, repayment bergantung pada loan, dua item independen (satu `9007199254740993`), konflik waktu masa depan, dan child-nya. Tidak ada request selama offline. Online → satu request, parent sebelum child, hasil `SYNCED` ×5, `CONFLICT`, `BLOCKED`. Saldo dan piutang server tepat. |
| Validasi enqueue | Nominal `Number`, jenis `ADJUSTMENT`, dan field tak dikenal ditolak. |
| Konflik | Siklus ulang tidak mengirim apa pun. Koreksi → attemptId baru, lalu parent dan child `SYNCED`. Attempt lama tetap `REJECTED` di server. Item `SYNCED` tidak bisa dikoreksi. |
| Respons hilang | Respons digagalkan setelah server commit → lookup → `SYNCED`, 1 request, efek sekali. |
| Crash | Request ditahan sebelum keluar, halaman di-reload. Server 404, unlock → kirim ulang attempt yang sama sekali, efek sekali. |
| Gangguan sementara | 503 `TEMPORARY_FAILURE` (disuntik lewat CDP) → tepat 3 request, lalu `RETRY_WAITING`. Tidak ada request lagi selama 4 detik, tidak ada yang tercatat. Siklus manual → `SYNCED`. |
| 500 | `INTERNAL_ERROR` (disuntik) → `CHECKING_OUTCOME`, lookup, lalu attempt yang sama dikirim ulang. Efek sekali. |
| Potongan batch | 52 item offline → 2 request (50 + 2). Child di request kedua, parent di request pertama. Semua `SYNCED`. |
| Owner | Body membawa owner vault. Jawaban `SESSION_OWNER_MISMATCH` (disuntik; penolakan server sungguhan diuji di Fase 3) → Hard Lock, antrean terdekripsi kosong, tidak ada yang tercatat. Setelah unlock → `SYNCED`. |
| In-flight | Jawaban `FAILED` palsu → `unsure`. Batal ditolak (`IN_FLIGHT`) dan tombol tidak tampil. Batal parent dengan child ditolak. Setelah 10 menit (jam digeser), lookup membersihkannya dan batal berhasil. |
| Dua tab | Dua tab terbuka dan online bersamaan → 1 request, efek sekali. Satu tab saat itu tersembunyi, jadi kasus ini belum menguji perebutan lock. Uji lock-nya: lease yang ditahan tab lain membuat tab ini tidak mengirim, dan setelah dilepas → `SYNCED`. Tab tersembunyi tidak sync. |
| Hard Lock | Saat terkunci dan online tidak ada request. Setelah unlock → `SYNCED`. `integrity-status` tidak freeze. |

Suite penuh (`--financial --browser --offline`) lulus 3 kali berturut-turut.

Tidak diuji di browser: `RETRYABLE`/`OUTCOME_UNKNOWN`/`NOT_PROCESSED` per item, freeze atau recovery sungguhan, 401 di tengah siklus, lookup gagal karena jaringan, Soft Lock atau kedaluwarsa di tengah siklus, record antrean rusak di `/sync`, penghapusan `SYNCED` setelah 24 jam, dan pergantian cookie ke akun lain sungguhan.

**Batas:** `GET /operations/{id}` tidak membawa owner. Bila sesi berganti akun di tengah siklus, 404 dari akun lain dapat membersihkan `unsure` setelah 10 menit. Kirim ulang tetap ditolak server (`SESSION_OWNER_MISMATCH`), jadi tidak ada efek finansial.

Belum: UI untuk mencatat transaksi offline dan mengoreksi konflik (Fase 5, saat ini hanya lewat hook uji), saldo estimasi lokal (BR-OFF-18, PR-OFF-12), peringatan logout bila ada pending, notifikasi lintas tab saat antrean berubah, dan uji di browser selain Chrome desktop. **G2 belum ditutup:** perlu review kontrak ini, uji deadlock 1213 sejati, dan alur end-to-end dari UI Fase 5.
