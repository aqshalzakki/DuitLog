<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useFinance } from './finance'
import { accountZone, localInput, rupiah } from './money'
import { type Change, type Period, type Range, PERIODS, biggest, changeText, dateLabel, fetchReport, rangeLabel,
  reportError, share } from './report'

type Totals = { income: string; expense: string; net: string }
type IncomeExpense = {
  range: Range; comparison: Range; timezone: string; current: Totals; previous: Totals
  change: Record<'income' | 'expense' | 'net', Change>
  categories: { categoryId: string | null; name: string | null; archived: boolean; income: string; expense: string }[]
  series: { label: string; income: string; expense: string }[]
}
type Movement = {
  range: Range; opening: string; income: string; expense: string; loansOut: string; repaymentsIn: string
  snapshotDelta: string; closing: string; series: { label: string; closing: string }[]
}
type Receivables = {
  range: Range; opening: string; loans: string; repayments: string; closing: string
  borrowers: { borrowerId: string; name: string; archived: boolean; opening: string; loans: string; repayments: string; closing: string }[]
}

const FAMILIES = { 'income-expense': 'Pemasukan & pengeluaran', 'balance-movement': 'Pergerakan saldo', receivables: 'Piutang' }
type Family = keyof typeof FAMILIES

const route = useRoute()
const router = useRouter()
const finance = useFinance()
const today = ref(localInput().slice(0, 10))
const family = computed<Family>(() => (route.query.family as Family) in FAMILIES ? route.query.family as Family : 'income-expense')
const period = ref<Period>('month')
const date = ref(today.value)
const from = ref(today.value)
const to = ref(today.value)
const busy = ref(false)
const error = ref('')
const data = ref<IncomeExpense | Movement | Receivables>()
let latest = 0 // a slower earlier answer never replaces a newer one

const ie = computed(() => family.value === 'income-expense' ? data.value as IncomeExpense | undefined : undefined)
const mv = computed(() => family.value === 'balance-movement' ? data.value as Movement | undefined : undefined)
const rc = computed(() => family.value === 'receivables' ? data.value as Receivables | undefined : undefined)
const flowMax = computed(() => biggest(ie.value?.series.flatMap((s) => [s.income, s.expense]) ?? []))
const spending = computed(() => (ie.value?.categories ?? []).filter((c) => c.expense !== '0')
  .sort((a, b) => (BigInt(b.expense) > BigInt(a.expense) ? 1 : BigInt(b.expense) < BigInt(a.expense) ? -1 : 0)))
const spendMax = computed(() => biggest(spending.value.map((c) => c.expense)))
const trendMax = computed(() => biggest(mv.value?.series.map((s) => s.closing.replace('-', '')) ?? []))
const categoryName = (c: { name: string | null; archived: boolean; categoryId: string | null }) =>
  c.categoryId === null ? 'Tanpa kategori' : (c.name ?? 'Kategori') + (c.archived ? ' (diarsipkan)' : '')

async function load() {
  const mine = ++latest
  busy.value = true
  error.value = ''
  try {
    const reply = await fetchReport<IncomeExpense | Movement | Receivables>(family.value,
      { period: period.value, date: date.value, from: from.value, to: to.value })
    if (mine === latest) data.value = reply
  } catch (failure) {
    if (mine === latest) {
      data.value = undefined
      error.value = reportError(failure)
    }
  } finally {
    if (mine === latest) busy.value = false
  }
}

