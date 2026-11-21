<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEntries } from './finance'
import { ApiError, api, type Device, useAuth } from './session'
import { useSync } from './sync/engine'
import { enrolledOwner, useVault } from './vault/store'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const devices = ref<Device[]>([])
const showDevices = computed(() => route.name === 'sessions')
const busy = ref(false)
const error = ref('')
const status = ref('')
const sync = useSync()
const vault = useVault()
const entries = useEntries()
const asking = ref<boolean>()
const revoking = ref<Device>()
watch(showDevices, () => { asking.value = revoking.value = undefined }) // /account and /sessions share this page
// PR-OFF-10: logout with pending is allowed, after a warning. Nothing local is deleted either way.
const pending = computed(() => sync.items.filter((item) => item.state !== 'SYNCED').length)
const unsure = computed(() => Object.values(entries.drafts).filter((d) =>
  [d.op, d.borrowerOp].some((op) => op?.state === 'sending' || op?.state === 'checking')).length)
// A locked vault cannot be counted; say so instead of claiming there is nothing pending.
const locked = computed(() => enrolledOwner() === auth.profile?.id && vault.status !== 'unlocked')
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

function logout(all: boolean, confirmed = false) {
  if (!confirmed && (pending.value || unsure.value || locked.value)) {
    revoking.value = undefined
    asking.value = all
    return
  }
  asking.value = undefined
  return action(async () => {
    if (all) await auth.authorized('/auth/logout-all', 'POST')
    else await api('/auth/logout', 'POST')
    await exit()
  })
}

function revoke(device: Device, confirmed = false) {
  // Revoking this device's own session is a logout: same warning (PR-OFF-10).
  if (device.current && !confirmed && (pending.value || unsure.value || locked.value)) {
    revoking.value = device
    return
  }
  revoking.value = undefined
  return action(async () => {
    await auth.authorized('/sessions/' + encodeURIComponent(device.id), 'DELETE')
    if (device.current) await exit()
    else {
      await load()
      status.value = 'Akses sesi perangkat dicabut.'
    }
  })
}

onMounted(() => {
  void action(load)
  void sync.refresh()
})
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
    <div v-if="asking !== undefined || revoking" class="notice info" role="alert" data-logout-warning>
      <strong>{{ revoking ? 'Cabut sesi ini dan keluar sekarang?' : `Keluar ${asking ? 'dari semua perangkat ' : ''}sekarang?` }}</strong>
      <p v-if="pending">{{ pending }} transaksi di perangkat ini belum tersinkron.</p>
      <p v-if="unsure">{{ unsure }} transaksi online sedang diperiksa hasilnya; cek Riwayat setelah masuk lagi.</p>
      <p v-if="locked">Akses Offline terkunci, jadi transaksi yang belum tersinkron tidak dapat dihitung.</p>
      <p>Data offline tetap terenkripsi di perangkat ini dan hanya terbuka lagi untuk akun ini. Transaksi yang belum
        tersinkron baru terkirim setelah kamu masuk kembali dan membuka Akses Offline.</p>
      <div class="actions">
        <button type="button" class="secondary" :disabled="busy"
          @click="revoking ? revoke(revoking, true) : logout(!!asking, true)">Tetap keluar</button>
        <button type="button" class="secondary" :disabled="busy" @click="asking = revoking = undefined">Batal</button>
      </div>
    </div>
    <div class="actions">
      <button type="button" class="link-button" :disabled="busy" @click="logout(false)">Keluar</button>
      <button v-if="showDevices" type="button" class="link-button" :disabled="busy"
        @click="logout(true)">Keluar dari semua perangkat</button>
    </div>
  </section>
</template>
