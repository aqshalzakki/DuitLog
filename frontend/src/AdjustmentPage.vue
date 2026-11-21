<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { check, newOp, send, useEntries, useFinance } from './finance'
import { REASONS } from './messages'
import { parseSigned, rupiah } from './money'

const finance = useFinance()
const entries = useEntries()
const draft = entries.draft('adjustment', () => ({ value: '', review: false }))
const f = draft.fields
const busy = ref(false)
const error = ref('')
const target = computed(() => parseSigned(String(f.value)))
const current = computed(() => finance.snapshot?.state.balance)
const shown = computed(() => (f.review ? f.before : current.value) as string | undefined) // balance as reviewed
const delta = computed(() => target.value !== undefined && shown.value !== undefined
  ? (BigInt(target.value) - BigInt(shown.value)).toString() : undefined)
const done = computed(() => draft.op?.state === 'confirmed')
const locked = computed(() => busy.value || done.value || draft.op?.state === 'checking')

onMounted(() => finance.load())

function review() {
  error.value = target.value === undefined ? 'Masukkan saldo dalam Rupiah bulat. Boleh Rp0 atau negatif.' : ''
  if (!error.value) Object.assign(f, { review: true, before: current.value })
}

async function confirm() {
  if (busy.value || target.value === undefined) return
  busy.value = true
  error.value = ''
  try {
    if (!draft.op || draft.op.state === 'rejected') draft.op = newOp('/balance-adjustments')
    if (draft.op.state === 'checking') await check(draft.op)
    else {
      draft.op.body = { targetBalance: target.value }
      await send(draft.op)
    }
    if (draft.op.state === 'confirmed') await finance.load()
    else if (draft.op.state === 'checking') error.value = 'Hasilnya belum diketahui. Tekan lagi untuk memeriksa; tidak akan tercatat dua kali.'
    else error.value = REASONS[draft.op.code ?? ''] ?? 'Penyesuaian belum dapat disimpan.'
  } finally {
    busy.value = false
  }
}

function again() {
  Object.assign(f, { value: '', review: false, before: undefined })
  draft.op = undefined // the next adjustment is a new operation
}
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Sesuaikan saldo</h1>
    <p v-if="!finance.live" class="notice info">Penyesuaian saldo hanya tersedia saat online.</p>
    <template v-else>
      <p class="intro">Masukkan saldo kas yang benar saat ini. Penyesuaian menjadi titik saldo resmi pada waktu server saat
        disimpan, tidak bisa diberi tanggal mundur, dan bukan pemasukan atau pengeluaran.</p>
      <div role="status" aria-live="polite">
        <p v-if="done" class="notice success" data-adjust-result>Saldo disesuaikan menjadi {{ rupiah(target) }}.
          Transaksi sebelumnya yang diubah nanti hanya mengubah selisihnya; targetnya tetap.</p>
      </div>
      <p v-if="error" class="notice error" role="alert" data-adjust-error>{{ error }}</p>
      <form v-if="!f.review" novalidate @submit.prevent="review">
        <p>Saldo terkonfirmasi sekarang <strong data-current>{{ rupiah(current) }}</strong></p>
        <label for="target">Saldo sebenarnya (Rp)</label>
        <input id="target" v-model="f.value" inputmode="numeric" autocomplete="off" :disabled="locked"
          :aria-invalid="!!error" aria-describedby="target-hint">
        <p id="target-hint" class="hint">Boleh Rp0 atau negatif.</p>
        <button class="primary" :disabled="locked">Tinjau penyesuaian</button>
      </form>
      <template v-else>
        <dl class="details" data-adjust-summary>
          <div><dt>Saldo terkonfirmasi</dt><dd>{{ rupiah(shown) }}</dd></div>
          <div><dt>Target saldo</dt><dd>{{ rupiah(target) }}</dd></div>
          <div><dt>Selisih</dt><dd>{{ rupiah(delta) }}</dd></div>
          <div><dt>Waktu</dt><dd>Waktu server saat disimpan</dd></div>
        </dl>
        <div class="actions">
          <button v-if="!done" type="button" class="primary" :disabled="busy" @click="confirm">
            {{ draft.op?.state === 'checking' ? 'Periksa hasil' : 'Simpan penyesuaian' }}</button>
          <button v-if="!locked" type="button" class="link-button" @click="f.review = false">Ubah target</button>
          <button v-if="done" type="button" class="secondary" @click="again">Sesuaikan lagi</button>
          <RouterLink to="/">Ke Beranda</RouterLink>
        </div>
      </template>
    </template>
  </section>
</template>
