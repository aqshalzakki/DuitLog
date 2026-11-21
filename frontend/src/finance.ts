import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError, useAuth } from './session'
import { setZone } from './money'
import { refused } from './sync/engine'
import { useVault } from './vault/store'

export type FinancialState = {
  balance: string
  receivables: string
  opening: 'pending' | 'skipped' | 'recorded'
  frozen: boolean
  recoveryActive: boolean
  timezone?: string
  updatedAt?: string
}
export type Borrower = { id: string; name: string; outstanding: string; archived: boolean; status: string }
export type Category = { id: string; name: string; archived: boolean }
export type Snapshot = { state: FinancialState; borrowers: Borrower[]; categories: Category[]; at: number }

/** Confirmed figures: live from the server, or the vault copy of the last live answer when offline. */
export const useFinance = defineStore('finance', () => {
  const auth = useAuth()
  const vault = useVault()
  const snapshot = ref<Snapshot>()
  const live = ref(false)

  async function load() {
    const owner = auth.profile?.emailVerified ? auth.profile.id : undefined
    if (owner) {
      try {
        const [state, borrowers, categories] = await Promise.all([
          auth.authorized<FinancialState>('/financial-state'),
          auth.authorized<Borrower[]>('/borrowers'),
          auth.authorized<Category[]>('/categories'),
        ])
        snapshot.value = { state, borrowers, categories, at: Date.now() }
        live.value = true
        setZone(state.timezone)
        // Cached only from a live answer for the vault's own owner.
        if (vault.status === 'unlocked' && !vault.expired && vault.owner === owner) {
          await vault.save('cache', 'finance', snapshot.value).catch(() => undefined)
        }
        return
      } catch {
        // fall back to the cache below
      }
    }
    live.value = false
    snapshot.value = vault.status === 'unlocked' && !vault.expired
      ? (await vault.read('finance').catch(() => undefined)) as Snapshot | undefined
      : undefined
    setZone(snapshot.value?.state.timezone)
  }

  function clear() {
    snapshot.value = undefined
    live.value = false
    setZone('Asia/Jakarta') // the next account never sees the previous one's zone
  }

  return { snapshot, live, load, clear }
})

/** One online write without a vault. Its ids live in Pinia so a remount never makes a second activity. */
export type Op = {
  path: string
  method: string
  clientActivityId: string
  attemptId: string
  body: Record<string, unknown>
  state: 'idle' | 'sending' | 'checking' | 'confirmed' | 'rejected'
  code?: string
  result?: { resourceId?: string; status?: string; code?: string }
}

export const newOp = (path: string, method = 'POST'): Op => ({
  path, method, clientActivityId: crypto.randomUUID(), attemptId: crypto.randomUUID(), body: {}, state: 'idle',
})

function settle(op: Op, code: string | undefined) {
  if (code === 'ALREADY_CONFIRMED_ACTIVITY') {
    op.state = 'confirmed'
    op.code = code
    return
  }
  op.state = 'rejected'
  op.code = code
  op.attemptId = crypto.randomUUID() // a refused attempt is spent; the correction is a new attempt
}

export async function send(op: Op, lookup = true) {
  const auth = useAuth()
  op.state = 'sending'
  op.code = undefined
  try {
    op.result = await auth.authorized(op.path, op.method,
      { attemptId: op.attemptId, clientActivityId: op.clientActivityId, ...op.body }, AbortSignal.timeout(20_000))
    op.state = 'confirmed'
  } catch (failure) {
    if (!refused(failure)) {
      op.state = 'checking' // the write may have committed: ask before anything else
      if (lookup) await check(op)
      return
    }
    settle(op, failure.code)
  }
}

/** Unknown outcome: look the attempt up; resend the same attempt only when it was never recorded. */
export async function check(op: Op) {
  const auth = useAuth()
  try {
    const outcome = await auth.authorized<NonNullable<Op['result']>>('/operations/' + op.attemptId, 'GET', undefined,
      AbortSignal.timeout(10_000))
    if (outcome.status === 'CONFIRMED') {
      op.result = outcome
      op.state = 'confirmed'
    } else settle(op, outcome.code)
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 404 && failure.code === 'NOT_FOUND') await send(op, false)
    // otherwise still unknown; the page offers "Periksa hasil" again
  }
}

// shortcut: loosely typed form fields, each page reads its own names; tighten if forms multiply.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Draft = { fields: Record<string, any>; op?: Op; borrowerOp?: Op; queued?: string; loaded?: boolean }

/** Form state per form, kept across Soft Lock unmounts for this tab only; never persisted. */
export const useEntries = defineStore('entries', () => {
  const drafts = ref<Record<string, Draft>>({})
  function draft(key: string, initial: () => Draft['fields']): Draft {
    drafts.value[key] ??= { fields: initial() }
    return drafts.value[key]
  }
  const reset = (key: string) => { delete drafts.value[key] }
  const clear = () => { drafts.value = {} }
  return { drafts, draft, reset, clear }
})
