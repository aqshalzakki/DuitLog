# Fase 6 (slice 1): Bukti transaksi online

Cakupan: BR-FILE-01..06, PR-FILE-01..06, AC-21. Satu bukti opsional per aktivitas yang sudah dikonfirmasi server: JPG, PNG, WebP, atau PDF, paling besar 10 MB. Bukti disimpan privat di penyimpanan objek S3-compatible dan terpisah dari commit finansial.

Belum termasuk: bukti offline terenkripsi, ekspor PDF/Excel, pembersihan objek yatim, dan pemindaian malware.

## Alur

1. Aktivitas dibuat lewat jalur finansial biasa. Bukti tidak ikut transaksi finansial itu.
2. Klien mengirim `PUT /api/v1/activities/{id}/evidence/{uploadId}`:
   - body berisi isi berkas;
   - `Content-Type` adalah jenis yang diklaim;
   - `X-Duit-File-Name` berisi nama berkas dalam percent-encoding;
   - `uploadId` berupa UUIDv4 dari klien dan menjadi identitas retry. Retry dengan id yang sama hanya disimpan sekali.
3. Server menahan paling banyak 10 MB dalam memori, dengan dua slot bersamaan dan batas baca 60 detik. Server lalu memeriksa:
   - tanda tangan berkas;
   - jenis yang diklaim;
   - ekstensi;
   - struktur dasar berkas (rantai chunk PNG, penutup JPEG, ukuran RIFF WebP, `%%EOF` pada PDF).

   Berkas yang ditolak mendapat 422 `EVIDENCE_REJECTED` dengan `conflictDetails.reason` berisi `EMPTY`, `TOO_LARGE`, `TYPE`, `NAME`, atau `STRUCTURE`.
4. Objek ditulis ke S3 lebih dulu. Setelah itu satu transaksi MySQL pendek berjalan:
   - mengunci baris aktivitas;
   - menandai bukti lama sebagai `REMOVED`;
   - menyisipkan baris `QUARANTINED`;
   - mencatat audit `EVIDENCE_ATTACHED`.

   Tidak ada panggilan jaringan selama transaksi itu.
5. Worker membaca ulang objek dan memeriksa ukuran, SHA-256, jenis, dan struktur. Hasilnya `AVAILABLE` (audit `EVIDENCE_VERIFIED`) atau `REJECTED` (audit `EVIDENCE_REJECTED`). Lease dan status `QUARANTINED` mencegah dua worker menulis hasil yang sama.
6. Unduhan hanya untuk bukti `AVAILABLE`. Hash diperiksa ulang saat unduh. Respons dikirim sebagai attachment dengan `Content-Security-Policy: sandbox; default-src 'none'`, `no-store`, dan `nosniff`.
7. `DELETE` melepas bukti: status menjadi `REMOVED` dan tercatat di audit `EVIDENCE_REMOVED`. Objeknya tetap disimpan karena MVP tidak menghapus permanen.

## Aturan dan penolakan

- **Kepemilikan:** setiap query dibatasi per pemilik. Aktivitas milik orang lain mendapat 404.
- **Kunci objek:** `ev/` + SHA-256 dari `owner:uploadId`.
- **Satu bukti aktif per aktivitas:** dijaga oleh kolom generated `active_activity` dengan constraint UNIQUE.
- **Aktivitas terhapus:** unggah dan hapus bukti mendapat 409 `INVALID_ACTIVITY_STATE`. Bukti yang sudah ada tetap bisa dibaca.
- **Freeze atau Financial Recovery Mode:** unggah dan hapus bukti ditolak seperti mutasi lain.
- **Penyimpanan objek mati:** respons 503 `TEMPORARY_FAILURE` dengan `retryable: true`. Transaksi finansial tetap terkonfirmasi (AC-21), dan retry dengan `uploadId` yang sama aman.
- **Worker saat penyimpanan mati:** worker menunda pemeriksaan dengan backoff 5 detik × 2ⁿ, paling lama 1 jam.

## UI

- Form catat bisa melampirkan bukti saat membuat transaksi online. Bukti diunggah setelah transaksi terkonfirmasi. Kalau unggah gagal, ada tombol "Coba unggah lagi" dan "Buka detail". Transaksinya tidak dibatalkan.
- Halaman detail aktivitas punya panel Bukti:
  - status berkas, diperbarui otomatis selama pemeriksaan berjalan;
  - "Lihat" untuk pratinjau gambar dan "Unduh";
  - "Ganti bukti" dan "Hapus bukti" (dengan konfirmasi);
  - "Coba lagi" yang memakai ulang `uploadId`.
- Audit menampilkan nama berkas dan alasan penolakan. Pemeriksaan worker tercatat sebagai aktor "Sistem".

## Konfigurasi

| Variable | Fungsi |
| --- | --- |
| `DUIT_S3_ENDPOINT` | URL endpoint S3 (path-style). HTTP polos hanya diizinkan untuk loopback. |
| `DUIT_S3_BUCKET` | Bucket privat. |
| `DUIT_S3_REGION` | Default `us-east-1`. |
| `DUIT_S3_ACCESS_KEY`, `DUIT_S3_SECRET_KEY` | Kredensial SigV4. API dan worker memerlukan keduanya. |

`api init-storage` membuat bucket bila belum ada. `tests/dev_local.py` dan test suite menjalankan SeaweedFS `chrislusf/seaweedfs:4.53` lewat Docker, jadi Docker harus berjalan.

## Batasan yang diketahui

- Pemeriksaan isi hanya mencakup tanda tangan dan struktur. Tidak ada decode piksel penuh atau pemindaian malware.
- Objek yang diganti atau dilepas tidak pernah dihapus, dan objek yatim dari unggahan yang gagal setelah S3 PUT tidak dibersihkan. Pembersihan menunggu job cleanup di slice berikutnya.
- Bukti untuk aktivitas offline/pending belum didukung. Bukti hanya bisa dilampirkan setelah aktivitas tersinkron, dari halaman detail.
