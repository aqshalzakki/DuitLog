// Web Crypto primitives for the offline vault. Every ciphertext is AES-256-GCM with a fresh
// 96-bit nonce and AAD that binds schema, owner, device, record type and record id.
const { subtle } = crypto
const encoder = new TextEncoder()

export const SCHEMA = 1
export const aes = { name: 'AES-GCM', length: 256 } as const
// Proposal: PBKDF2-SHA-256 600k (Phase 0: 182–240 ms on desktop Chrome/Edge); measure on target phones.
export const PASSPHRASE_ITERATIONS = 600_000
const PIN_ITERATIONS = 100_000

export type Bytes = Uint8Array<ArrayBuffer>
export type Wrapper = { iv: Bytes; wrapped: ArrayBuffer; salt?: Bytes; iterations?: number }

export function random(length: number): Bytes {
  return crypto.getRandomValues(new Uint8Array(length))
}

export function context(...parts: (string | number)[]): Bytes {
  return encoder.encode(JSON.stringify([SCHEMA, ...parts]))
}

export function newDek(): Promise<CryptoKey> {
  // Extractable only until it is wrapped at enrollment; day-to-day keys are unwrapped non-extractable.
  return subtle.generateKey(aes, true, ['encrypt', 'decrypt'])
}

export async function passphraseKek(passphrase: string, salt: Bytes, iterations: number) {
  const material = await subtle.importKey('raw', encoder.encode(passphrase.normalize('NFKC')), 'PBKDF2', false, ['deriveKey'])
  return subtle.deriveKey({ name: 'PBKDF2', salt, iterations, hash: 'SHA-256' }, material, aes, false, ['wrapKey', 'unwrapKey'])
}

export function recoveryKek(raw: Bytes) {
  return subtle.importKey('raw', raw, aes, false, ['wrapKey', 'unwrapKey'])
}

export async function wrap(dek: CryptoKey, kek: CryptoKey, aad: Bytes, extra: Partial<Wrapper> = {}): Promise<Wrapper> {
  const iv = random(12)
  return { ...extra, iv, wrapped: await subtle.wrapKey('raw', dek, kek, { name: 'AES-GCM', iv, additionalData: aad }) }
}

export function unwrap(wrapper: Wrapper, kek: CryptoKey, aad: Bytes, extractable = false) {
  return subtle.unwrapKey('raw', wrapper.wrapped, kek, { name: 'AES-GCM', iv: wrapper.iv, additionalData: aad },
    aes, extractable, ['encrypt', 'decrypt'])
}

export async function seal(dek: CryptoKey, aad: Bytes, plaintext: Bytes) {
  const iv = random(12)
  return { iv, ct: await subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad }, dek, plaintext) }
}

export async function open(dek: CryptoKey, aad: Bytes, iv: Bytes, ct: ArrayBuffer): Promise<Bytes> {
  return new Uint8Array(await subtle.decrypt({ name: 'AES-GCM', iv, additionalData: aad }, dek, ct))
}

export async function pinHash(pin: string, salt: Bytes): Promise<Bytes> {
  const material = await subtle.importKey('raw', encoder.encode(pin), 'PBKDF2', false, ['deriveBits'])
  return new Uint8Array(await subtle.deriveBits({ name: 'PBKDF2', salt, iterations: PIN_ITERATIONS, hash: 'SHA-256' }, material, 256))
}

export function same(a: Bytes, b: Bytes): boolean {
  let diff = a.length ^ b.length
  for (let i = 0; i < Math.min(a.length, b.length); i++) diff |= a[i] ^ b[i]
  return diff === 0
}

// Recovery Key: 256 random bits as Crockford base32 in groups of four (52 characters).
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'

export function formatRecovery(raw: Bytes): string {
  let bits = 0
  let value = 0
  let out = ''
  for (const byte of raw) {
    value = ((value << 8) | byte) & 0xffff
    bits += 8
    while (bits >= 5) {
      out += ALPHABET[(value >>> (bits - 5)) & 31]
      bits -= 5
    }
  }
  if (bits > 0) out += ALPHABET[(value << (5 - bits)) & 31]
  return out.match(/.{1,4}/g)!.join('-')
}

export function parseRecovery(text: string): Bytes | undefined {
  const clean = text.toUpperCase().replace(/[\s-]/g, '').replace(/[IL]/g, '1').replace(/O/g, '0')
  if (clean.length !== 52) return undefined
  const out = new Uint8Array(32)
  let bits = 0
  let value = 0
  let index = 0
  for (const char of clean) {
    const digit = ALPHABET.indexOf(char)
    if (digit < 0) return undefined
    value = ((value << 5) | digit) & 0xfff
    bits += 5
    if (bits >= 8 && index < 32) {
      out[index++] = (value >>> (bits - 8)) & 255
      bits -= 8
    }
  }
  return index === 32 ? out : undefined
}
