# Fase 2 · Financial Core

Kontrak kerja mengikuti BR-FIN-01–14, BR-REC-01–10, BR-HIS-02/06–10 dan BR-OFF-13. Cakupan PR-BAL-01–06, PR-TXN-03–05, PR-REC-01–08, PR-HIS-04–08 serta AC-01–09, AC-11, AC-14 dan AC-22. Sync batch, tampilan History/Reports, penyimpanan offline, bukti, dan prosedur operator produksi mengikuti fase berikutnya.

Semua API keuangan berada di `/api/v1`, memerlukan sesi aktif dan email terverifikasi. Semua request mutasi memakai cookie dan kebijakan CSRF Fase 1. Mutasi menerima `attemptId` dan `clientActivityId` UUID. Operasi koreksi memakai `expectedVersion`. Koreksi aktivitas memakai payload pengganti lengkap agar nilai kosong dan perubahan eksplisit jelas. Snapshot dibuat lewat onboarding atau balance adjustment, dengan waktu server dan target yang dipertahankan saat replay. Nilai uang berupa string desimal kanonik. Timestamp RFC 3339 memakai presisi mikrodetik.

| Method dan path | Input selain identitas operasi |
| --- | --- |
| GET /financial-state | Saldo, total piutang, versi, status opening dan hold. |
| GET /onboarding | Status keputusan opening. |
| POST /onboarding/opening-balance | `targetBalance`. |
| POST /onboarding/skip-opening-balance | Identitas operasi saja. |
| POST /balance-adjustments | `targetBalance`. |
| POST /activities | `kind`, `amount`, `effectiveAt`, opsional `title`, `description`, `categoryId`, `borrowerId`, `affectCashBalance`, `dependsOn` berisi ID aktivitas pendahulu. |
| PATCH /activities/{id} | Payload aktivitas dan `expectedVersion`. |
| DELETE /activities/{id} | `expectedVersion` dan `reason` opsional. |
| POST /activities/{id}/restore | `expectedVersion`. |
| GET /activities/{id} | Detail aktivitas milik akun, termasuk soft delete. |
| GET /activities | Riwayat owner-scoped; cursor dan pilihan recently deleted. |
| GET /borrowers, GET /borrowers/{id} | Profil borrower dan outstanding turunan. |
| POST /borrowers, PATCH /borrowers/{id} | `name`, `phone` dan `notes` opsional; edit memakai `expectedVersion`. |
| POST /borrowers/{id}/archive, POST /borrowers/{id}/reactivate | `expectedVersion`. |
| GET /categories, POST /categories, PATCH /categories/{id} | Kategori owner-scoped, `name`; edit memakai `expectedVersion`. |
| POST /categories/{id}/archive, POST /categories/{id}/restore | `expectedVersion`. |
| GET /audit | Audit owner-scoped berdasarkan action time. |
| GET /operations/{attemptId} | Hasil yang tercatat untuk owner; 404 berarti belum ada bukti hasil pada database yang sedang diakses. |
| GET /integrity-status | Status freeze akun dan hold global. |

Replay yang identik mengembalikan hasil tersimpan. Payload berbeda untuk attempt yang sama ditolak. Attempt baru untuk logical create yang sudah confirmed tidak menciptakan aktivitas kedua. Business rejection yang tervalidasi disimpan tanpa efek finansial. Bentuk mutasi dan lookup memakai outcome yang sama dengan versi dan keadaan pada saat keputusan dibuat.

## Verifikasi

```powershell
python -B tests/phase1_auth.py --financial
```

| Pemeriksaan | Hasil lokal |
| --- | --- |
| `cargo fmt --all -- --check` | Lulus. |
| `cargo clippy --locked --all-targets -- -D warnings` | Lulus. |
| `cargo test --locked` | 4 uji domain lulus: replay snapshot, prefix piutang dan dependensi, overflow uang, proyeksi kas acak. |
| `python -B tests/phase1_auth.py --financial` | Lulus pada MySQL 8.x sementara: opening/skip, backdate sebelum snapshot, tie timestamp, adjustment, edit/delete/restore dengan versi, kategori diarsipkan, piutang negatif ditolak, arsip/reaktivasi borrower dengan audit, waktu masa depan, overflow, idempotensi dan lookup operasi, dua tulis paralel, rollback saat audit gagal, integrity freeze dan unfreeze operator, recovery hold global, isolasi pemilik. |

Belum dijalankan: `cargo build --release`, uji deadlock yang disuntikkan, property test di atas MySQL, serta beban konkurensi lebih dari dua penulis.
