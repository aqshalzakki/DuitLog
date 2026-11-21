import { ApiError, useAuth } from './session'

export type Change = { state: 'ZERO' | 'NEW' | 'NO_BASELINE' | 'PERCENT'; percent?: string }
export type Range = { from: string; to: string; start: string; end: string; period?: string; running?: boolean }
export type Period = 'day' | 'week' | 'month' | 'year' | 'custom'
export type Query = { period: Period; date?: string; from?: string; to?: string }

export const PERIODS: Record<Period, string> = { day: 'Harian', week: 'Mingguan', month: 'Bulanan', year: 'Tahunan', custom: 'Rentang' }

/** Official reports: online only, never cached, never mixed with pending items. */
export async function fetchReport<T>(family: string, query: Query): Promise<T> {
  const params = new URLSearchParams({ period: query.period })
  if (query.period === 'custom') {
    params.set('from', query.from ?? '')
    params.set('to', query.to ?? '')
  } else if (query.date) params.set('date', query.date)
  return useAuth().authorized<T>(`/reports/${family}?` + params)
}

/** Why a report is not shown; no reply at all means offline. */
export function reportError(error: unknown) {
  if (!(error instanceof ApiError)) return 'Laporan hanya tersedia saat online. Sambungkan ke internet lalu coba lagi.'
  if (error.code === 'FINANCIAL_INTEGRITY_FROZEN') return 'Akun sedang dalam pemeriksaan integritas. Laporan resmi ditahan sampai selesai.'
  if (error.code === 'FINANCIAL_RECOVERY_ACTIVE') return 'Pemulihan finansial sedang berlangsung. Laporan resmi ditahan.'
  if (error.code === 'VALIDATION_ERROR') return 'Periode tidak valid. Periksa tanggalnya; periode di masa depan tidak bisa dipilih.'
  return 'Laporan gagal dimuat. Coba lagi.'
}

const day = new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const month = new Intl.DateTimeFormat('id-ID', { month: 'short', year: 'numeric', timeZone: 'UTC' })

/** "YYYY-MM-DD" (or "YYYY-MM") already in the account zone; formatted without shifting it again. */
export const dateLabel = (value: string) =>
  value.length === 7 ? month.format(new Date(value + '-01T00:00:00Z')) : day.format(new Date(value + 'T00:00:00Z'))

export function rangeLabel(range: Range) {
  const span = range.from === range.to ? dateLabel(range.from) : `${dateLabel(range.from)} – ${dateLabel(range.to)}`
  return range.running ? `${span} (berjalan, sampai sekarang)` : span
}

export function changeText(change: Change) {
  if (change.state === 'ZERO') return '0%'
  if (change.state === 'NEW') return 'Baru'
  if (change.state === 'NO_BASELINE') return 'Tidak ada pembanding: periode sebelumnya Rp0'
  const value = change.percent ?? '0.0'
  const text = value.replace('-', '').replace('.', ',') + '%'
  return value.startsWith('-') ? `turun ${text}` : value === '0.0' ? 'tetap (0,0%)' : `naik ${text}`
}

/** Bar width in percent of the largest value; Number is fine for a ratio, never for the amounts. */
export function share(value: string, max: bigint) {
  return max > 0n ? Math.max(0, Math.round((Number(BigInt(value)) / Number(max)) * 100)) : 0
}

export const biggest = (values: string[]) => values.reduce((max, v) => (BigInt(v) > max ? BigInt(v) : max), 0n)
