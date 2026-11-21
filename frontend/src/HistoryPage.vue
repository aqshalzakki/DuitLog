<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useFinance } from './finance'
import { KINDS, formatTime, rupiah } from './money'
import { ApiError, useAuth } from './session'
import { useSync } from './sync/engine'

type Row = {
  id: string; kind: string; amount?: string; targetBalance?: string; snapshotDelta?: string; title?: string
  effectiveAt: string; sequence: number; borrowerId?: string; categoryId?: string; affectCashBalance?: boolean
  deleted: boolean
}

const route = useRoute()
const auth = useAuth()
const sync = useSync()
const finance = useFinance()
const rows = ref<Row[]>([])
const next = ref<number | null>(null)
const busy = ref(false)
const failed = ref(false)
const deleted = computed(() => route.query.deleted === '1')
const online = computed(() => !!auth.profile?.emailVerified)
const waiting = computed(() => sync.items.filter((item) => item.type === 'ACTIVITY' && item.state !== 'SYNCED'))
const borrower = (id?: string) => finance.snapshot?.borrowers.find((b) => b.id === id)?.name
const STATES: Record<string, string> = {
  PENDING: 'Menunggu', SYNCING: 'Menyinkronkan', CHECKING_OUTCOME: 'Memeriksa hasil', RETRY_WAITING: 'Menunggu coba ulang',
  CONFLICT: 'Konflik', BLOCKED: 'Tertahan',
}

// PR-HIS-02: filters run on the server over confirmed activities; dates are in the account zone.
const empty = { q: '', kind: '', category: '', from: '', to: '' }
const filter = ref({ ...empty })
const applied = ref({ ...empty })
const filtering = computed(() => Object.values(applied.value).some((v) => v))
const categories = computed(() => finance.snapshot?.categories ?? [])
const invalid = ref(false)

let latest = 0 // switching Riwayat ↔ Baru dihapus mid-load: only the newest request may fill the list

async function page(more = false) {
  if (!online.value || (more && busy.value)) return
  const mine = ++latest
  busy.value = true
  failed.value = false
  invalid.value = false
  try {
    const query = new URLSearchParams()
    if (deleted.value) query.set('deleted', 'true')
    if (more && next.value !== null) query.set('before', String(next.value))
    for (const [key, value] of Object.entries(applied.value)) if (value) query.set(key, value.trim())
    const reply = await auth.authorized<{ items: Row[]; nextCursor: number | null }>('/activities?' + query)
    if (mine !== latest) return
    rows.value = more ? [...rows.value, ...reply.items] : reply.items
    next.value = reply.nextCursor
  } catch (error) {
    if (mine !== latest) return
    invalid.value = error instanceof ApiError && error.code === 'VALIDATION_ERROR'
    failed.value = !invalid.value
  } finally {
    if (mine === latest) busy.value = false
  }
}

onMounted(() => Promise.all([finance.load(), sync.refresh(), page()]))
watch(deleted, () => page())
function search() {
  applied.value = { ...filter.value }
  void page()
}
function reset() {
  filter.value = { ...empty }
  search()
}

