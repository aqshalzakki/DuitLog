<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { type Op, newOp, send, useFinance } from './finance'
import { REASONS } from './messages'
import { KINDS, formatTime, rupiah } from './money'
import { ApiError, useAuth } from './session'

type Borrower = { id: string; name: string; phone?: string; notes?: string; outstanding: string; archived: boolean
  status: string; version: number }
type Row = { id: string; kind: string; amount: string; title?: string; effectiveAt: string; sequence: number
  affectCashBalance?: boolean }

const route = useRoute()
const auth = useAuth()
const finance = useFinance()
const id = String(route.params.id)
const borrower = ref<Borrower>()
const rows = ref<Row[]>([])
const next = ref<number | null>(null)
const missing = ref(false)
const busy = ref(false)
const message = ref<{ tone: string; text: string }>()
let op: Op | undefined

async function load() {
  try {
    borrower.value = await auth.authorized<Borrower>('/borrowers/' + id)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) missing.value = true
    else message.value = { tone: 'error', text: 'Data peminjam gagal dimuat.' }
  }
}

async function page(more = false) {
  const query = new URLSearchParams({ borrowerId: id })
  if (more && next.value !== null) query.set('before', String(next.value))
  try {
    const reply = await auth.authorized<{ items: Row[]; nextCursor: number | null }>('/activities?' + query)
    rows.value = more ? [...rows.value, ...reply.items] : reply.items
    next.value = reply.nextCursor
  } catch {
    message.value = { tone: 'error', text: 'Riwayat peminjam gagal dimuat.' }
  }
}

onMounted(() => Promise.all([load(), page()]))

async function toggle() {
  const b = borrower.value
  if (!b || busy.value) return
  busy.value = true
  message.value = undefined
  try {
    const path = `/borrowers/${id}/${b.archived ? 'reactivate' : 'archive'}`
    if (!op || op.path !== path || op.state === 'rejected' || op.state === 'confirmed') op = newOp(path)
    if (op.state !== 'checking') op.body = { expectedVersion: b.version }
    await send(op)
    if (op.state === 'confirmed') {
      message.value = { tone: 'success', text: b.archived ? 'Peminjam aktif kembali.' : 'Peminjam diarsipkan.' }
      await Promise.all([load(), finance.load()])
    } else message.value = op.state === 'checking'
      ? { tone: 'info', text: 'Hasilnya belum diketahui. Tekan lagi untuk memeriksa; tidak akan diterapkan dua kali.' }
      : { tone: 'error', text: REASONS[op.code ?? ''] ?? 'Tindakan ini belum dapat diterapkan.' }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">{{ borrower?.name ?? 'Peminjam' }}</h1>
    <div role="status" aria-live="polite">
      <p v-if="message" class="notice" :class="message.tone" data-borrower-message>{{ message.text }}</p>
    </div>
    <p v-if="missing" class="notice error" role="alert">Peminjam tidak ditemukan.</p>
    <template v-else-if="borrower">
      <dl class="details" data-borrower-detail>
        <div><dt>Sisa piutang</dt><dd data-outstanding>{{ rupiah(borrower.outstanding) }}</dd></div>
        <div><dt>Status</dt><dd>{{ borrower.status === 'PAID' ? 'Lunas' : 'Belum lunas' }}{{ borrower.archived ? ' · Diarsipkan' : '' }}</dd></div>
        <div v-if="borrower.phone"><dt>Telepon</dt><dd>{{ borrower.phone }}</dd></div>
        <div v-if="borrower.notes"><dt>Catatan</dt><dd>{{ borrower.notes }}</dd></div>
      </dl>
      <div class="actions">
        <template v-if="!borrower.archived">
          <RouterLink :to="{ path: '/add/loan', query: { borrower: id } }">Catat pinjaman</RouterLink>
          <RouterLink :to="{ path: '/add/repayment', query: { borrower: id } }">Terima pembayaran</RouterLink>
        </template>
        <button v-if="borrower.archived || borrower.status === 'PAID'" type="button" class="secondary" :disabled="busy"
          @click="toggle">{{ borrower.archived ? 'Aktifkan kembali' : 'Arsipkan' }}</button>
      </div>
      <p v-if="borrower.archived" class="hint">Aktifkan kembali untuk mencatat pinjaman atau pembayaran baru.</p>

      <h2>Riwayat piutang</h2>
      <p v-if="!rows.length" class="hint">Belum ada pinjaman atau pembayaran.</p>
      <ul class="recent" data-borrower-history>
        <li v-for="row in rows" :key="row.id">
          <div>
            <RouterLink :to="'/activity/' + row.id"><strong>{{ row.title || KINDS[row.kind] }}</strong></RouterLink>
            <p>{{ KINDS[row.kind] }} · {{ formatTime(row.effectiveAt) }}<template v-if="row.affectCashBalance === false">
              · Tidak memengaruhi saldo</template></p>
          </div>
          <span>{{ row.kind === 'LOAN' ? '+' : '−' }}{{ rupiah(row.amount) }}</span>
        </li>
      </ul>
      <button v-if="next !== null" type="button" class="secondary" @click="page(true)">Muat lagi</button>
    </template>
    <RouterLink to="/borrowers">Kembali ke Piutang</RouterLink>
  </section>
</template>
