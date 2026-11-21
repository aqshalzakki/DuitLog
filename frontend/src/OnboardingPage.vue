<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { newOp, send, check, useEntries, useFinance } from './finance'
import { REASONS } from './messages'
import { parseSigned, rupiah } from './money'

const finance = useFinance()
const entries = useEntries()
const draft = entries.draft('opening', () => ({ value: '' }))
const busy = ref(false)
const error = ref('')
const decided = ref(false)
const parsed = computed(() => parseSigned(String(draft.fields.value)))

onMounted(async () => {
  await finance.load()
  if (finance.snapshot && finance.snapshot.state.opening !== 'pending') decided.value = true
})

async function run(path: string, body: Record<string, unknown>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    // The same attempt is reused until the server gives a recorded answer.
    if (!draft.op || draft.op.path !== path || draft.op.state === 'rejected') {
      draft.op = newOp(path)
      draft.op.body = body
    }
    if (draft.op.state === 'checking') await check(draft.op)
    else await send(draft.op)
    const op = draft.op
    if (op.state === 'confirmed' || op.code === 'OPENING_ALREADY_DECIDED') {
      decided.value = true
      await finance.load()
    } else if (op.state === 'checking') error.value = 'Hasilnya belum diketahui. Tekan lagi untuk memeriksa; tidak akan tercatat dua kali.'
    else error.value = REASONS[op.code ?? ''] ?? 'Saldo awal belum dapat disimpan.'
  } finally {
    busy.value = false
  }
}

function record() {
  if (parsed.value === undefined) {
    error.value = 'Masukkan saldo dalam Rupiah bulat. Boleh Rp0 atau negatif.'
    return
  }
  void run('/onboarding/opening-balance', { targetBalance: parsed.value })
}
const skip = () => run('/onboarding/skip-opening-balance', {})
</script>

<template>
  <section class="card auth-card" aria-labelledby="page-title">
    <h1 id="page-title">{{ decided ? 'Akses Offline' : 'Saldo awal' }}</h1>
    <template v-if="!decided">
      <p class="intro">Masukkan saldo kas yang Anda miliki sekarang. Nilai ini menjadi titik awal resmi, termasuk bila
        Rp0. Pilih Lewati bila belum tahu: saldo mulai dari Rp0 tanpa titik awal, dan transaksi lampau tetap dihitung.</p>
      <form novalidate @submit.prevent="record">
        <label for="opening">Saldo saat ini (Rp)</label>
        <input id="opening" v-model="draft.fields.value" inputmode="numeric" autocomplete="off" :disabled="busy || draft.op?.state === 'checking'"
          :aria-invalid="!!error" :aria-describedby="error ? 'opening-error' : 'opening-hint'">
        <p id="opening-hint" class="hint">Boleh Rp0 atau negatif.</p>
        <p v-if="error" id="opening-error" class="field-error" role="alert">{{ error }}</p>
        <button class="primary" :disabled="busy">
          {{ parsed === undefined ? 'Simpan saldo awal' : `Konfirmasi saldo awal ${rupiah(parsed)}` }}</button>
      </form>
      <div class="actions">
        <button type="button" class="link-button" :disabled="busy" @click="skip">Lewati saldo awal</button>
      </div>
    </template>
    <template v-else>
      <p class="notice success" role="status">Saldo awal sudah ditentukan.</p>
      <p class="intro">Opsional: simpan transaksi terenkripsi di perangkat ini agar tetap bisa mencatat saat offline.
        Bisa diaktifkan nanti.</p>
      <div class="actions">
        <RouterLink to="/offline">Aktifkan Akses Offline</RouterLink>
        <RouterLink to="/">Nanti saja</RouterLink>
      </div>
    </template>
  </section>
</template>
