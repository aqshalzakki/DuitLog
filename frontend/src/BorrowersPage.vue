<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { type Op, newOp, send, useFinance } from './finance'
import { REASONS } from './messages'
import { rupiah } from './money'
import { useAuth } from './session'
import { useSync } from './sync/engine'
import { VaultError, useVault } from './vault/store'

type Borrower = { id: string; name: string; phone?: string; notes?: string; outstanding: string; archived: boolean
  status: string; version: number }

const auth = useAuth()
const vault = useVault()
const sync = useSync()
const finance = useFinance()
const busy = ref(false)
const message = ref<{ tone: string; text: string }>()
const form = ref({ name: '', phone: '', notes: '' })
const nameError = ref('')
const ops: Record<string, Op> = {} // one attempt per action until it gets a recorded answer

const online = computed(() => finance.live)
const list = computed(() => (finance.snapshot?.borrowers ?? []) as Borrower[])
const waiting = computed(() => sync.items.filter((item) => item.type === 'BORROWER' && item.state !== 'SYNCED'))

onMounted(() => Promise.all([finance.load(), sync.refresh()]))

async function run(key: string, path: string, body: Record<string, unknown>, done: string) {
  if (busy.value) return
  busy.value = true
  message.value = undefined
  try {
    let op = ops[key]
    if (!op || op.state === 'rejected' || op.state === 'confirmed') op = ops[key] = newOp(path)
    if (op.state !== 'checking') op.body = body
    await send(op)
    if (op.state === 'confirmed') {
      message.value = { tone: 'success', text: done }
      await finance.load()
    } else if (op.state === 'checking') {
      message.value = { tone: 'info', text: 'Hasilnya belum diketahui. Tekan lagi untuk memeriksa; tidak akan diterapkan dua kali.' }
    } else message.value = { tone: 'error', text: REASONS[op.code ?? ''] ?? 'Tindakan ini belum dapat diterapkan.' }
  } finally {
    busy.value = false
  }
}

async function add() {
  const name = form.value.name.trim()
  nameError.value = name ? '' : 'Isi nama peminjam.'
  if (!name) return
  const fields = { name, ...(form.value.phone.trim() ? { phone: form.value.phone.trim() } : {}),
    ...(form.value.notes.trim() ? { notes: form.value.notes.trim() } : {}) }
  if (vault.status === 'unlocked' && !vault.expired) {
    try {
      await sync.enqueue('BORROWER', fields)
      message.value = { tone: 'success', text: online.value ? 'Peminjam ditambahkan.' : 'Peminjam tersimpan offline dan dikirim saat online.' }
      form.value = { name: '', phone: '', notes: '' }
      void finance.load()
    } catch (error) {
      message.value = { tone: 'error', text: error instanceof VaultError ? REASONS[error.code] ?? 'Gagal menyimpan.' : 'Gagal menyimpan.' }
    }
    return
  }
  if (!auth.profile?.emailVerified) {
    message.value = { tone: 'error', text: 'Sedang offline. Buka Akses Offline untuk menambah peminjam di perangkat ini.' }
    return
  }
  await run('add', '/borrowers', fields, 'Peminjam ditambahkan.')
  if (ops.add?.state === 'confirmed') form.value = { name: '', phone: '', notes: '' }
}

const toggle = (b: Borrower) => run(b.id, `/borrowers/${b.id}/${b.archived ? 'reactivate' : 'archive'}`,
  { expectedVersion: b.version }, b.archived ? `${b.name} aktif kembali.` : `${b.name} diarsipkan.`)
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Piutang</h1>
    <div role="status" aria-live="polite">
      <p v-if="message" class="notice" :class="message.tone" data-borrower-message>{{ message.text }}</p>
    </div>
    <p v-if="finance.snapshot" class="intro">Total piutang {{ rupiah(finance.snapshot.state.receivables) }}<template v-if="!online">
      (data offline, terakhir diperbarui; saldo resmi mungkin sudah berubah)</template>.</p>

    <ul class="recent" data-borrowers>
      <li v-for="b in list" :key="b.id" :data-borrower="b.name">
        <div>
          <strong>{{ b.name }}</strong>
          <p>{{ b.status === 'PAID' ? 'Lunas' : 'Belum lunas' }}<template v-if="b.archived"> · Diarsipkan</template>
            <template v-if="b.phone"> · {{ b.phone }}</template><template v-if="b.notes"> · {{ b.notes }}</template></p>
        </div>
        <div class="row-end">
          <span>{{ rupiah(b.outstanding) }}</span>
          <button v-if="online && (b.archived || b.status === 'PAID')" type="button" class="link-button" :disabled="busy"
            @click="toggle(b)">{{ b.archived ? 'Aktifkan kembali' : 'Arsipkan' }}</button>
        </div>
      </li>
      <li v-for="item in waiting" :key="item.clientActivityId">
        <div><strong>{{ item.payload.name }}</strong><p>Belum tersinkron</p></div>
      </li>
    </ul>
    <p v-if="!list.length && !waiting.length" class="hint">Belum ada peminjam.</p>
    <p class="hint">Arsip hanya untuk peminjam yang sudah lunas. Peminjam yang lunas tidak diarsipkan otomatis.</p>

    <form novalidate @submit.prevent="add">
      <h2>Tambah peminjam</h2>
      <label for="borrower-name">Nama</label>
      <input id="borrower-name" v-model="form.name" autocomplete="off" maxlength="120" :aria-invalid="!!nameError"
        :aria-describedby="nameError ? 'borrower-name-error' : undefined">
      <p v-if="nameError" id="borrower-name-error" class="field-error">{{ nameError }}</p>
      <label for="borrower-phone">Telepon (opsional)</label>
      <input id="borrower-phone" v-model="form.phone" autocomplete="off" inputmode="tel" maxlength="40">
      <label for="borrower-notes">Catatan (opsional)</label>
      <input id="borrower-notes" v-model="form.notes" autocomplete="off" maxlength="500">
      <button class="primary" :disabled="busy">Tambah peminjam</button>
    </form>
  </section>
</template>
