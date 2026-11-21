import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError, useAuth } from '../session'
import { VaultError, useVault } from '../vault/store'

export type State = 'PENDING' | 'SYNCING' | 'CHECKING_OUTCOME' | 'RETRY_WAITING' | 'CONFLICT' | 'BLOCKED' | 'SYNCED'
type Kind = 'ACTIVITY' | 'BORROWER'
type Fields = Record<string, string | boolean>

export type QueueItem = {
  clientActivityId: string
  attemptId: string
  type: Kind
  /** Wire fields exactly as they will be sent; money stays a decimal string. */
  payload: Fields
  /** clientActivityIds of predecessor activities (a borrower reference is in the payload). */
  dependsOn: string[]
  state: State
  code?: string
  details?: unknown
  result?: { resourceId?: string; financialSequence?: number; effectiveAt?: string }
  sentAt?: number
  /** Time of a send whose answer for this item never arrived: the attempt may still commit. */
  unsure?: number
  createdAt: number
  updatedAt: number
}

type Result = {
  clientActivityId?: string
  status?: string
  code?: string
  conflictDetails?: unknown
  blockedBy?: string[]
  resourceId?: string
  financialSequence?: number
  effectiveAt?: string
}

// Proposals, reviewable: attempts per cycle, backoff, cooldown between cycles, timeouts, settle time.
export const MAX_ATTEMPTS = 3
const BASE_MS = 500
const COOLDOWN_MS = 60_000
const MAX_COOLDOWN_MS = 15 * 60_000
const SEND_TIMEOUT_MS = 20_000
const LOOKUP_TIMEOUT_MS = 10_000
// A server batch keeps running after its request is gone; past this, an unrecorded attempt is settled.
const SETTLE_MS = 10 * 60_000
const SYNCED_KEEP_MS = 24 * 60 * 60_000
const MAX_BATCH = 50
const MAX_BYTES = 60 * 1024 // server body limit is 64 KiB
const MAX_ITEM_BYTES = 8 * 1024

const FIELDS: Record<Kind, string[]> = {
  ACTIVITY: ['kind', 'amount', 'effectiveAt', 'borrowerId', 'borrowerClientId', 'categoryId', 'title', 'description',
    'affectCashBalance'],
  BORROWER: ['name', 'phone', 'notes'],
}
const OFFLINE_KINDS = ['INCREASE', 'DEDUCT', 'LOAN', 'REPAYMENT']
const SENDABLE: State[] = ['PENDING', 'RETRY_WAITING', 'BLOCKED']
const EDITABLE: State[] = ['PENDING', 'CONFLICT', 'BLOCKED']
const HOLDS = ['FINANCIAL_INTEGRITY_FROZEN', 'FINANCIAL_RECOVERY_ACTIVE']

export class SyncError extends Error {
  constructor(readonly code: 'INVALID' | 'IN_FLIGHT' | 'NOT_EDITABLE' | 'HAS_CHILDREN' | 'NOT_FOUND') {
    super(code)
  }
}

/**
 * True only when the app itself refused the request before anything ran: a coded 4xx, or 503 for
 * recovery or a busy lock. A 500 can follow a commit; a timeout, network error or bare 5xx may leave
 * the request running on the server, so those are unknown outcomes.
 */
export function refused(failure: unknown): failure is ApiError {
  return failure instanceof ApiError && !!failure.code && (failure.status < 500
    || (failure.status === 503 && ['FINANCIAL_RECOVERY_ACTIVE', 'TEMPORARY_FAILURE'].includes(failure.code)))
}

const encoder = new TextEncoder()
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function clean(type: Kind, fields: Record<string, unknown>): Fields {
  const allowed = FIELDS[type]
  if (!allowed) throw new SyncError('INVALID')
  const payload: Fields = {}
  for (const [name, value] of Object.entries(fields)) {
    if (!allowed.includes(name)) throw new SyncError('INVALID')
    if (value === undefined || value === null || value === '') continue
    if (typeof value !== 'string' && typeof value !== 'boolean') throw new SyncError('INVALID') // never a Number
    payload[name] = value
  }
  const ok = type === 'BORROWER'
    ? typeof payload.name === 'string'
    : OFFLINE_KINDS.includes(payload.kind as string) && /^[1-9]\d{0,18}$/.test(payload.amount as string)
      && typeof payload.effectiveAt === 'string' && !(payload.borrowerId && payload.borrowerClientId)
  if (!ok) throw new SyncError('INVALID')
  return payload
}

