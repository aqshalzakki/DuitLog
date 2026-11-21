import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import AuthPage from './AuthPage.vue'
import SessionPage from './SessionPage.vue'
import { useAuth } from './session'
import './style.css'

const pinia = createPinia()
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/account' },
    { path: '/login', name: 'login', component: AuthPage },
    { path: '/register', name: 'register', component: AuthPage },
    { path: '/forgot-password', name: 'forgot', component: AuthPage },
    { path: '/reset-password', name: 'reset', component: AuthPage },
    { path: '/verify-email', name: 'verify', component: AuthPage },
    { path: '/account', name: 'account', component: SessionPage, meta: { session: true, verified: true } },
    { path: '/sessions', name: 'sessions', component: SessionPage, meta: { session: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuth(pinia)
  if (!auth.loaded && (to.meta.session || to.name === 'verify')) await auth.restore()
  if (to.meta.session && !auth.profile) return { name: 'login' }
  if (to.meta.verified && !auth.profile?.emailVerified) return { name: 'verify' }
  if (to.name === 'verify' && auth.profile?.emailVerified) return { name: 'account' }
})

const auth = useAuth(pinia)
watch(() => auth.profile?.id, (id, previous) => {
  if (previous && !id && router.currentRoute.value.meta.session) void router.replace({ name: 'login' })
})

createApp(App).use(pinia).use(router).mount('#app')
