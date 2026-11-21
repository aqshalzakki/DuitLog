<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { type Op, newOp, send, useFinance } from './finance'
import { REASONS } from './messages'
import { KINDS, formatTime, rupiah } from './money'
import { ApiError, useAuth } from './session'

type Activity = {
  id: string; kind: string; amount?: string; targetBalance?: string; snapshotDelta?: string; title?: string
  description?: string; effectiveAt: string; borrowerId?: string; categoryId?: string; affectCashBalance?: boolean
  deleted: boolean; version: number
}

const route = useRoute()
const auth = useAuth()
const finance = useFinance()
const id = String(route.params.id)
const activity = ref<Activity>()
const missing = ref(false)
const busy = ref(false)
const message = ref<{ tone: string; text: string; reload?: boolean }>()
const reason = ref('')
const dialog = ref<HTMLDialogElement>()
let op: Op | undefined // kept for the page's life so a retry after an unknown outcome reuses the attempt

const online = computed(() => !!auth.profile?.emailVerified)
const category = computed(() => finance.snapshot?.categories.find((c) => c.id === activity.value?.categoryId))
const borrower = computed(() => finance.snapshot?.borrowers.find((b) => b.id === activity.value?.borrowerId))
const snapshot = computed(() => activity.value?.kind === 'OPENING' || activity.value?.kind === 'ADJUSTMENT')
const editPath = computed(() => activity.value && !snapshot.value && !activity.value.deleted
  ? { path: '/add/' + activity.value.kind.toLowerCase(), query: { edit: id } } : undefined)

async function load() {
  try {
    activity.value = await auth.authorized<Activity>('/activities/' + id)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) missing.value = true
    else message.value = { tone: 'error', text: 'Transaksi gagal dimuat.' }
  }
}

onMounted(() => Promise.all([finance.load(), load()]))

async function act(path: string, method: string, body: Record<string, unknown>, done: string) {
  if (busy.value || !activity.value) return
  busy.value = true
  message.value = undefined
  try {
    if (!op || op.path !== path || op.state === 'rejected' || op.state === 'confirmed') op = newOp(path, method)
    if (op.state !== 'checking') op.body = { expectedVersion: activity.value.version, ...body }
    await send(op)
    if (op.state === 'confirmed') {
      message.value = { tone: 'success', text: done }
      await Promise.all([load(), finance.load()])
    } else if (op.state === 'checking') {
      message.value = { tone: 'info', text: 'Hasilnya belum diketahui. Tekan lagi untuk memeriksa; tidak akan diterapkan dua kali.' }
    } else {
      message.value = { tone: 'error', text: REASONS[op.code ?? ''] ?? 'Tindakan ini belum dapat diterapkan.',
        reload: op.code === 'VERSION_CONFLICT' }
    }
  } finally {
    busy.value = false
  }
}

function openDelete() {
  reason.value = ''
  dialog.value?.showModal()
}

async function confirmDelete() {
  dialog.value?.close()
  await act('/activities/' + id, 'DELETE', reason.value.trim() ? { reason: reason.value.trim() } : {},
    'Transaksi dihapus. Saldo dan piutang sudah dihitung ulang. Bisa dipulihkan dari Baru dihapus.')
}

const restore = () => act('/activities/' + id + '/restore', 'POST', {}, 'Transaksi dipulihkan pada waktu efektif aslinya.')
const sign = (kind: string) => (kind === 'DEDUCT' || kind === 'LOAN' ? '−' : '+')
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Detail transaksi</h1>
    <div role="status" aria-live="polite">
      <p v-if="message" class="notice" :class="message.tone" data-activity-message>{{ message.text }}
        <button v-if="message.reload" type="button" class="link-button" @click="load(); message = undefined">Muat ulang</button>
      </p>
    </div>
    <p v-if="!online" class="notice info">Detail dan perubahan transaksi tercatat hanya tersedia saat online.</p>
    <p v-else-if="missing" class="notice error" role="alert">Transaksi tidak ditemukan.</p>
    <template v-else-if="activity">
      <p v-if="activity.deleted" class="notice info">Transaksi ini sudah dihapus dan tidak dihitung dalam saldo maupun laporan.</p>
      <dl class="details">
        <div><dt>Jenis</dt><dd>{{ KINDS[activity.kind] }}</dd></div>
        <div v-if="activity.amount"><dt>Nominal</dt><dd data-amount>{{ sign(activity.kind) }}{{ rupiah(activity.amount) }}</dd></div>
        <div v-else><dt>Target saldo</dt><dd>{{ rupiah(activity.targetBalance) }} (selisih saat ini {{ rupiah(activity.snapshotDelta) }})</dd></div>
        <div><dt>Waktu efektif</dt><dd>{{ formatTime(activity.effectiveAt) }}</dd></div>
        <div v-if="activity.title"><dt>Judul</dt><dd>{{ activity.title }}</dd></div>
        <div v-if="!snapshot && !activity.borrowerId"><dt>Kategori</dt>
          <dd>{{ category ? category.name + (category.archived ? ' (diarsipkan)' : '') : 'Tanpa kategori' }}</dd></div>
        <div v-if="activity.borrowerId"><dt>Peminjam</dt><dd>{{ borrower?.name ?? '—' }}</dd></div>
        <div v-if="activity.affectCashBalance !== undefined && activity.affectCashBalance !== null"><dt>Pengaruh saldo</dt>
          <dd>{{ activity.affectCashBalance ? 'Memengaruhi saldo utama' : 'Tidak memengaruhi saldo' }}</dd></div>
        <div v-if="activity.description"><dt>Deskripsi</dt><dd>{{ activity.description }}</dd></div>
      </dl>
      <p v-if="snapshot" class="hint">Saldo awal dan penyesuaian adalah titik saldo resmi dan tidak dapat diubah atau dihapus.
        Perubahan transaksi sebelumnya hanya mengubah selisihnya, bukan targetnya.</p>
      <div v-if="!snapshot" class="actions">
        <RouterLink v-if="editPath" :to="editPath">Ubah</RouterLink>
        <button v-if="!activity.deleted" type="button" class="secondary" :disabled="busy" @click="openDelete">Hapus</button>
        <button v-else type="button" class="secondary" :disabled="busy" @click="restore">Pulihkan</button>
      </div>
    </template>
    <RouterLink to="/history">Kembali ke Riwayat</RouterLink>

    <dialog ref="dialog" aria-labelledby="delete-title" class="card">
      <form method="dialog" @submit.prevent="confirmDelete">
        <h2 id="delete-title">Hapus transaksi?</h2>
        <p>Saldo, piutang, dan selisih saldo awal/penyesuaian sesudahnya akan dihitung ulang. Transaksi tetap ada di
          Baru dihapus dan bisa dipulihkan. Penghapusan bisa ditolak bila membuat piutang negatif.</p>
        <label for="delete-reason">Alasan (opsional)</label>
        <textarea id="delete-reason" v-model="reason" rows="2" maxlength="500"></textarea>
        <div class="actions">
          <button class="secondary">Hapus transaksi</button>
          <button type="button" class="link-button" @click="dialog?.close()">Batal</button>
        </div>
      </form>
    </dialog>
  </section>
</template>
