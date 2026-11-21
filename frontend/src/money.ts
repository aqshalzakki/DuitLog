// Money stays a decimal string end to end; BigInt is used only to check range and to display.
const MAX = 9223372036854775807n // i64, the server's range

/** A transaction amount: a positive whole number of rupiah. */
export function parseAmount(text: string): string | undefined {
  const value = text.trim().replace(/[.\s]/g, '') // allow "1.250.000"
  return /^[1-9]\d*$/.test(value) && BigInt(value) <= MAX ? value : undefined
}

/** A balance target: any whole number of rupiah, zero and negative included. */
export function parseSigned(text: string): string | undefined {
  const value = text.trim().replace(/[.\s]/g, '').replace(/^[−–]/, '-')
  if (!/^-?\d+$/.test(value)) return undefined
  const number = BigInt(value)
  return number <= MAX && number >= -MAX - 1n ? number.toString() : undefined
}

const group = new Intl.NumberFormat('id-ID')

export function rupiah(value: string | undefined) {
  if (value === undefined) return '—'
  const number = BigInt(value)
  return (number < 0n ? '−Rp' : 'Rp') + group.format(number < 0n ? -number : number)
}

// Assumption: accounts have no stored timezone yet, so the BRD default Asia/Jakarta (UTC+7, no DST) is used.
export const ZONE = 'Asia/Jakarta'
const OFFSET_MS = 7 * 60 * 60_000

/** "YYYY-MM-DDTHH:mm" for a datetime-local input, in the account timezone. */
export function localInput(ms = Date.now()) {
  return new Date(ms + OFFSET_MS).toISOString().slice(0, 16)
}

/** The absolute instant of a datetime-local value read in the account timezone. */
export function instant(value: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return undefined
  const ms = Date.parse((value.length === 16 ? value + ':00' : value) + '+07:00')
  return Number.isNaN(ms) ? undefined : new Date(ms).toISOString()
}

const when = new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short', timeZone: ZONE })
export const formatTime = (value: string | number) => when.format(new Date(value))

export const KINDS: Record<string, string> = {
  INCREASE: 'Pemasukan', DEDUCT: 'Pengeluaran', LOAN: 'Pinjaman', REPAYMENT: 'Pembayaran piutang',
  OPENING: 'Saldo awal', ADJUSTMENT: 'Penyesuaian saldo',
}
