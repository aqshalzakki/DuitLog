<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useFinance } from './finance'
import { accountZone } from './money'
import { ApiError, useAuth } from './session'
import { type Theme, applyTheme, savedTheme } from './theme'

const auth = useAuth()
const finance = useFinance()
const theme = ref<Theme>(savedTheme())
watch(theme, applyTheme)

const zones = (() => {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return []
  }
})()
const current = computed(() => finance.snapshot?.state.timezone ?? accountZone())
// Browsers list canonical IANA names but not "UTC"; the current zone is always selectable.
const choices = computed(() => [...new Set([current.value, 'UTC', ...zones])])
const zone = ref(current.value)
const confirming = ref(false)
const busy = ref(false)
const message = ref('')
const error = ref('')

onMounted(async () => {
  await finance.load()
  zone.value = current.value
})

function review() {
  message.value = ''
  error.value = ''
  confirming.value = zone.value !== current.value
}

async function save() {
  busy.value = true
  error.value = ''
  try {
    await auth.authorized('/settings/timezone', 'PUT', { timezone: zone.value })
    await finance.load()
    message.value = `Zona waktu akun sekarang ${current.value}.`
    confirming.value = false
  } catch (failure) {
    error.value = failure instanceof ApiError
      ? failure.code === 'VALIDATION_ERROR' ? 'Zona waktu ini tidak dikenali server.' : 'Gagal menyimpan. Coba lagi.'
      : 'Zona waktu hanya bisa diubah saat online.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Pengaturan</h1>

    <fieldset class="choice">
      <legend>Tema tampilan</legend>
      <label><input v-model="theme" type="radio" name="theme" value="light"> Terang</label>
      <label><input v-model="theme" type="radio" name="theme" value="dark"> Gelap</label>
      <label><input v-model="theme" type="radio" name="theme" value="system"> Ikuti sistem</label>
    </fieldset>
    <p class="hint">Disimpan di perangkat ini saja.</p>

    <h2>Zona waktu akun</h2>
    <p class="hint" data-current-zone>Saat ini: {{ current }}</p>
    <template v-if="auth.profile && finance.live">
      <form novalidate @submit.prevent="review">
        <label for="zone">Zona waktu</label>
        <select id="zone" v-model="zone" @change="confirming = false">
          <option v-for="name in choices" :key="name" :value="name">{{ name }}</option>
        </select>
        <button class="secondary" :disabled="busy || zone === current">Simpan zona waktu</button>
      </form>
      <div v-if="confirming" class="notice info" role="alert" data-zone-warning>
        <strong>Ubah zona waktu ke {{ zone }}?</strong>
        <p>Pengelompokan tanggal di Laporan, Beranda dan Riwayat akan mengikuti zona baru, jadi transaksi lama bisa
          pindah ke tanggal atau bulan lain. Waktu transaksi yang tersimpan, saldo, dan piutang tidak berubah.</p>
        <div class="actions">
          <button type="button" class="secondary" :disabled="busy" @click="save">Ya, ubah zona waktu</button>
          <button type="button" class="secondary" :disabled="busy" @click="confirming = false">Batal</button>
        </div>
      </div>
    </template>
    <p v-else class="hint">Zona waktu hanya bisa diubah saat online.</p>
    <div role="status" aria-live="polite">
      <p v-if="message" class="notice success">{{ message }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>
    </div>
  </section>
</template>