function fits(item: QueueItem) {
  if (encoder.encode(JSON.stringify(wire(item))).length > MAX_ITEM_BYTES) throw new SyncError('INVALID')
}

const parents = (item: QueueItem) =>
  typeof item.payload.borrowerClientId === 'string' ? [...item.dependsOn, item.payload.borrowerClientId] : item.dependsOn

const wire = (item: QueueItem) => ({
  attemptId: item.attemptId,
  clientActivityId: item.clientActivityId,
  type: item.type,
  ...(item.dependsOn.length ? { dependsOn: item.dependsOn } : {}),
  ...item.payload,
})

/** Parents before children; items on a cycle go last and the server reports them. */
function parentsFirst(list: QueueItem[]) {
  const ids = new Set(list.map((item) => item.clientActivityId))
  const placed = new Set<string>()
  const out: QueueItem[] = []
  let rest = list
  while (rest.length) {
    const next = rest.filter((item) => parents(item).every((id) => !ids.has(id) || placed.has(id)))
    if (!next.length) return [...out, ...rest]
    for (const item of next) placed.add(item.clientActivityId)
    out.push(...next)
    rest = rest.filter((item) => !placed.has(item.clientActivityId))
  }
  return out
}

function chunks(list: QueueItem[]) {
  const out: QueueItem[][] = []
  let size = 0
  for (const item of list) {
    const bytes = encoder.encode(JSON.stringify(wire(item))).length + 1
    if (!out.length || out[out.length - 1].length >= MAX_BATCH || size + bytes > MAX_BYTES) {
      out.push([])
      size = 256 // envelope
    }
    out[out.length - 1].push(item)
    size += bytes
  }
  return out
}

type Verdict = 'done' | 'retry' | 'stop'

