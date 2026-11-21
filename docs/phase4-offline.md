# Fase 4 · Offline vault (slice 1)

Slice ini mengikuti BR-OFF-02–07, 17, 19, PR-SEC-02–06, 08, AC-17–19 dan Tech Spec §9.2–9.4. Sebagian: BR-OFF-01/16, PR-SEC-01/07 dan AC-16. Penawaran saat onboarding dan peringatan logout bila ada pending belum dibuat (UI Fase 5). **Fase 4 dan gate G3 belum selesai.** Masih terbuka: WebAuthn PRF, service worker dan prompt-based update (§9.5), migrasi store terenkripsi, engine sync klien, dan pengukuran KDF di perangkat target.

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
