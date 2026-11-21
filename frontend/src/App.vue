<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './session'
import { VaultError, useVault } from './vault/store'

const auth = useAuth()
const vault = useVault()
const router = useRouter()
const route = useRoute()
// Mobile bottom navigation (PRD §3.1): the + slot opens the four Quick Add choices.
const adding = ref(false)
const addButton = ref<HTMLButtonElement>()
watch(() => route.fullPath, () => { adding.value = false })
const addArea = ref<HTMLElement>()
// A phone has no Escape: a tap anywhere outside the menu closes it.
function outside(event: PointerEvent) {
  if (adding.value && !addArea.value?.contains(event.target as Node)) adding.value = false
}
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
function closeAdd() {
  adding.value = false
  addButton.value?.focus()
}
const pin = ref('')
const pinError = ref('')
const pinInput = ref<HTMLInputElement>()
// Offline boot: no live session, but this tab opened the vault.
const offline = computed(() => !auth.profile && !!auth.loadError && vault.status !== 'none')

watch(() => vault.status, async (status) => {
  pin.value = ''
  pinError.value = ''
  if (status === 'soft') {
    await nextTick()
    pinInput.value?.focus()
  }
})

async function unlockPin() {
  try {
    await vault.unlockPin(pin.value)
  } catch (error) {
    pin.value = ''
    pinError.value = error instanceof VaultError && vault.status === 'hard'
      ? 'Terlalu banyak percobaan. Buka dengan passphrase atau Recovery Key.'
      : 'PIN salah.'
    if (vault.status === 'hard') await router.push('/offline')
  }
}

async function strongUnlock() {
  vault.hardLock()
  await router.push('/offline')
}
</script>

<template>
  <a class="skip-link" href="#content">Langsung ke konten</a>
  <header class="topbar">
    <RouterLink to="/" class="wordmark"><svg class="logo" aria-hidden="true" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" class="logo-bg"/><path class="logo-lines" d="M8 10h12M8 15h9M8 20h5"/><circle class="logo-coin" cx="21.5" cy="21.5" r="5.5"/></svg><span class="wordmark-text">Duit Log</span></RouterLink>
    <nav v-if="auth.profile || offline" aria-label="Utama">
      <template v-if="auth.profile?.emailVerified || offline">
        <RouterLink class="in-bottom" to="/">Beranda</RouterLink>
        <RouterLink class="in-bottom" to="/history">Riwayat</RouterLink>
        <RouterLink class="in-bottom" to="/borrowers">Piutang</RouterLink>
        <RouterLink to="/categories">Kategori</RouterLink>
        <RouterLink class="in-bottom" v-if="auth.profile?.emailVerified" to="/reports">Laporan</RouterLink>
        <RouterLink to="/sync">Sinkronisasi</RouterLink>
        <RouterLink to="/offline">Offline</RouterLink>
        <RouterLink to="/settings">Pengaturan</RouterLink>
      </template>
      <template v-if="auth.profile">
        <RouterLink :to="auth.profile.emailVerified ? '/account' : '/verify-email'">Akun</RouterLink>
        <RouterLink to="/sessions">Perangkat</RouterLink>
        <RouterLink v-if="auth.profile.emailVerified" to="/audit">Audit</RouterLink>
      </template>
    </nav>
  </header>
  <main id="content" tabindex="-1">
    <p v-if="auth.loadError" class="notice error" role="alert">{{ auth.loadError }}</p>
    <!-- Soft Lock unmounts the page instead of covering it, so no decrypted state stays rendered. -->
    <section v-if="vault.status === 'soft'" class="card auth-card" role="dialog" aria-modal="true"
      aria-labelledby="soft-title" data-soft-lock>
      <h1 id="soft-title">Terkunci</h1>
      <p class="intro">Tidak ada aktivitas selama 5 menit. Masukkan PIN untuk melanjutkan.</p>
      <form @submit.prevent="unlockPin">
        <label for="soft-pin">PIN</label>
        <input id="soft-pin" ref="pinInput" v-model="pin" inputmode="numeric" autocomplete="off" maxlength="6"
          pattern="\d{6}" required :aria-describedby="pinError ? 'soft-error' : undefined">
        <p v-if="pinError" id="soft-error" class="field-error" role="alert">{{ pinError }}</p>
        <button class="primary">Buka</button>
      </form>
      <div class="actions">
        <button type="button" class="link-button" @click="strongUnlock">Lupa PIN? Buka dengan passphrase</button>
      </div>
    </section>
    <RouterView v-else v-slot="{ Component, route }">
      <component :is="Component" :key="route.name" />
    </RouterView>
  </main>
  <nav v-if="auth.profile?.emailVerified || offline" class="bottom-nav" aria-label="Navigasi bawah" data-bottom-nav>
    <RouterLink to="/"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></svg>Beranda</RouterLink>
    <RouterLink to="/history"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01"/></svg>Transaksi</RouterLink>
    <div ref="addArea" class="add" @keydown.esc="closeAdd">
      <button ref="addButton" type="button" aria-controls="add-menu" :aria-expanded="adding"
        @click="adding = !adding"><span aria-hidden="true">+</span> Tambah</button>
      <ul v-if="adding" id="add-menu" class="add-menu">
        <li><RouterLink to="/add/increase">Pemasukan</RouterLink></li>
        <li><RouterLink to="/add/deduct">Pengeluaran</RouterLink></li>
        <li><RouterLink to="/add/loan">Tambah piutang</RouterLink></li>
        <li><RouterLink to="/add/repayment">Terima pembayaran</RouterLink></li>
      </ul>
    </div>
    <RouterLink to="/borrowers"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M16 3.5a4 4 0 0 1 0 7.5M22 21a7 7 0 0 0-4-6.3"/></svg>Piutang</RouterLink>
    <RouterLink v-if="auth.profile?.emailVerified" to="/reports"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 20V11M10 20V4M16 20v-7M21 20H3"/></svg>Laporan</RouterLink>
  </nav>
</template>
