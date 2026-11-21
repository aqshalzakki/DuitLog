// Transaction evidence (PR-FILE-01..06). Uploaded only after the activity is confirmed; its status is
// separate from the financial state, and only AVAILABLE evidence can be opened.
import { ApiError, useAuth } from './session'

export const MAX_BYTES = 10 * 1024 * 1024
export const ACCEPT = '.jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf'
const EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'pdf']

export type Evidence = {
  id: string
  status: 'QUARANTINED' | 'AVAILABLE' | 'REJECTED'
  fileName: string
  contentType: string
  size: number
  createdAt: string
}

export const EVIDENCE_STATES: Record<Evidence['status'], string> = {
  QUARANTINED: 'Sedang diperiksa',
  AVAILABLE: 'Bukti tersedia',
  REJECTED: 'Ditolak saat pemeriksaan',
}

const REFUSALS: Record<string, string> = {
  EMPTY: 'Berkas kosong.',
  TOO_LARGE: 'Ukuran berkas melebihi 10 MB.',
  TYPE: 'Jenis berkas tidak didukung. Gunakan JPG, PNG, WebP, atau PDF.',
  NAME: 'Nama atau ekstensi berkas tidak sesuai isinya.',
  STRUCTURE: 'Berkas rusak atau tidak utuh.',
}

/** Convenience check before sending; the server checks again by content. */
export function checkFile(file: File): string | undefined {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!EXTENSIONS.includes(extension)) return REFUSALS.TYPE
  if (file.size === 0) return REFUSALS.EMPTY
  if (file.size > MAX_BYTES) return REFUSALS.TOO_LARGE
  return undefined
}

export function sizeText(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toLocaleString('id-ID', { maximumFractionDigits: 1 })} MB`
}

/** Raw requests (file body, blob reply) get the same one-refresh retry as `auth.authorized`. */
async function withSession<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run()
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) throw error
  }
  await useAuth().restore()
  return run()
}

/** One upload id per chosen file: a retry of the same file reuses it, so the server stores it once. */
export function uploadEvidence(activityId: string, file: File, uploadId: string): Promise<Evidence> {
  return withSession(() => put(activityId, file, uploadId))
}

async function put(activityId: string, file: File, uploadId: string): Promise<Evidence> {
  const headers = new Headers({ Accept: 'application/json', 'X-Duit-CSRF': '1',
    'X-Duit-File-Name': encodeURIComponent(file.name) })
  if (file.type) headers.set('Content-Type', file.type)
  const response = await fetch(`/api/v1/activities/${activityId}/evidence/${uploadId}`, {
    method: 'PUT', headers, credentials: 'same-origin', body: file,
  })
  const value = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, value)
  return value as Evidence
}

export const fetchEvidence = (activityId: string) =>
  useAuth().authorized<Evidence | null>(`/activities/${activityId}/evidence`)
export const removeEvidence = (activityId: string) =>
  useAuth().authorized(`/activities/${activityId}/evidence`, 'DELETE')

export function evidenceBlob(activityId: string): Promise<Blob> {
  return withSession(() => blob(activityId))
}

async function blob(activityId: string): Promise<Blob> {
  const response = await fetch(`/api/v1/activities/${activityId}/evidence/content`, { credentials: 'same-origin' })
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => ({})))
  return response.blob()
}

export function evidenceError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Tidak dapat terhubung. Transaksi tetap tercatat; coba unggah lagi.'
  if (error.code === 'EVIDENCE_REJECTED') {
    return REFUSALS[String(error.details?.reason)] ?? 'Bukti ditolak. Gunakan JPG, PNG, WebP, atau PDF maksimal 10 MB.'
  }
  if (error.code === 'TEMPORARY_FAILURE') return 'Penyimpanan bukti sedang sibuk atau tidak tersedia. Transaksi tetap tercatat; coba unggah lagi.'
  if (error.code === 'INVALID_ACTIVITY_STATE') return 'Transaksi yang dihapus tidak dapat diberi bukti.'
  if (error.code === 'FINANCIAL_INTEGRITY_FROZEN') return 'Akun sedang dalam pemeriksaan integritas. Bukti belum dapat diubah.'
  if (error.code === 'FINANCIAL_RECOVERY_ACTIVE') return 'Pemulihan finansial sedang berlangsung. Bukti belum dapat diubah.'
  return error.message
}
