<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useFinance } from './finance'
import { KINDS, formatTime, rupiah } from './money'
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

const state = computed(() => finance.snapshot?.state)
const waiting = computed(() => sync.items.filter((item) => item.state !== 'SYNCED'))
const action = computed(() => waiting.value.filter((item) => item.state === 'CONFLICT' || item.state === 'BLOCKED'))

onMounted(async () => {
  await Promise.all([finance.load(), sync.refresh()])
  if (finance.live && state.value?.opening === 'pending') return router.replace({ name: 'onboarding' })
  if (finance.live) {
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
    <p v-else-if="!finance.live" class="notice info">Saldo belum tersedia offline. Buka Akses Offline atau sambungkan ke internet.</p>
    <p v-if="state && !finance.live" class="hint" data-cache-time>Data offline, terakhir diperbarui {{ formatTime(finance.snapshot!.at) }}.
      Saldo resmi mungkin sudah berubah.</p>

    <p v-if="waiting.length" class="notice info" data-waiting>
      {{ waiting.length }} item belum tersinkron<template v-if="action.length">, {{ action.length }} perlu tindakan</template>.
      Estimasi belum tersedia. <RouterLink to="/sync">Buka Sinkronisasi</RouterLink>
    </p>

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
        <span>{{ row.amount ? sign(row) + rupiah(row.amount) : rupiah(row.targetBalance) }}</span>
      </li>
    </ul>
    <RouterLink v-if="finance.live" to="/history">Lihat semua riwayat</RouterLink>
    <p v-if="vault.status === 'hard'" class="hint"><RouterLink to="/offline">Buka Akses Offline</RouterLink> untuk melihat antrean di perangkat ini.</p>
  </section>
</template>