export const useSync = defineStore('sync', () => {
  const auth = useAuth()
  const vault = useVault()
  const items = ref<QueueItem[]>([])
  const running = ref(false)
  const error = ref('')
  let cooldownUntil = 0
  let failures = 0

  async function withLock(owner: string, ifAvailable: boolean, work: () => Promise<void>) {
    // Without Web Locks, server idempotency is still the final duplicate guard.
    if (!navigator.locks) return work()
    await navigator.locks.request('duitlog-sync-' + owner, { ifAvailable }, async (lock) => { if (lock) await work() })
  }

  function canSync() {
    const profile = auth.profile
    return document.visibilityState === 'visible' && navigator.onLine && vault.status === 'unlocked'
      && !vault.expired && !!profile?.emailVerified && profile.id === vault.owner
  }

  async function load() {
    const rows = await vault.list('pending') // a record that fails to decrypt throws, never reads as empty
    const list = rows.map((row) => row.value as QueueItem).sort((a, b) => a.createdAt - b.createdAt)
    items.value = list
    return list
  }

  /** Decrypted items live only while the vault is open. */
  async function refresh() {
    if (vault.status !== 'unlocked' || vault.expired) {
      items.value = []
      return
    }
    try {
      await load()
      if (error.value === 'CORRUPTED') error.value = ''
    } catch (failure) {
      items.value = []
      error.value = failure instanceof VaultError ? failure.code : 'FAILED'
    }
  }

  async function put(item: QueueItem, changes: Partial<QueueItem>) {
    Object.assign(item, changes, { updatedAt: Date.now() })
    await vault.save('pending', item.clientActivityId, item)
  }

  async function apply(item: QueueItem, result: Result | undefined): Promise<Verdict> {
    const code = result?.code
    switch (result?.status) {
      case 'CONFIRMED':
        await put(item, {
          state: 'SYNCED', code: undefined, details: undefined, unsure: undefined,
          result: { resourceId: result.resourceId, financialSequence: result.financialSequence, effectiveAt: result.effectiveAt },
        })
        return 'done'
      case 'REJECTED': // recorded: this attempt can never commit; ALREADY_CONFIRMED_ACTIVITY is shown, not hidden
        await put(item, { state: 'CONFLICT', code, details: result.conflictDetails, unsure: undefined })
        return 'done'
      case 'INVALID':
        await put(item, { state: 'CONFLICT', code })
        return 'done'
      case 'BLOCKED':
        await put(item, { state: 'BLOCKED', code, details: result.blockedBy && { blockedBy: result.blockedBy } })
        return 'done'
      case 'NOT_PROCESSED':
        await put(item, { state: 'PENDING' })
        return 'done'
      case 'RETRYABLE':
        if (code === 'TEMPORARY_FAILURE') {
          await put(item, { state: 'RETRY_WAITING', code })
          return 'retry'
        }
        await put(item, { state: 'PENDING', code })
        error.value = code ?? 'FAILED'
        return 'stop'
      default: // OUTCOME_UNKNOWN, FAILED, a missing or unknown answer: the attempt may have committed
        await put(item, { state: 'CHECKING_OUTCOME', unsure: Date.now() })
        return 'retry'
    }
  }

  async function pass(owner: string): Promise<Verdict> {
    const list = await load()
    const now = Date.now()
    for (const item of list) {
      if (item.state === 'SYNCED' && now - item.updatedAt > SYNCED_KEEP_MS) await vault.remove(item.clientActivityId)
      // Left mid-send by a crash, reload or lock: only the server knows.
      if (item.state === 'SYNCING') await put(item, { state: 'CHECKING_OUTCOME', unsure: item.sentAt ?? now })
    }
    let verdict: Verdict = 'done'
    const check = (item: QueueItem) =>
      item.state === 'CHECKING_OUTCOME' || (!!item.unsure && EDITABLE.includes(item.state))
    for (const item of list.filter(check)) {
      let outcome: Result
      try {
        outcome = await auth.authorized<Result>('/operations/' + item.attemptId, 'GET', undefined,
          AbortSignal.timeout(LOOKUP_TIMEOUT_MS))
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 404 && failure.code === 'NOT_FOUND') {
          // Not recorded (yet). Resending the same attempt is safe: a late commit answers through idempotency.
          const settled = !item.unsure || Date.now() - item.unsure > SETTLE_MS
          await put(item, {
            state: item.state === 'CHECKING_OUTCOME' ? 'PENDING' : item.state,
            ...(settled ? { unsure: undefined } : {}),
          })
          continue
        }
        if (failure instanceof ApiError && failure.code) {
          error.value = failure.code
          return 'stop'
        }
        verdict = 'retry'
        continue
      }
      if ((await apply(item, outcome)) === 'stop') return 'stop'
    }

    const byId = new Map(list.map((item) => [item.clientActivityId, item]))
    // A child held by a local conflict waits for the parent's correction; resending it would only block again.
    const held = (item: QueueItem) => item.state === 'BLOCKED'
      && parents(item).some((id) => ['CONFLICT', 'BLOCKED'].includes(byId.get(id)?.state ?? ''))
    const ready = parentsFirst(list.filter((item) => SENDABLE.includes(item.state) && !held(item)))
    for (const chunk of chunks(ready)) {
      const sentAt = Date.now()
      for (const item of chunk) await put(item, { state: 'SYNCING', sentAt })
      let results: Result[]
      try {
        const reply = await auth.authorized<{ results?: Result[] }>('/sync/items', 'POST',
          { owner, items: chunk.map(wire) }, AbortSignal.timeout(SEND_TIMEOUT_MS))
        results = reply?.results ?? []
      } catch (failure) {
        if (!refused(failure)) {
          for (const item of chunk) await put(item, { state: 'CHECKING_OUTCOME', unsure: sentAt })
          return 'retry'
        }
        const retry = failure.code === 'TEMPORARY_FAILURE' || failure.status === 429
        for (const item of chunk) await put(item, { state: retry ? 'RETRY_WAITING' : 'PENDING', ...(retry ? { code: failure.code } : {}) })
        if (failure.code === 'SESSION_OWNER_MISMATCH') vault.hardLock()
        if (retry) return 'retry'
        error.value = failure.code ?? 'FAILED'
        return 'stop'
      }
      const got = new Map(results.map((result) => [result.clientActivityId, result]))
      for (const item of chunk) {
        const next = await apply(item, got.get(item.clientActivityId))
        if (next !== 'done' && verdict !== 'stop') verdict = next
      }
      if (verdict !== 'done') return verdict
    }
    return verdict
  }

  /** One cycle: at most MAX_ATTEMPTS passes with backoff. Only one tab per owner runs it. */
  async function cycle(manual = false) {
    if (!canSync() || (!manual && Date.now() < cooldownUntil)) return
    const owner = vault.owner!
    await withLock(owner, true, async () => {
      running.value = true
      error.value = ''
      let verdict: Verdict = 'done'
      try {
        for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
          if (attempt) await sleep(BASE_MS * 2 ** (attempt - 1) * (1 + Math.random()))
          if (!canSync() || vault.owner !== owner) break
          verdict = await pass(owner)
          if (verdict !== 'retry') break
        }
      } catch (failure) {
        verdict = 'stop' // a lock, expiry or storage failure mid-cycle; SYNCING items are looked up next time
        error.value = failure instanceof VaultError ? failure.code : 'FAILED'
      } finally {
        failures = verdict === 'done' ? 0 : failures + 1
        cooldownUntil = verdict === 'done' ? 0 : Date.now() + Math.min(COOLDOWN_MS * 2 ** (failures - 1), MAX_COOLDOWN_MS)
        running.value = false
        await refresh()
      }
    })
  }

  async function enqueue(type: Kind, fields: Record<string, unknown>, dependsOn: string[] = []) {
    const payload = clean(type, fields)
    if (type === 'BORROWER' && dependsOn.length) throw new SyncError('INVALID')
    const now = Date.now()
    const item: QueueItem = {
      clientActivityId: crypto.randomUUID(), attemptId: crypto.randomUUID(), type, payload,
      dependsOn: [...dependsOn], state: 'PENDING', createdAt: now, updatedAt: now,
    }
    fits(item)
    await vault.save('pending', item.clientActivityId, item) // saved only once this write commits
    await refresh()
    void cycle(true)
    return item.clientActivityId
  }

  /** Edits and cancels share the cycle's lock so a send in progress never overwrites them. */
  async function change(id: string, work: (item: QueueItem, list: QueueItem[]) => Promise<void>) {
    const owner = vault.owner
    if (!owner) throw new VaultError('LOCKED')
    await withLock(owner, false, async () => {
      const list = await load()
      const item = list.find((entry) => entry.clientActivityId === id)
      if (!item) throw new SyncError('NOT_FOUND')
      if (!EDITABLE.includes(item.state)) throw new SyncError('NOT_EDITABLE')
      if (item.unsure) throw new SyncError('IN_FLIGHT') // an earlier send may still commit this payload
      await work(item, list)
    })
    await refresh()
  }

  /** A correction is a new attempt of the same logical activity, never a second activity. */
  const correct = async (id: string, fields: Record<string, unknown>) => {
    await change(id, (item) => {
      const payload = clean(item.type, fields)
      fits({ ...item, payload })
      return put(item, { payload, attemptId: crypto.randomUUID(), state: 'PENDING', code: undefined, details: undefined })
    })
    void cycle(true)
  }

  const cancel = (id: string) => change(id, async (_, list) => {
    if (list.some((other) => other.state !== 'SYNCED' && parents(other).includes(id))) throw new SyncError('HAS_CHILDREN')
    await vault.remove(id)
  })

  const editable = (item: QueueItem) => EDITABLE.includes(item.state) && !item.unsure

  return { items, running, error, refresh, cycle, enqueue, correct, cancel, editable }
})
