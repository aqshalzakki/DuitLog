import { defineStore } from 'pinia'
import { ref } from 'vue'

export type Profile = {
  id: string
  name: string
  email: string
  emailVerified: boolean
}

export type Device = {
  id: string
  label: string
  createdAt: string
  lastSeenAt: string
  expiresAt: string
  current: boolean
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    value: { message?: string; fieldErrors?: Record<string, string> },
  ) {
    super(value.message ?? 'Permintaan gagal diproses.')
    this.fields = value.fieldErrors ?? {}
  }

  readonly fields: Record<string, string>
}

export async function api<T>(path: string, method = 'GET', payload?: object): Promise<T> {
  const headers = new Headers({ Accept: 'application/json' })
  if (method !== 'GET') headers.set('X-Duit-CSRF', '1')
  if (payload !== undefined) headers.set('Content-Type', 'application/json')
  const response = await fetch('/api/v1' + path, {
    method,
    headers,
    credentials: 'same-origin',
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => ({})))
  if (response.status === 204 || response.status === 202) return undefined as T
  return response.json() as Promise<T>
}

function unauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

export const useAuth = defineStore('auth', () => {
  const profile = ref<Profile>()
  const loaded = ref(false)
  const loadError = ref('')
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('duitlog-auth') : undefined
  let activeRestore: Promise<void> | undefined

  async function getProfile() {
    profile.value = await api<Profile>('/me')
    loaded.value = true
  }

  // Recheck the access cookie inside the lock because another tab may have refreshed it.
  async function refreshSession() {
    const refresh = async () => {
      try {
        return await getProfile()
      } catch (error) {
        if (!unauthorized(error)) throw error
      }
      await api('/auth/refresh', 'POST')
      await getProfile()
    }
    if (navigator.locks) await navigator.locks.request('duitlog-auth-refresh', refresh)
    else await refresh()
  }

  function clear() {
    profile.value = undefined
    loaded.value = true
  }

  function notify() {
    channel?.postMessage('session-changed')
  }

  async function restore() {
    if (activeRestore) return activeRestore
    activeRestore = (async () => {
      loadError.value = ''
      try {
        await refreshSession()
      } catch (error) {
        clear()
        if (!unauthorized(error)) loadError.value = 'Layanan tidak dapat dihubungi. Coba lagi.'
      }
    })()
    try {
      await activeRestore
    } finally {
      activeRestore = undefined
    }
  }

  async function authorized<T>(path: string, method = 'GET', payload?: object): Promise<T> {
    try {
      return await api<T>(path, method, payload)
    } catch (error) {
      if (!unauthorized(error)) throw error
    }
    try {
      await refreshSession()
      return await api<T>(path, method, payload)
    } catch (error) {
      if (unauthorized(error)) clear()
      throw error
    }
  }

  channel?.addEventListener('message', () => {
    clear()
    loaded.value = false
  })

  return { profile, loaded, loadError, getProfile, restore, authorized, clear, notify }
})