onMounted(async () => {
  await finance.load() // "today" must be the account zone's, or a zone behind Jakarta gets a future date
  const before = today.value
  today.value = localInput().slice(0, 10)
  if (date.value === before) date.value = today.value // only dates nobody changed meanwhile
  if (from.value === before) from.value = today.value
  if (to.value === before) to.value = today.value
  await load()
})
watch(family, () => {
  data.value = undefined
  void load()
})
const pick = (next: Family) => router.replace({ query: { ...route.query, family: next } })
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Laporan</h1>
    <p class="intro">Hanya transaksi terkonfirmasi di server. Item yang belum tersinkron dan transaksi terhapus tidak
      termasuk. Tanggal mengikuti zona waktu akun {{ accountZone() }}.</p>
    <nav class="tabs" aria-label="Jenis laporan">
      <button v-for="(name, key) in FAMILIES" :key="key" type="button" :aria-pressed="family === key"
        :class="family === key ? 'primary' : 'secondary'" @click="pick(key)">{{ name }}</button>
    </nav>

    <form class="inline" novalidate @submit.prevent="load">
      <label for="period">Periode</label>
      <select id="period" v-model="period">
        <option v-for="(name, key) in PERIODS" :key="key" :value="key">{{ name }}</option>
      </select>
      <template v-if="period === 'custom'">
        <label for="from">Dari</label><input id="from" v-model="from" type="date" :max="today">
        <label for="to">Sampai</label><input id="to" v-model="to" type="date" :max="today">
      </template>
      <template v-else>
        <label for="date">Tanggal dalam periode</label><input id="date" v-model="date" type="date" :max="today">
      </template>
      <button class="secondary" :disabled="busy">Tampilkan</button>
    </form>

    <div role="status" aria-live="polite">
      <p v-if="error" class="notice error" data-report-error>{{ error }}</p>
      <p v-else-if="busy && !data" class="hint">Memuat laporan…</p>
    </div>

    <template v-if="data">
      <p class="hint" data-report-range>Periode: {{ rangeLabel(data.range) }}<template v-if="ie">.
        Dibandingkan dengan {{ rangeLabel(ie.comparison) }}</template>.</p>

      <template v-if="ie">
        <dl class="details" data-report-summary>
          <div><dt>Pemasukan</dt><dd data-income>{{ rupiah(ie.current.income) }} · {{ changeText(ie.change.income) }}</dd></div>
          <div><dt>Pengeluaran</dt><dd data-expense>{{ rupiah(ie.current.expense) }} · {{ changeText(ie.change.expense) }}</dd></div>
          <div><dt>Selisih bersih</dt><dd data-net>{{ rupiah(ie.current.net) }} · {{ changeText(ie.change.net) }}</dd></div>
        </dl>
        <p class="hint">Pinjaman, pembayaran piutang, saldo awal, dan penyesuaian saldo bukan pemasukan atau pengeluaran.</p>

        <h2>Pemasukan vs pengeluaran</h2>
        <table class="report" data-flow>
          <caption class="visually-hidden">Pemasukan dan pengeluaran per {{ data.range.period === 'year' ? 'bulan' : 'hari' }}</caption>
          <thead><tr><th scope="col">Tanggal</th><th scope="col">Pemasukan</th><th scope="col">Pengeluaran</th></tr></thead>
          <tbody>
            <tr v-for="row in ie.series" :key="row.label">
              <th scope="row">{{ dateLabel(row.label) }}</th>
              <td><span class="bar in" :style="{ width: share(row.income, flowMax) + '%' }" aria-hidden="true"></span>{{ rupiah(row.income) }}</td>
              <td><span class="bar out" :style="{ width: share(row.expense, flowMax) + '%' }" aria-hidden="true"></span>{{ rupiah(row.expense) }}</td>
            </tr>
          </tbody>
        </table>

        <h2>Pengeluaran menurut kategori</h2>
        <p v-if="!spending.length" class="hint">Tidak ada pengeluaran pada periode ini.</p>
        <table v-else class="report" data-categories-report>
          <thead><tr><th scope="col">Kategori</th><th scope="col">Pengeluaran</th></tr></thead>
          <tbody>
            <tr v-for="c in spending" :key="c.categoryId ?? 'none'">
              <th scope="row">{{ categoryName(c) }}</th>
              <td><span class="bar out" :style="{ width: share(c.expense, spendMax) + '%' }" aria-hidden="true"></span>{{ rupiah(c.expense) }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <template v-if="mv">
        <dl class="details" data-movement>
          <div><dt>Saldo pembuka</dt><dd data-opening>{{ rupiah(mv.opening) }}</dd></div>
          <div><dt>+ Pemasukan</dt><dd>{{ rupiah(mv.income) }}</dd></div>
          <div><dt>− Pengeluaran</dt><dd>{{ rupiah(mv.expense) }}</dd></div>
          <div><dt>− Pinjaman keluar (memengaruhi saldo)</dt><dd>{{ rupiah(mv.loansOut) }}</dd></div>
          <div><dt>+ Pembayaran piutang masuk (memengaruhi saldo)</dt><dd>{{ rupiah(mv.repaymentsIn) }}</dd></div>
          <div><dt>± Selisih saldo awal dan penyesuaian</dt><dd>{{ rupiah(mv.snapshotDelta) }}</dd></div>
          <div><dt>= Saldo penutup</dt><dd data-closing>{{ rupiah(mv.closing) }}</dd></div>
        </dl>
        <h2>Tren saldo</h2>
        <table class="report" data-trend>
          <thead><tr><th scope="col">Tanggal</th><th scope="col">Saldo akhir</th></tr></thead>
          <tbody>
            <tr v-for="row in mv.series" :key="row.label">
              <th scope="row">{{ dateLabel(row.label) }}</th>
              <td><span class="bar" :class="row.closing.startsWith('-') ? 'out' : 'in'" aria-hidden="true"
                :style="{ width: share(row.closing.replace('-', ''), trendMax) + '%' }"></span>{{ rupiah(row.closing) }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <template v-if="rc">
        <dl class="details" data-receivables-report>
          <div><dt>Piutang awal</dt><dd>{{ rupiah(rc.opening) }}</dd></div>
          <div><dt>+ Pinjaman</dt><dd>{{ rupiah(rc.loans) }}</dd></div>
          <div><dt>− Pembayaran</dt><dd>{{ rupiah(rc.repayments) }}</dd></div>
          <div><dt>= Piutang akhir</dt><dd data-receivables-closing>{{ rupiah(rc.closing) }}</dd></div>
        </dl>
        <p class="hint">Termasuk pinjaman dan pembayaran yang tidak memengaruhi saldo.</p>
        <p v-if="!rc.borrowers.length" class="hint">Tidak ada piutang pada periode ini.</p>
        <table v-else class="report" data-borrowers-report>
          <thead><tr><th scope="col">Peminjam</th><th scope="col">Awal</th><th scope="col">Pinjaman</th>
            <th scope="col">Pembayaran</th><th scope="col">Akhir</th></tr></thead>
          <tbody>
            <tr v-for="b in rc.borrowers" :key="b.borrowerId">
              <th scope="row">{{ b.name }}{{ b.archived ? ' (diarsipkan)' : '' }}</th>
              <td>{{ rupiah(b.opening) }}</td><td>{{ rupiah(b.loans) }}</td><td>{{ rupiah(b.repayments) }}</td>
              <td>{{ rupiah(b.closing) }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <p class="hint">Ekspor PDF dan Excel belum tersedia.</p>
    </template>
  </section>
</template>
