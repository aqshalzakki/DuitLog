import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as c from './crypto'

// Proposals pending review: 5 wrong PINs drop to Hard Lock; passphrase at least 12 characters.
export const IDLE_MS = 5 * 60_000
export const VALIDATION_MS = 7 * 24 * 60 * 60_000
const CLOCK_SLACK_MS = 5 * 60_000
const PIN_ATTEMPTS = 5
const POINTER = 'duitlog.offline.owner'
const RECORD_TYPES = ['draft', 'pending', 'evidence', 'cache'] as const

export type RecordType = (typeof RECORD_TYPES)[number]
export type Status = 'loading' | 'none' | 'hard' | 'unlocked' | 'soft' | 'corrupt'
type Meta = { schema: number; owner: string; device: string; createdAt: number; wrappers: Record<string, c.Wrapper> }
type Stored = { id: string; type: string; iv: c.Bytes; ct: ArrayBuffer; bin: boolean }
type Validation = { verifiedAt: number; seenAt: number }
type Unlock = { passphrase: string } | { recovery: string }

export class VaultError extends Error {
  constructor(readonly code: 'LOCKED' | 'EXPIRED' | 'WRONG_SECRET' | 'CORRUPTED' | 'EXISTS' | 'INVALID' | 'STORAGE') {
    super(code)
  }
}

// The only copy of the DEK lives in this tab's memory: a reload or new tab is a Hard Lock.
let dek: CryptoKey | undefined
let pin: { salt: c.Bytes; hash: c.Bytes } | undefined
let pending: { dek: CryptoKey; recovery: c.Bytes } | undefined
let db: IDBDatabase | undefined
let meta: Meta | undefined

export function enrolledOwner(): string | undefined {
  try {
    return localStorage.getItem(POINTER) ?? undefined // owner UUID only, so an offline boot can find its vault
  } catch {
    return undefined
  }
}

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

const dbName = (owner: string) => `duitlog-vault-${owner}`

async function vaultExists(owner: string): Promise<boolean> {
  if (!indexedDB.databases) return true // shortcut: no listing API, so open (and maybe create) to find out
  return (await indexedDB.databases()).some((item) => item.name === dbName(owner))
}

function openDb(owner: string): Promise<IDBDatabase> {
  const req = indexedDB.open(dbName(owner), 1)
  req.onupgradeneeded = () => {
    req.result.createObjectStore('meta')
    req.result.createObjectStore('records', { keyPath: 'id' })
  }
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(new VaultError('STORAGE'))
    req.onblocked = () => reject(new VaultError('STORAGE')) // another tab holds an old connection
  })
}

// Encrypt first, then write: awaiting Web Crypto inside an IndexedDB transaction auto-commits it.
function write(fill: (meta: IDBObjectStore, records: IDBObjectStore) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!db) return reject(new VaultError('LOCKED'))
    const tx = db.transaction(['meta', 'records'], 'readwrite', { durability: 'strict' })
    tx.oncomplete = () => resolve()
    tx.onabort = () => reject(tx.error?.name === 'ConstraintError' ? new VaultError('EXISTS') : new VaultError('STORAGE'))
    try {
      fill(tx.objectStore('meta'), tx.objectStore('records'))
    } catch {
      tx.abort()
    }
  })
}

const encoder = new TextEncoder()
const decoder = new TextDecoder()
const aad = (type: string, id: string) => c.context(meta!.owner, meta!.device, type, id)
const wrapperAad = (kind: string) => c.context(meta!.owner, meta!.device, 'wrapper', kind)

async function sealRecord(key: CryptoKey, type: string, id: string, value: unknown): Promise<Stored> {
  const bin = value instanceof Uint8Array
  const bytes = bin ? new Uint8Array(value) : encoder.encode(JSON.stringify(value))
  return { id, type, bin, ...(await c.seal(key, aad(type, id), bytes)) }
}

