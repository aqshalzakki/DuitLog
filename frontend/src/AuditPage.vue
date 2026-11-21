<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ACTIONS, EVIDENCE_REASONS } from './messages'
import { formatTime, rupiah } from './money'
import { useAuth } from './session'

type State = { balance: string; receivables: string }
type Item = {
  id: number; actor: string; action: string; actionAt: string
  details: {
    resourceId?: string; reason?: string; names?: string[]; fileName?: string; before?: Record<string, unknown> | null; after?: Record<string, unknown> | null
    snapshotChanges?: { id: string; targetBalance: string; beforeDelta?: string; afterDelta?: string }[]
    borrowerChanges?: { after: { name: string }; automaticallyReactivated: boolean }[]
    stateBefore?: State; stateAfter?: State
  }
}

const FIELDS: Record<string, string> = {
  amount: 'Nominal', effectiveAt: 'Waktu efektif', title: 'Judul', description: 'Deskripsi', categoryId: 'Kategori',
  borrowerId: 'Peminjam', affectCashBalance: 'Pengaruh saldo', name: 'Nama', phone: 'Telepon', notes: 'Catatan',
  archived: 'Diarsipkan', deleted: 'Dihapus', timezone: 'Zona waktu',
}

const auth = useAuth()
const items = ref<Item[]>([])
const next = ref<number | null>(null)
const failed = ref(false)

async function page(more = false) {
  failed.value = false
  try {
    const query = more && next.value !== null ? '?before=' + next.value : ''
    const reply = await auth.authorized<{ items: Item[]; nextCursor: number | null }>('/audit' + query)
    items.value = more ? [...items.value, ...reply.items] : reply.items
    next.value = reply.nextCursor
  } catch {
    failed.value = true
  }
}

onMounted(() => page())

const show = (value: unknown, key: string) => value === null || value === undefined ? '—'
  : key === 'amount' ? rupiah(String(value)) : key === 'effectiveAt' ? formatTime(String(value))
    : typeof value === 'boolean' ? (value ? 'Ya' : 'Tidak') : String(value)
/** Fields an edit or restore changed; ids for category/borrower are shown as changed, not resolved. */
function changes(item: Item) {
  const { before, after } = item.details
  if (!before || !after) return []
  return Object.keys(FIELDS).filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => ({ key, label: FIELDS[key], from: show(before[key], key), to: show(after[key], key) }))
}
const activity = (item: Item) => item.action.startsWith('ACTIVITY_') || item.action.startsWith('EVIDENCE_')
  || item.action === 'BALANCE_ADJUSTMENT'
  || item.action === 'OPENING_BALANCE'
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Audit</h1>
    <p class="intro">Urutan menurut waktu aksi di server, bukan waktu efektif transaksi. Catatan audit tidak dapat diubah.</p>
    <p v-if="failed" class="notice error" role="alert">Audit gagal dimuat. <button type="button" class="link-button" @click="page()">Coba lagi</button></p>
    <ol class="recent" data-audit>
      <li v-for="item in items" :key="item.id" :data-action="item.action">
        <div>
          <strong>{{ ACTIONS[item.action] ?? item.action }}</strong>
          <p>{{ formatTime(item.actionAt) }}<template v-if="item.actor.startsWith('system:')"> · Sistem</template><template
            v-else-if="item.actor !== auth.profile?.id"> · Operator: {{ item.actor }}</template></p>
          <p v-if="item.details.fileName">Berkas: {{ item.details.fileName }}</p>
          <p v-if="item.details.reason">Alasan: {{ EVIDENCE_REASONS[item.details.reason] ?? item.details.reason }}</p>
          <p v-if="item.details.names">{{ item.details.names.join(', ') }}</p>
          <p v-for="c in changes(item)" :key="c.key">{{ c.label }}: {{ c.from }} → {{ c.to }}</p>
          <p v-if="item.details.stateBefore && item.details.stateAfter">
            Saldo {{ rupiah(item.details.stateBefore.balance) }} → {{ rupiah(item.details.stateAfter.balance) }} ·
            Piutang {{ rupiah(item.details.stateBefore.receivables) }} → {{ rupiah(item.details.stateAfter.receivables) }}</p>
          <p v-for="s in item.details.snapshotChanges ?? []" :key="s.id" data-snapshot-change>
            Selisih titik saldo {{ rupiah(s.targetBalance) }}: {{ rupiah(s.beforeDelta ?? undefined) }} → {{ rupiah(s.afterDelta ?? undefined) }} (target tetap)</p>
          <p v-for="b in (item.details.borrowerChanges ?? []).filter((b) => b.automaticallyReactivated)" :key="b.after.name">
            {{ b.after.name }} diaktifkan kembali otomatis karena piutangnya kembali ada.</p>
          <RouterLink v-if="activity(item) && item.details.resourceId" :to="'/activity/' + item.details.resourceId">Lihat transaksi</RouterLink>
        </div>
      </li>
    </ol>
    <p v-if="!failed && !items.length" class="hint">Belum ada catatan audit.</p>
    <button v-if="next !== null" type="button" class="secondary" @click="page(true)">Muat lagi</button>
  </section>
</template>
