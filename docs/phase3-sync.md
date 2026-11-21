# Fase 3 · Sync (slice server)

Slice ini mengikuti BR-OFF-08, 12, 13, PR-OFF-04, 06, 07, AC-15 dan Tech Spec §8.1, §8.3. Yang dikerjakan baru sisi server. Antrean klien, state lokal (`PENDING` … `SYNCED`), 3 retry otomatis per siklus dengan backoff/jitter, serta lease multi-tab belum dibuat karena bergantung pada IndexedDB terenkripsi (Fase 4). **Fase 3 dan gate G2 belum selesai.**

## Kontrak `POST /api/v1/sync/items`

Memerlukan sesi aktif, email terverifikasi, cookie dan CSRF seperti mutasi lain.

```json
{ "items": [
  { "attemptId": "…", "clientActivityId": "…", "type": "BORROWER", "name": "…", "phone": "…" },
  { "attemptId": "…", "clientActivityId": "…", "type": "ACTIVITY", "kind": "LOAN", "amount": "10",
    "effectiveAt": "…", "borrowerClientId": "<clientActivityId borrower>", "dependsOn": ["<clientActivityId>"] }
] }
```

- `type` hanya `BORROWER` atau `ACTIVITY` dengan `kind` `INCREASE`, `DEDUCT`, `LOAN`, `REPAYMENT` (BR-OFF-08). Field aktivitas lain sama dengan `POST /activities`.
- Borrower dirujuk lewat `borrowerId` (server) atau `borrowerClientId` (dibuat offline), tidak keduanya.
- `dependsOn` di sync berisi **clientActivityId** aktivitas pendahulu. Server menerjemahkannya ke ID server dan menyimpannya sebagai `dependsOn` yang sama dengan jalur online, jadi parent tidak bisa dihapus selama child aktif. Pendahulu harus lebih awal secara kronologi.
- Referensi diselesaikan hanya untuk pemilik yang sama melalui create yang sudah confirmed. Referensi milik akun lain sama dengan referensi yang tidak ada.

Setiap item masuk ke `financial::execute` yang sama dengan request online, dalam transaksi sendiri. Urutan proses: dependensi lebih dulu, lalu urutan request. Batch dijalankan di task terpisah sehingga koneksi klien yang putus tidak membatalkan batch di tengah.

Respons 200 `{ "results": [...] }` dalam urutan request:

| `status` | Tercatat? | Arti dan tindakan klien |
| --- | --- | --- |
| `CONFIRMED` | Ya | Sama persis dengan `GET /operations/{attemptId}`. |
| `REJECTED` | Ya | Konflik bisnis definitif. Koreksi memakai **attemptId baru** dan clientActivityId sama, bahkan bila payload tidak berubah. |
| `BLOCKED` | Tidak | `DEPENDENCY_BLOCKED` (parent gagal di batch ini atau belum confirmed, `blockedBy`) atau `DEPENDENCY_CYCLE`. Kirim ulang dengan attempt yang sama setelah parent beres. |
| `INVALID` | Tidak | Bentuk item salah. Child-nya ikut `BLOCKED`. |
| `RETRYABLE` | Tidak | `TEMPORARY_FAILURE`, atau freeze/recovery yang muncul di tengah batch. Retry attempt yang sama. |
| `OUTCOME_UNKNOWN` | Mungkin | Commit tidak terkonfirmasi. Cek `GET /operations/{attemptId}` dulu. |
| `NOT_PROCESSED` | Tidak | Batch berhenti setelah kegagalan non-bisnis. Kirim lagi nanti. |

Batch berhenti pada kegagalan non-bisnis pertama karena semua item berbagi lock akun. Recovery aktif → 503 `FINANCIAL_RECOVERY_ACTIVE`, akun freeze → 423, keduanya sebelum item diproses. Envelope kosong, lebih dari 50 item, ID bukan UUID v4, atau `clientActivityId`/`attemptId` ganda → 422. Body di atas 64 KiB → 413.

**Usulan, dapat direview:** batas 50 item dan 64 KiB, serta nama status `BLOCKED`/`INVALID`/`RETRYABLE`/`NOT_PROCESSED`/`DEPENDENCY_CYCLE`.

## Verifikasi

| Pemeriksaan | Hasil lokal |
| --- | --- |
| `cargo test --locked` | 7 uji unit lulus, termasuk urutan dependensi, cycle, dan parsing item offline. |
| `python -B tests/phase1_auth.py --financial` (`tests/phase3_sync.py`) | Lulus pada MySQL 8.x sementara. |
| AC-15 | Batch 10 item dengan child sebelum parent: borrower offline, loan dan repayment via `borrowerClientId`/`dependsOn`, konflik waktu masa depan, child-nya `BLOCKED`, item invalid, referensi hilang, dua item independen. Total saldo/piutang tepat, `dependsOn` tersimpan, `reconcile` → `frozen=false`. Kirim ulang batch tidak mengubah apa pun. Koreksi parent dengan attempt baru, lalu child dengan attempt lama → confirmed. |
| Respons hilang | Klien memutus koneksi sebelum dan selama proses (lock akun ditahan 1,5 detik). Kasus kedua: 3/3 item tetap commit, lookup cocok, kirim ulang confirmed sekali. Uji mutasi: tanpa `tokio::spawn` kasus ini gagal (0/3). |
| Dua tab | Batch sama dari 4 thread → hasil identik, efek sekali. Satu clientActivityId dengan 4 attempt → 1 `CONFIRMED`, 3 `ALREADY_CONFIRMED_ACTIVITY`. |
| Envelope, owner scope, recovery | 422/413 sesuai di atas. Bob tidak bisa merujuk borrower Alice lewat clientActivityId (`BLOCKED`) maupun ID server (`NOT_FOUND`). Recovery aktif → 503, tidak ada yang tercatat. |
| `cargo fmt`, `cargo clippy -D warnings`, `cargo build --locked --release` | Lulus. |

Belum dijalankan: engine sync klien dan state lokal, 3 retry per siklus, lease multi-tab, browser E2E, serta deadlock MySQL 1213 sejati. Catatan: endpoint tunggal (`POST /activities` dll.) tidak memakai spawn. Bila klien putus, transaksi di-rollback, kecuali saat commit sudah terkirim, yang ditangani lewat lookup `/operations`.