async function openRecord(key: CryptoKey, row: Stored | undefined): Promise<unknown> {
  if (!row) throw new VaultError('CORRUPTED')
  try {
    const bytes = await c.open(key, aad(row.type, row.id), row.iv, row.ct)
    return row.bin ? bytes : JSON.parse(decoder.decode(bytes))
  } catch {
    throw new VaultError('CORRUPTED') // tampered or foreign ciphertext never reads as empty
  }
}

async function kek(secret: Unlock): Promise<{ kind: string; key: CryptoKey }> {
  if ('passphrase' in secret) {
    const wrapper = meta!.wrappers.passphrase
    return { kind: 'passphrase', key: await c.passphraseKek(secret.passphrase, wrapper.salt!, wrapper.iterations!) }
  }
  const raw = c.parseRecovery(secret.recovery)
  if (!raw) throw new VaultError('WRONG_SECRET')
  return { kind: 'recovery', key: await c.recoveryKek(raw) }
}

async function unwrapWith(secret: Unlock, extractable = false): Promise<CryptoKey> {
  const { kind, key } = await kek(secret)
  try {
    return await c.unwrap(meta!.wrappers[kind], key, wrapperAad(kind), extractable)
  } catch {
    throw new VaultError('WRONG_SECRET')
  }
}

async function passphraseWrapper(key: CryptoKey, passphrase: string) {
  const salt = c.random(16)
  const iterations = c.PASSPHRASE_ITERATIONS
  return c.wrap(key, await c.passphraseKek(passphrase, salt, iterations), wrapperAad('passphrase'), { salt, iterations })
}

export function validPassphrase(passphrase: string, newPin?: string) {
  return passphrase.trim().length >= 12 && (!newPin || !passphrase.includes(newPin))
}

