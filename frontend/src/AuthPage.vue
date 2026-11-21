<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, api, useAuth } from './session'

type Mode = 'login' | 'register' | 'forgot' | 'reset' | 'verify'
const route = useRoute()
const router = useRouter()
const auth = useAuth()
const mode = computed(() => route.name as Mode)
const copy = {
  login: ['Masuk', 'Masuk ke akun Duit Log kamu.', 'Masuk'],
  register: ['Buat akun', 'Gunakan email yang bisa kamu akses untuk verifikasi.', 'Daftar'],
  forgot: ['Lupa kata sandi', 'Masukkan email akun untuk meminta kode pemulihan.', 'Minta kode'],
  reset: ['Atur ulang kata sandi', 'Masukkan kode dari email dan pilih kata sandi baru.', 'Simpan kata sandi'],
  verify: ['Verifikasi email', 'Masukkan kode verifikasi yang dikirim melalui email.', 'Verifikasi'],
} satisfies Record<Mode, [string, string, string]>

const name = ref('')
const email = ref('')
const password = ref('')
const token = ref('')
const busy = ref(false)
const complete = ref(false)
const status = ref('')
const error = ref('')
const fields = ref<Record<string, string>>({})
const showEmail = computed(() => ['login', 'register', 'forgot'].includes(mode.value))
const showPassword = computed(() => ['login', 'register', 'reset'].includes(mode.value))
const showToken = computed(() => ['verify', 'reset'].includes(mode.value))

async function action(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  fields.value = {}
  error.value = ''
  status.value = ''
  try {
    await work()
  } catch (failure) {
    error.value = failure instanceof ApiError ? failure.message : 'Layanan tidak dapat dihubungi.'
    fields.value = failure instanceof ApiError ? failure.fields : {}
    if (failure instanceof ApiError && failure.status === 401 && mode.value === 'verify') {
      await router.replace({ name: 'login' })
    }
  } finally {
    busy.value = false
  }
}

async function submit() {
  await action(async () => {
    switch (mode.value) {
      case 'register':
        await api('/auth/register', 'POST', { name: name.value, email: email.value, password: password.value })
        password.value = ''
        await router.replace({ name: 'verify' })
        break
      case 'login':
        await api('/auth/login', 'POST', { email: email.value, password: password.value })
        password.value = ''
        await auth.getProfile()
        auth.notify()
        await router.replace({ name: 'account' })
        break
      case 'verify':
        await auth.authorized('/auth/verify-email', 'POST', { token: token.value })
        token.value = ''
        await auth.getProfile()
        await router.replace({ name: 'account' })
        break
      case 'forgot':
        await api('/auth/forgot-password', 'POST', { email: email.value })
        status.value = 'Jika email terdaftar, kode pemulihan akan dikirim.'
        complete.value = true
        break
      case 'reset':
        await api('/auth/reset-password', 'POST', { token: token.value, password: password.value })
        token.value = ''
        password.value = ''
        auth.clear()
        auth.notify()
        status.value = 'Kata sandi tersimpan. Masuk kembali untuk melanjutkan.'
        complete.value = true
        break
    }
  })
}

function resend() {
  return action(async () => {
    await auth.authorized('/auth/resend-verification', 'POST')
    status.value = 'Permintaan diterima. Cek kotak masuk dan folder spam.'
  })
}

function logout() {
  return action(async () => {
    await api('/auth/logout', 'POST')
    auth.clear()
    auth.notify()
    await router.replace({ name: 'login' })
  })
}
</script>

<template>
  <section class="card auth-card" aria-labelledby="page-title">
    <h1 id="page-title">{{ copy[mode][0] }}</h1>
    <p class="intro">{{ copy[mode][1] }}</p>
    <p v-if="mode === 'verify' && auth.profile" class="account-email">{{ auth.profile.email }}</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p class="notice success" role="status" :hidden="!status">{{ status }}</p>
    <p v-if="mode === 'verify' && !auth.profile" role="status">
      Jika pendaftaran dapat diteruskan, kode verifikasi dikirim. Masuk untuk memasukkan kode.
    </p>
    <form v-else-if="!complete" @submit.prevent="submit">
      <template v-if="mode === 'register'">
        <label for="name">Nama</label>
        <input id="name" v-model="name" autocomplete="name" maxlength="100" required
          :aria-invalid="!!fields.name" :aria-describedby="fields.name ? 'name-error' : undefined">
        <p v-if="fields.name" id="name-error" class="field-error">{{ fields.name }}</p>
      </template>
      <template v-if="showEmail">
        <label for="email">Email</label>
        <input id="email" v-model="email" type="email" autocomplete="email" maxlength="254" required
          :aria-invalid="!!fields.email" :aria-describedby="fields.email ? 'email-error' : undefined">
        <p v-if="fields.email" id="email-error" class="field-error">{{ fields.email }}</p>
      </template>
      <template v-if="showToken">
        <label for="token">Kode dari email</label>
        <input id="token" v-model="token" autocomplete="one-time-code" autocapitalize="none"
          spellcheck="false" maxlength="80" required>
      </template>
      <template v-if="showPassword">
        <label for="password">{{ mode === 'reset' ? 'Kata sandi baru' : 'Kata sandi' }}</label>
        <input id="password" v-model="password" type="password" maxlength="128" required
          :minlength="mode === 'login' ? 1 : 12"
          :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
          :aria-invalid="!!fields.password"
          :aria-describedby="fields.password ? 'password-error' : mode === 'login' ? undefined : 'password-hint'">
        <p v-if="fields.password" id="password-error" class="field-error">{{ fields.password }}</p>
        <p v-else-if="mode !== 'login'" id="password-hint" class="hint">Gunakan 12 sampai 128 karakter.</p>
      </template>
      <button class="primary" type="submit" :disabled="busy">{{ busy ? 'Memproses…' : copy[mode][2] }}</button>
    </form>
    <div class="actions">
      <template v-if="mode === 'login'">
        <RouterLink to="/register">Buat akun</RouterLink>
        <RouterLink to="/forgot-password">Lupa kata sandi?</RouterLink>
      </template>
      <template v-else-if="mode === 'verify'">
        <template v-if="auth.profile">
          <button type="button" class="link-button" :disabled="busy" @click="resend">Kirim ulang kode</button>
          <button type="button" class="link-button" :disabled="busy" @click="logout">Keluar</button>
        </template>
        <RouterLink v-else to="/login">Masuk</RouterLink>
      </template>
      <template v-else>
        <RouterLink v-if="mode === 'forgot'" to="/reset-password">Saya sudah punya kode</RouterLink>
        <RouterLink to="/login">Masuk</RouterLink>
      </template>
    </div>
  </section>
</template>
