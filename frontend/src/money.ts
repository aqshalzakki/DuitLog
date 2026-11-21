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

import { shallowRef } from 'vue'

// The account timezone (BR-RPT-11): set from the confirmed state, live or cached; the BRD default until then.
let zone = 'Asia/Jakarta'
const current = shallowRef(zone) // reactive copy, so labels re-render when the zone arrives
let parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit',
  day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
let when = new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit',
  minute: '2-digit', timeZoneName: 'short', timeZone: zone })

export const accountZone = () => current.value

/** Ignored unless the browser knows the zone, so a bad value can never break date handling. */
export function setZone(name: string | undefined) {
  if (!name || name === zone) return
  try {
    const next = new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit',
      minute: '2-digit', timeZoneName: 'short', timeZone: name })
    parts = new Intl.DateTimeFormat('en-US', { timeZone: name, hourCycle: 'h23', year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    when = next
    zone = name
    current.value = name
  } catch { /* unknown to this browser: keep the previous zone */ }
}

/** Offset of the account zone at an instant, in ms (DST included). */
function offset(ms: number) {
  const p = Object.fromEntries(parts.formatToParts(ms).map((x) => [x.type, Number(x.value)]))
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(ms / 1000) * 1000
}

/** "YYYY-MM-DDTHH:mm" for a datetime-local input, in the account timezone. */
export function localInput(ms = Date.now()) {
  return new Date(ms + offset(ms)).toISOString().slice(0, 16)
}

/** The absolute instant of a datetime-local value read in the account timezone. A wall time in a DST
 * gap resolves to an instant just past it; in an overlap, to one of the two. */
export function instant(value: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return undefined
  const wall = Date.parse((value.length === 16 ? value + ':00' : value) + 'Z')
  if (Number.isNaN(wall)) return undefined
  const first = wall - offset(wall)
  return new Date(wall - offset(first)).toISOString()
}

export const formatTime = (value: string | number) => when.format(new Date(value))

export const KINDS: Record<string, string> = {
  INCREASE: 'Pemasukan', DEDUCT: 'Pengeluaran', LOAN: 'Pinjaman', REPAYMENT: 'Pembayaran piutang',
  OPENING: 'Saldo awal', ADJUSTMENT: 'Penyesuaian saldo',
}