export const useVault = defineStore('vault', () => {
  const owner = ref<string>()
  const status = ref<Status>('none')
  const expired = ref(false)
  const verifiedAt = ref<number>()
  const pinFailures = ref(0)
  let lastActivity = Date.now()
  let validation: Validation | undefined

  function drop() {
    dek = undefined
    pin = undefined
    pending = undefined
    validation = undefined
  }

  function forget() {
    drop()
    db?.close()
    db = undefined
    meta = undefined
  }

  async function load(next: string | undefined) {
    if (next !== owner.value) {
      forget()
      status.value = 'loading' // never show the previous owner's state while the new one loads
    }
    owner.value = next
    if (!next) return void (status.value = 'none')
    if (dek) return
    // Users who never enabled Offline Access get no database at all; enrollment creates it.
    if (!db && !(await vaultExists(next))) return void (status.value = 'none')
    const opened = await connect(next)
    meta = await request(opened.transaction('meta').objectStore('meta').get('vault'))
    const count = await request(opened.transaction('records').objectStore('records').count())
    status.value = meta?.wrappers?.passphrase && meta.wrappers.recovery ? 'hard' : count ? 'corrupt' : 'none'
  }

  async function connect(target: string) {
    if (db) return db
    const opened = await openDb(target)
    // Another tab erasing this vault: let go so its delete is not blocked, and show it as gone.
    opened.onversionchange = () => {
      forget()
      status.value = 'none'
    }
    db = opened
    return opened
  }

  /** Page leaving (or entering the back/forward cache): drop the key and the connection. */
  function release() {
    forget()
    owner.value = undefined
    status.value = 'loading'
  }

  function hardLock() {
    drop()
    pinFailures.value = 0
    if (status.value === 'unlocked' || status.value === 'soft') status.value = 'hard'
  }

  function checkClock(now = Date.now()) {
    if (!validation) return
    expired.value = now - validation.verifiedAt > VALIDATION_MS || now < validation.seenAt - CLOCK_SLACK_MS
    verifiedAt.value = validation.verifiedAt
  }

  async function storeValidation(next: Validation) {
    const row = await sealRecord(dek!, 'validation', '__validation', next)
    await write((_, records) => records.put(row))
    validation = next
    checkClock()
  }

  async function afterUnlock(key: CryptoKey) {
    const rows = await request(db!.transaction('records').objectStore('records').getAll())
    const find = (id: string): Stored | undefined => rows.find((row: Stored) => row.id === id)
    const savedPin = (await openRecord(key, find('__pin'))) as { salt: number[]; hash: number[] }
    const saved = (await openRecord(key, find('__validation'))) as Validation
    dek = key
    pin = { salt: new Uint8Array(savedPin.salt), hash: new Uint8Array(savedPin.hash) }
    validation = saved
    pinFailures.value = 0
    lastActivity = Date.now()
    status.value = 'unlocked'
    checkClock()
    try {
      localStorage.setItem(POINTER, meta!.owner) // the last opened vault is the one an offline boot finds
    } catch {
      // shortcut: without the pointer an offline boot cannot find the vault; online boot still can.
    }
    // Remember the latest clock we trusted, but never move it backwards.
    if (!expired.value) await storeValidation({ ...saved, seenAt: Math.max(saved.seenAt, Date.now()) })
  }

  async function pinRecord(key: CryptoKey, newPin: string) {
    const salt = c.random(16)
    const hash = await c.pinHash(newPin, salt)
    return { row: await sealRecord(key, 'pin', '__pin', { salt: [...salt], hash: [...hash] }), salt, hash }
  }

  /** Step 1 of setup: nothing is stored until `enroll` succeeds. */
  async function prepare(): Promise<string> {
    if (status.value !== 'none') throw new VaultError('EXISTS')
    pending = { dek: await c.newDek(), recovery: c.random(32) }
    return c.formatRecovery(pending.recovery)
  }

  async function enroll(newPin: string, passphrase: string, recoveryConfirm: string) {
    const draft = pending
    const typed = c.parseRecovery(recoveryConfirm)
    if (!draft || !owner.value || !/^\d{6}$/.test(newPin) || !validPassphrase(passphrase, newPin)) throw new VaultError('INVALID')
    if (!typed || !c.same(typed, draft.recovery)) throw new VaultError('WRONG_SECRET')
    meta = { schema: c.SCHEMA, owner: owner.value, device: crypto.randomUUID(), createdAt: Date.now(), wrappers: {} }
    const recoveryKek = await c.recoveryKek(draft.recovery)
    meta.wrappers = {
      passphrase: await passphraseWrapper(draft.dek, passphrase),
      recovery: await c.wrap(draft.dek, recoveryKek, wrapperAad('recovery')),
    }
    const now = Date.now()
    const { row: pinRow } = await pinRecord(draft.dek, newPin)
    const validationRow = await sealRecord(draft.dek, 'validation', '__validation', { verifiedAt: now, seenAt: now })
    const record = meta
    try {
      await connect(owner.value)
      await write((metaStore, records) => {
        metaStore.add(record, 'vault') // add, not put: never overwrite an existing vault
        records.put(pinRow)
        records.put(validationRow)
      })
    } catch (error) {
      meta = undefined
      throw error
    }
    pending = undefined
    // Ask the browser not to evict best-effort storage (pending data). It may still say no.
    void navigator.storage?.persist?.().catch(() => false)
    // Swap the extractable setup key for a non-extractable one.
    await afterUnlock(await c.unwrap(record.wrappers.recovery, recoveryKek, wrapperAad('recovery')))
  }

  async function unlock(secret: Unlock) {
    if (status.value !== 'hard' && status.value !== 'soft') throw new VaultError('INVALID')
    await afterUnlock(await unwrapWith(secret))
  }

  async function unlockPin(value: string) {
    // PIN is only a gate in front of a key that is still in memory; it decrypts nothing.
    if (status.value !== 'soft' || !dek || !pin) throw new VaultError('LOCKED')
    if (c.same(await c.pinHash(value, pin.salt), pin.hash)) {
      pinFailures.value = 0
      lastActivity = Date.now()
      status.value = 'unlocked'
      return checkClock()
    }
    pinFailures.value += 1
    if (pinFailures.value >= PIN_ATTEMPTS) hardLock()
    throw new VaultError('WRONG_SECRET')
  }

  function touch() {
    checkIdle() // the input that ends an idle period must not reset the timer first
    if (status.value === 'unlocked') lastActivity = Date.now()
  }

  function checkIdle() {
    if (status.value === 'unlocked' && Date.now() - lastActivity >= IDLE_MS) status.value = 'soft'
    checkClock()
  }

  function ready() {
    if (status.value !== 'unlocked' || !dek) throw new VaultError('LOCKED')
    checkClock()
    if (expired.value) throw new VaultError('EXPIRED')
    return dek
  }

  async function resetPin(newPin: string) {
    const key = ready()
    if (!/^\d{6}$/.test(newPin)) throw new VaultError('INVALID')
    const next = await pinRecord(key, newPin)
    await write((_, records) => records.put(next.row))
    pin = { salt: next.salt, hash: next.hash }
  }

  /** Replace wrappers in one atomic meta write; ciphertext is never touched. */
  async function rotate(current: Unlock, change: { passphrase?: string; recovery?: string }) {
    ready()
    if (change.passphrase !== undefined && !validPassphrase(change.passphrase)) throw new VaultError('INVALID')
    const recovery = change.recovery === undefined ? undefined : c.parseRecovery(change.recovery)
    if (change.recovery !== undefined && (!recovery || !pending || !c.same(recovery, pending.recovery))) {
      throw new VaultError('WRONG_SECRET')
    }
    const exportable = await unwrapWith(current, true)
    const wrappers = { ...meta!.wrappers }
    if (change.passphrase !== undefined) wrappers.passphrase = await passphraseWrapper(exportable, change.passphrase)
    if (recovery) wrappers.recovery = await c.wrap(exportable, await c.recoveryKek(recovery), wrapperAad('recovery'))
    const next = { ...meta!, wrappers }
    await write((metaStore) => metaStore.put(next, 'vault'))
    meta = next
    pending = undefined
  }

  /** New Recovery Key for `rotate`: shown once, confirmed before it replaces the old one. */
  function draftRecovery(): string {
    ready()
    pending = { dek: dek!, recovery: c.random(32) }
    return c.formatRecovery(pending.recovery)
  }

  /** Only a live, verified server answer for the same owner renews the 7-day window. */
  async function revalidate(profile: { id: string; emailVerified: boolean }) {
    if (!dek || profile.id !== owner.value || !profile.emailVerified) return
    // A live server answer is the trusted moment: it also resets the rollback reference.
    const now = Date.now()
    await storeValidation({ verifiedAt: now, seenAt: now })
  }

  async function save(type: RecordType, id: string, value: unknown) {
    const key = ready()
    if (!RECORD_TYPES.includes(type) || !id || id.startsWith('__')) throw new VaultError('INVALID')
    const row = await sealRecord(key, type, id, value)
    await write((_, records) => records.put(row)) // resolves only after the transaction commits
  }

  async function read(id: string) {
    const key = ready()
    const row = await request<Stored | undefined>(db!.transaction('records').objectStore('records').get(id))
    return row && !id.startsWith('__') ? openRecord(key, row) : undefined
  }

  async function list(type: RecordType) {
    const key = ready()
    const rows = await request<Stored[]>(db!.transaction('records').objectStore('records').getAll())
    const out: { id: string; value: unknown }[] = []
    for (const row of rows.filter((item) => item.type === type)) out.push({ id: row.id, value: await openRecord(key, row) })
    return out
  }

  async function remove(id: string) {
    ready()
    if (!id || id.startsWith('__')) throw new VaultError('INVALID')
    await write((_, records) => records.delete(id))
  }

  async function erase() {
    const target = owner.value
    if (!target) return
    forget()
    await request(indexedDB.deleteDatabase(dbName(target)))
    try {
      if (localStorage.getItem(POINTER) === target) localStorage.removeItem(POINTER)
    } catch {
      // nothing else to clean up
    }
    status.value = 'none'
  }

  return {
    owner, status, expired, verifiedAt, pinFailures,
    load, release, hardLock, prepare, enroll, unlock, unlockPin, touch, checkIdle,
    resetPin, rotate, draftRecovery, revalidate, save, read, list, remove, erase,
  }
})