const sign = (row: Row) => (row.kind === 'DEDUCT' || row.kind === 'LOAN' ? '−' : '+')
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">{{ deleted ? 'Baru dihapus' : 'Riwayat' }}</h1>
    <div class="actions">
      <RouterLink v-if="deleted" to="/history">Riwayat</RouterLink>
      <RouterLink v-else :to="{ path: '/history', query: { deleted: '1' } }">Baru dihapus</RouterLink>
    </div>

    <template v-if="!deleted && waiting.length">
      <h2>Belum tersinkron</h2>
      <p class="hint">Masih di perangkat ini. Posisinya sementara, bukan urutan final, dan belum masuk saldo resmi.</p>
      <ul class="recent" data-pending-list>
        <li v-for="item in waiting" :key="item.clientActivityId">
          <div>
            <strong>{{ item.payload.title || KINDS[item.payload.kind as string] }}</strong>
            <p>{{ KINDS[item.payload.kind as string] }} · {{ formatTime(item.payload.effectiveAt as string) }} · {{ STATES[item.state] }}</p>
          </div>
          <span>{{ rupiah(item.payload.amount as string) }}</span>
        </li>
      </ul>
      <RouterLink to="/sync">Buka Sinkronisasi</RouterLink>
    </template>

    <h2 v-if="!deleted && waiting.length">Tercatat</h2>
    <details v-if="online" class="panel" :open="filtering">
      <summary>Cari dan filter</summary>
      <form novalidate data-history-filter @submit.prevent="search">
        <label for="q">Cari judul atau deskripsi</label>
        <input id="q" v-model="filter.q" type="search" maxlength="100" autocomplete="off">
        <div class="filters">
        <div><label for="kind">Jenis</label>
        <select id="kind" v-model="filter.kind">
          <option value="">Semua jenis</option>
          <option v-for="(name, key) in KINDS" :key="key" :value="key">{{ name }}</option>
        </select></div>
        <div><label for="category">Kategori</label>
        <select id="category" v-model="filter.category">
          <option value="">Semua kategori</option>
          <option value="none">Tanpa kategori</option>
          <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}{{ c.archived ? ' (diarsipkan)' : '' }}</option>
        </select></div>
        <fieldset class="plain filters">
          <legend class="visually-hidden">Tanggal efektif</legend>
          <div><label for="from">Dari tanggal</label><input id="from" v-model="filter.from" type="date"></div>
          <div><label for="to">Sampai tanggal</label><input id="to" v-model="filter.to" type="date"></div>
        </fieldset>
        </div>
        <div class="actions">
          <button class="secondary" :disabled="busy">Terapkan</button>
          <button v-if="filtering" type="button" class="secondary" :disabled="busy" @click="reset">Hapus filter</button>
        </div>
      </form>
      <p class="hint">Filter berlaku untuk transaksi tercatat; yang belum tersinkron tetap tampil di atas.</p>
    </details>
    <p v-if="!online" class="notice info">Riwayat tercatat hanya tersedia saat online. Data di perangkat ini tidak memuat riwayat lengkap.</p>
    <p v-else-if="failed" class="notice error" role="alert">Riwayat gagal dimuat. <button type="button" class="link-button" @click="page()">Coba lagi</button></p>
    <p v-else-if="invalid" class="notice error" role="alert">Filter tidak valid. Periksa tanggalnya: "Dari" tidak boleh setelah "Sampai".</p>
    <div role="status" aria-live="polite">
      <p v-if="online && !failed && !invalid && !busy && !rows.length" class="hint" data-history-empty>{{ filtering
        ? 'Tidak ada transaksi yang cocok dengan filter.' : deleted ? 'Tidak ada transaksi yang dihapus.' : 'Belum ada transaksi.' }}</p>
    </div>
    <ul class="recent" data-history>
      <li v-for="row in rows" :key="row.id">
        <div>
          <RouterLink :to="'/activity/' + row.id"><strong>{{ row.title || KINDS[row.kind] }}</strong></RouterLink>
          <p>{{ KINDS[row.kind] }} · {{ formatTime(row.effectiveAt) }}<template v-if="borrower(row.borrowerId)"> · {{ borrower(row.borrowerId) }}</template>
            <template v-if="row.affectCashBalance === false"> · Tidak memengaruhi saldo</template></p>
        </div>
        <span :class="['amt', row.amount ? (sign(row) === '+' ? 'in' : 'out') : '']">{{ row.amount ? sign(row) + rupiah(row.amount) : 'Target ' + rupiah(row.targetBalance) }}</span>
      </li>
    </ul>
    <button v-if="next !== null" type="button" class="secondary" :disabled="busy" @click="page(true)">Muat lagi</button>
  </section>
</template>
