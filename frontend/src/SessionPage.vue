<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, api, type Device, useAuth } from './session'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const devices = ref<Device[]>([])
const showDevices = computed(() => route.name === 'sessions')
const busy = ref(false)
const error = ref('')
const status = ref('')
const date = new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' })

async function action(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  status.value = ''
  try {
    await work()
  } catch (failure) {
    error.value = failure instanceof ApiError ? failure.message : 'Layanan tidak dapat dihubungi.'
    if (failure instanceof ApiError && failure.status === 401) await router.replace({ name: 'login' })
  } finally {
    busy.value = false
  }
}

async function load() {
  if (showDevices.value) devices.value = await auth.authorized<Device[]>('/sessions')
  else await auth.authorized('/account/verified')
}

async function exit() {
  auth.clear()
  auth.notify()
  await router.replace({ name: 'login' })
}

function logout(all: boolean) {
  return action(async () => {
    if (all) await auth.authorized('/auth/logout-all', 'POST')
    else await api('/auth/logout', 'POST')
    await exit()
  })
}

function revoke(device: Device) {
  return action(async () => {
    await auth.authorized('/sessions/' + encodeURIComponent(device.id), 'DELETE')
    if (device.current) await exit()
    else {
      await load()
      status.value = 'Akses sesi perangkat dicabut.'
    }
  })
}

onMounted(() => { void action(load) })
</script>

<template>
  <section v-if="auth.profile" class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">{{ showDevices ? 'Perangkat' : 'Akun' }}</h1>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p class="notice success" role="status" :hidden="!status">{{ status }}</p>
    <template v-if="showDevices">
      <p class="intro">Kelola sesi yang dapat mengakses akunmu.</p>
      <p v-if="busy && !devices.length" role="status">Memuat sesi…</p>
      <ul v-if="devices.length" class="device-list">
        <li v-for="device in devices" :key="device.id">
          <div>
            <strong>{{ device.label }}{{ device.current ? ' · Sesi ini' : '' }}</strong>
            <p>Aktif {{ date.format(new Date(device.lastSeenAt)) }}</p>
            <p>Berakhir {{ date.format(new Date(device.expiresAt)) }}</p>
          </div>
          <button type="button" class="secondary" :disabled="busy"
            :aria-label="'Cabut sesi ' + device.label + (device.current ? ' ini' : '')"
            @click="revoke(device)">Cabut</button>
        </li>
      </ul>
      <p v-if="!busy && !devices.length && !error">Tidak ada sesi aktif.</p>
    </template>
    <template v-else>
      <dl class="details">
        <div><dt>Nama</dt><dd>{{ auth.profile.name }}</dd></div>
        <div><dt>Email terverifikasi</dt><dd>{{ auth.profile.email }}</dd></div>
      </dl>
      <RouterLink to="/sessions">Kelola perangkat</RouterLink>
    </template>
    <div class="actions">
      <button type="button" class="link-button" :disabled="busy" @click="logout(false)">Keluar</button>
      <button v-if="showDevices" type="button" class="link-button" :disabled="busy"
        @click="logout(true)">Keluar dari semua perangkat</button>
    </div>
  </section>
</template>
