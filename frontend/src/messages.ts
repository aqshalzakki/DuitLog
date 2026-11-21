/** User-facing text for server and vault codes. */
export const REASONS: Record<string, string> = {
  INVALID_FUTURE_EFFECTIVE_TIME: 'Waktu efektif berada di masa depan.',
  DEPENDENCY_BLOCKED: 'Menunggu aktivitas pendahulu.',
  ALREADY_CONFIRMED_ACTIVITY: 'Aktivitas ini sudah tercatat dari percobaan lain. Periksa riwayat sebelum membatalkan.',
  CATEGORY_ARCHIVED: 'Kategori sudah diarsipkan.',
  BORROWER_ARCHIVED: 'Peminjam sudah diarsipkan.',
  RECEIVABLE_NEGATIVE: 'Kronologi membuat piutang negatif.',
  VALIDATION_ERROR: 'Isian tidak valid.',
  OPENING_REQUIRED: 'Tentukan saldo awal terlebih dahulu.',
  TEMPORARY_FAILURE: 'Layanan sibuk, akan dicoba lagi.',
  FINANCIAL_INTEGRITY_FROZEN: 'Akun sedang dalam pemeriksaan integritas. Sinkronisasi ditahan.',
  FINANCIAL_RECOVERY_ACTIVE: 'Pemulihan finansial sedang berlangsung. Sinkronisasi ditahan.',
  SESSION_OWNER_MISMATCH: 'Sesi aktif milik akun lain. Tidak ada yang disinkronkan.',
  CORRUPTED: 'Data offline rusak atau tidak dapat diverifikasi. Antrean tidak ditampilkan.',
  LOCKED: 'Data offline terkunci.',
  EXPIRED: 'Validasi online diperlukan.',
  OPENING_ALREADY_DECIDED: 'Saldo awal sudah ditentukan.',
  NOT_FOUND: 'Data tidak ditemukan.',
  VERSION_CONFLICT: 'Data telah berubah di perangkat lain. Muat ulang versi terbaru.',
  INVALID_ACTIVITY_STATE: 'Tindakan ini tidak berlaku untuk transaksi dalam keadaan sekarang.',
  BORROWER_OUTSTANDING: 'Peminjam masih memiliki piutang. Arsip hanya untuk yang sudah lunas.',
  INVALID_AMOUNT: 'Nominal harus Rupiah bulat lebih dari Rp0.',
  STORAGE: 'Tidak dapat menyimpan di perangkat. Tidak ada yang tersimpan.',
}

/** Audit action labels, shared by the Audit page and a transaction's related audit. */
/** Why the worker refused a stored evidence file (audit `details.reason`). */
export const EVIDENCE_REASONS: Record<string, string> = {
  CHANGED: 'isi berkas berubah setelah diunggah', STRUCTURE: 'berkas rusak atau tidak utuh', MISSING: 'berkas tidak ditemukan',
}

export const ACTIONS: Record<string, string> = {
  ACTIVITY_CREATED: 'Transaksi dicatat', ACTIVITY_EDITED: 'Transaksi diubah', ACTIVITY_DELETED: 'Transaksi dihapus',
  ACTIVITY_RESTORED: 'Transaksi dipulihkan', BALANCE_ADJUSTMENT: 'Penyesuaian saldo', OPENING_BALANCE: 'Saldo awal',
  OPENING_SKIPPED: 'Saldo awal dilewati', BORROWER_CREATED: 'Peminjam ditambahkan', BORROWER_EDITED: 'Peminjam diubah',
  BORROWER_ARCHIVED: 'Peminjam diarsipkan', BORROWER_REACTIVATED: 'Peminjam diaktifkan kembali',
  CATEGORY_CREATED: 'Kategori ditambahkan', CATEGORY_RENAMED: 'Kategori diganti nama', CATEGORY_ARCHIVED: 'Kategori diarsipkan',
  CATEGORY_RESTORED: 'Kategori diaktifkan kembali', INTEGRITY_FREEZE: 'Pemeriksaan integritas dimulai',
  INTEGRITY_UNFREEZE: 'Pemeriksaan integritas selesai', TIMEZONE_CHANGED: 'Zona waktu akun diubah',
  DEFAULT_CATEGORIES_CREATED: 'Kategori default dibuat', EVIDENCE_ATTACHED: 'Bukti dilampirkan',
  EVIDENCE_VERIFIED: 'Bukti lolos pemeriksaan', EVIDENCE_REJECTED: 'Bukti ditolak saat pemeriksaan',
  EVIDENCE_REMOVED: 'Bukti dilepas',
}
