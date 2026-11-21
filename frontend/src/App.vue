<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from './session'
import { VaultError, useVault } from './vault/store'

const auth = useAuth()
const vault = useVault()
const router = useRouter()
const pin = ref('')
const pinError = ref('')
const pinInput = ref<HTMLInputElement>()

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
    <RouterLink to="/" class="wordmark"><span aria-hidden="true">D</span>Duit Log</RouterLink>
    <nav v-if="auth.profile" aria-label="Akun">
      <RouterLink :to="auth.profile.emailVerified ? '/account' : '/verify-email'">Akun</RouterLink>
      <RouterLink to="/sessions">Perangkat</RouterLink>
      <RouterLink v-if="auth.profile.emailVerified" to="/offline">Offline</RouterLink>
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
</template>
