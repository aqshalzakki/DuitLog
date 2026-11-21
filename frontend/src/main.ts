import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import AuthPage from './AuthPage.vue'
import OfflinePage from './OfflinePage.vue'
import SessionPage from './SessionPage.vue'
import SyncPage from './SyncPage.vue'
import DashboardPage from './DashboardPage.vue'
import EntryPage from './EntryPage.vue'
import OnboardingPage from './OnboardingPage.vue'
import { useEntries, useFinance } from './finance'
import { useSync } from './sync/engine'
import { useAuth } from './session'
import { enrolledOwner, useVault } from './vault/store'
import './style.css'

const pinia = createPinia()
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: DashboardPage, meta: { offline: true } },
    { path: '/onboarding', name: 'onboarding', component: OnboardingPage, meta: { session: true, verified: true } },
    { path: '/add/:kind(increase|deduct|loan|repayment)', name: 'add', component: EntryPage, meta: { offline: true } },
    { path: '/login', name: 'login', component: AuthPage },
    { path: '/register', name: 'register', component: AuthPage },
    { path: '/forgot-password', name: 'forgot', component: AuthPage },
    { path: '/reset-password', name: 'reset', component: AuthPage },
    { path: '/verify-email', name: 'verify', component: AuthPage },
    { path: '/account', name: 'account', component: SessionPage, meta: { session: true, verified: true } },
    { path: '/sessions', name: 'sessions', component: SessionPage, meta: { session: true } },
    { path: '/offline', name: 'offline', component: OfflinePage, meta: { offline: true } },
    { path: '/sync', name: 'sync', component: SyncPage, meta: { offline: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

const auth = useAuth(pinia)
const vault = useVault(pinia)
const sync = useSync(pinia)
const finance = useFinance(pinia)
const entries = useEntries(pinia)
// Server unreachable (not 401) with a vault on this device: offline capability, not "logged out".
const offlineBoot = () => !auth.profile && !!auth.loadError && !!enrolledOwner()

router.beforeEach(async (to) => {
  if (!auth.loaded && (to.meta.session || to.meta.offline || to.name === 'verify')) await auth.restore()
  if (to.meta.offline) {
    if (auth.profile) return auth.profile.emailVerified ? undefined : { name: 'verify' }
    return offlineBoot() ? undefined : { name: 'login' }
  }
  if (to.meta.session && offlineBoot()) return { name: 'offline' }
  if (to.meta.session && !auth.profile) return { name: 'login' }
  if (to.meta.verified && !auth.profile?.emailVerified) return { name: 'verify' }
  if (to.name === 'verify' && auth.profile?.emailVerified) return { name: 'account' }
})

watch(() => auth.profile?.id, (id, previous) => {
  if (previous && !id && router.currentRoute.value.meta.session) void router.replace({ name: 'login' })
})

// The vault follows the signed-in owner. Logout or a real 401 drops the key but keeps the owner, so
// the page shows Hard Lock; a network error keeps the key; another account switches vaults.
function syncVault() {
  const id = auth.profile?.id
  if (!id && !auth.loadError) vault.hardLock()
  void vault.load(id ?? vault.owner ?? (auth.loadError ? enrolledOwner() : undefined))
}
watch(() => [auth.profile?.id, auth.loadError], syncVault, { immediate: true })
// Leaving the page (or entering the back/forward cache) is a Hard Lock and frees the database.
addEventListener('pagehide', () => vault.release())
addEventListener('pageshow', (event) => { if (event.persisted) syncVault() })
// Any session change in another tab (logout, login, account switch) hard-locks this tab too.
if (typeof BroadcastChannel === 'function') {
  new BroadcastChannel('duitlog-auth').addEventListener('message', () => vault.hardLock())
}
for (const event of ['pointerdown', 'keydown', 'touchstart', 'wheel']) {
  addEventListener(event, () => vault.touch(), { capture: true, passive: true })
}
// Timers sleep in background tabs, so idle is also checked by timestamp on focus and visibility.
addEventListener('focus', () => vault.checkIdle())
document.addEventListener('visibilitychange', () => vault.checkIdle())
setInterval(() => vault.checkIdle(), 15_000)

// Foreground-first sync: on unlock, when back online or visible, and on a slow timer.
// Another owner, or a lock with no live session, drops in-memory figures and form state.
watch(() => auth.profile?.id ?? vault.owner, () => { finance.clear(); entries.clear() })
watch(() => vault.status, (status) => { if (status === 'hard' && !auth.profile) finance.clear() })
watch(() => [vault.status, vault.expired, auth.profile?.id], async () => {
  await sync.refresh() // also clears decrypted items on any lock
  void sync.cycle(true)
})
addEventListener('online', () => void sync.cycle(true))
document.addEventListener('visibilitychange', () => void sync.cycle())
setInterval(() => void sync.cycle(), 30_000)

if (import.meta.env.DEV) {
  // Test hook for the browser suite only; stripped from production builds.
  Object.assign(window, {
    __duitVault: { save: vault.save, read: vault.read, list: vault.list },
    __duitSync: { enqueue: sync.enqueue, correct: sync.correct, cancel: sync.cancel, cycle: sync.cycle,
      items: async () => { await sync.refresh(); return JSON.parse(JSON.stringify(sync.items)) }, state: () => ({ running: sync.running, error: sync.error }) },
  })
}

createApp(App).use(pinia).use(router).mount('#app')
