<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useFinance } from './finance'
import { KINDS, formatTime, rupiah } from './money'
import { type Change, PERIODS, type Period, type Range, changeText, fetchReport, rangeLabel, reportError } from './report'
import { useAuth } from './session'
import { useSync } from './sync/engine'
import { useVault } from './vault/store'

type Row = { id: string; kind: string; amount?: string; targetBalance?: string; title?: string; effectiveAt: string;
  affectCashBalance?: boolean }

const auth = useAuth()
const vault = useVault()
const sync = useSync()
const finance = useFinance()
const router = useRouter()
const recent = ref<Row[]>()
type Stats = { range: Range; current: { income: string; expense: string; net: string }; change: Record<string, Change> }
const period = ref<Exclude<Period, 'custom'>>('month')
const stats = ref<Stats>()
const statsError = ref('')
const fixed = Object.entries(PERIODS).filter(([key]) => key !== 'custom')
let latest = 0

/** Period statistics are online only; the current balance above does not depend on them. */
async function loadStats() {
  const mine = ++latest
  statsError.value = ''
  try {
    const reply = await fetchReport<Stats>('income-expense', { period: period.value })
    if (mine === latest) stats.value = reply
  } catch (failure) {
    if (mine === latest) {
      stats.value = undefined
      statsError.value = reportError(failure)
    }
  }
}

const state = computed(() => finance.snapshot?.state)
const waiting = computed(() => sync.items.filter((item) => item.state !== 'SYNCED'))
const action = computed(() => waiting.value.filter((item) => item.state === 'CONFLICT' || item.state === 'BLOCKED'))

onMounted(async () => {
  await Promise.all([finance.load(), sync.refresh()])
  if (finance.live && state.value?.opening === 'pending') return router.replace({ name: 'onboarding' })
  if (finance.live) {
    void loadStats()
    recent.value = (await auth.authorized<{ items: Row[] }>('/activities').catch(() => undefined))?.items.slice(0, 5)
  }
})

const sign = (row: Row) => (row.kind === 'DEDUCT' || row.kind === 'LOAN' ? '−' : '+')
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Beranda</h1>
    <p v-if="state?.recoveryActive" class="notice error" role="alert">Pemulihan finansial sedang berlangsung. Transaksi dan sinkronisasi ditahan.</p>
    <p v-if="state?.frozen" class="notice error" role="alert">Akun sedang dalam pemeriksaan integritas. Transaksi ditahan sampai operator selesai memeriksa.</p>

    <div v-if="state" class="figures">
      <div class="figure">
        <span>Saldo terkonfirmasi</span>
        <strong data-balance>{{ rupiah(state.balance) }}</strong>
      </div>
      <div class="figure">
        <span>Total piutang</span>
        <strong data-receivables>{{ rupiah(state.receivables) }}</strong>
      </div>
    </div>
    <p v-if="state && finance.live" class="hint"><RouterLink to="/adjust">Sesuaikan saldo</RouterLink> bila saldo
      tercatat berbeda dengan kas sebenarnya.</p>
    <p v-if="!state && !finance.live" class="notice info">Saldo belum tersedia offline. Buka Akses Offline atau sambungkan ke internet.</p>
    <p v-if="state && !finance.live" class="hint" data-cache-time>Data offline, terakhir diperbarui {{ formatTime(finance.snapshot!.at) }}.
      Saldo resmi mungkin sudah berubah.</p>

    <p v-if="waiting.length" class="notice info" data-waiting>
      {{ waiting.length }} item belum tersinkron<template v-if="action.length">, {{ action.length }} perlu tindakan</template>.
      Estimasi belum tersedia. <RouterLink to="/sync">Buka Sinkronisasi</RouterLink>
    </p>

    <template v-if="finance.live">
      <h2>Statistik</h2>
      <div class="inline">
        <label for="stats-period">Periode</label>
        <select id="stats-period" v-model="period" @change="loadStats">
          <option v-for="[key, name] in fixed" :key="key" :value="key">{{ name }}</option>
        </select>
      </div>
      <div role="status" aria-live="polite">
        <p v-if="statsError" class="notice error">{{ statsError }}</p>
      </div>
      <template v-if="stats">
        <p class="hint">{{ rangeLabel(stats.range) }} · hanya transaksi terkonfirmasi</p>
        <dl class="details stats" data-stats>
          <div><dt>Pemasukan</dt><dd data-stats-income>{{ rupiah(stats.current.income) }} · {{ changeText(stats.change.income) }}</dd></div>
          <div><dt>Pengeluaran</dt><dd data-stats-expense>{{ rupiah(stats.current.expense) }} · {{ changeText(stats.change.expense) }}</dd></div>
          <div><dt>Selisih bersih</dt><dd>{{ rupiah(stats.current.net) }} · {{ changeText(stats.change.net) }}</dd></div>
        </dl>
        <RouterLink to="/reports">Lihat laporan dan grafik</RouterLink>
      </template>
    </template>
    <p v-else class="hint">Statistik dan laporan hanya tersedia saat online.</p>

    <h2>Tambah</h2>
    <ul class="quick">
      <li><RouterLink to="/add/increase">Pemasukan</RouterLink></li>
      <li><RouterLink to="/add/deduct">Pengeluaran</RouterLink></li>
      <li><RouterLink to="/add/loan">Tambah piutang</RouterLink></li>
      <li><RouterLink to="/add/repayment">Terima pembayaran</RouterLink></li>
    </ul>

    <h2>Aktivitas terbaru</h2>
    <p v-if="!finance.live" class="hint">Riwayat terbaru tersedia saat online.</p>
    <p v-else-if="recent && !recent.length" class="hint">Belum ada transaksi. Catat transaksi pertama lewat Tambah di atas.</p>
    <ul v-else-if="recent" class="recent">
      <li v-for="row in recent" :key="row.id">
        <div>
          <RouterLink :to="'/activity/' + row.id"><strong>{{ row.title || KINDS[row.kind] }}</strong></RouterLink>
          <p>{{ KINDS[row.kind] }} · {{ formatTime(row.effectiveAt) }}<template v-if="row.affectCashBalance === false"> · Tidak memengaruhi saldo</template></p>
        </div>
        <span :class="['amt', row.amount ? (sign(row) === '+' ? 'in' : 'out') : '']">{{ row.amount ? sign(row) + rupiah(row.amount) : rupiah(row.targetBalance) }}</span>
      </li>
    </ul>
    <RouterLink v-if="finance.live" to="/history">Lihat semua riwayat</RouterLink>
    <p v-if="vault.status === 'hard'" class="hint"><RouterLink to="/offline">Buka Akses Offline</RouterLink> untuk melihat antrean di perangkat ini.</p>
  </section>
</template>
