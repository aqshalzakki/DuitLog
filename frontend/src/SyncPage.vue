<script setup lang="ts">
import { ref } from 'vue'
import { type QueueItem, type State, SyncError, useSync } from './sync/engine'
import { VaultError, useVault } from './vault/store'

const sync = useSync()
const vault = useVault()
const notice = ref('')
const failure = ref('')
const date = new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' })
const money = new Intl.NumberFormat('id-ID')

const labels: Record<State, string> = {
  PENDING: 'Menunggu', SYNCING: 'Menyinkronkan', CHECKING_OUTCOME: 'Memeriksa hasil', RETRY_WAITING: 'Menunggu coba ulang',
  CONFLICT: 'Konflik', BLOCKED: 'Tertahan', SYNCED: 'Tersinkron',
}
const kinds: Record<string, string> = { INCREASE: 'Pemasukan', DEDUCT: 'Pengeluaran', LOAN: 'Pinjaman', REPAYMENT: 'Pelunasan' }
const reasons: Record<string, string> = {
  INVALID_FUTURE_EFFECTIVE_TIME: 'Waktu efektif berada di masa depan.',
  DEPENDENCY_BLOCKED: 'Menunggu aktivitas pendahulu.',
  ALREADY_CONFIRMED_ACTIVITY: 'Aktivitas ini sudah tercatat dari percobaan lain. Periksa riwayat sebelum membatalkan.',
  CATEGORY_ARCHIVED: 'Kategori sudah diarsipkan.',
  BORROWER_ARCHIVED: 'Peminjam sudah diarsipkan.',
  RECEIVABLE_NEGATIVE: 'Kronologi membuat piutang negatif.',
  VALIDATION_ERROR: 'Isian tidak valid.',
  OPENING_REQUIRED: 'Tentukan saldo awal terlebih dahulu.',
  TEMPORARY_FAILURE: 'Layanan sibuk, akan dicoba lagi.',
  FINANCIAL_INTEGRITY_FROZEN: 'Akun sedang dalam pemeriksaan integritas. Sinkronisasi ditahan.',
  FINANCIAL_RECOVERY_ACTIVE: 'Pemulihan finansial sedang berlangsung. Sinkronisasi ditahan.',
  SESSION_OWNER_MISMATCH: 'Sesi aktif milik akun lain. Tidak ada yang disinkronkan.',
  CORRUPTED: 'Data offline rusak atau tidak dapat diverifikasi. Antrean tidak ditampilkan.',
  LOCKED: 'Data offline terkunci.',
  EXPIRED: 'Validasi online diperlukan.',
}
const syncErrors: Record<string, string> = {
  IN_FLIGHT: 'Pengiriman sebelumnya belum dipastikan. Tunggu hasilnya dulu.',
  HAS_CHILDREN: 'Aktivitas lain bergantung pada item ini. Batalkan item tersebut dulu.',
  NOT_EDITABLE: 'Item ini tidak dapat diubah sekarang.',
  NOT_FOUND: 'Item tidak ditemukan.',
  INVALID: 'Isian tidak valid.',
}

function describe(item: QueueItem) {
  if (item.type === 'BORROWER') return `Peminjam baru: ${item.payload.name}`
  const title = item.payload.title ? ` · ${item.payload.title}` : ''
  return `${kinds[item.payload.kind as string] ?? item.payload.kind} Rp${money.format(BigInt(item.payload.amount as string))}${title}`
}

async function cancel(item: QueueItem) {
  notice.value = ''
  failure.value = ''
  try {
    await sync.cancel(item.clientActivityId)
    notice.value = 'Item dibatalkan dan dihapus dari perangkat ini.'
  } catch (error) {
    failure.value = error instanceof SyncError ? syncErrors[error.code]
      : error instanceof VaultError ? reasons[error.code] ?? 'Permintaan gagal diproses.' : 'Permintaan gagal diproses.'
  }
}
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title" :data-sync-running="sync.running">
    <h1 id="page-title">Sinkronisasi</h1>
    <p v-if="failure" class="notice error" role="alert">{{ failure }}</p>
    <p v-if="sync.error" class="notice error" role="alert" data-sync-error>{{ reasons[sync.error] ?? 'Sinkronisasi gagal. Akan dicoba lagi.' }}</p>
    <p class="notice success" role="status" :hidden="!notice">{{ notice }}</p>
    <p v-if="vault.status !== 'unlocked'" class="intro">Buka Akses Offline untuk melihat antrean di perangkat ini.</p>
    <template v-else>
      <p class="intro">Hanya data yang sudah tersinkron yang menjadi data resmi. Item lain masih tersimpan di perangkat ini.</p>
      <div class="actions">
        <button type="button" class="primary" :disabled="sync.running" @click="sync.cycle(true)">Sinkronkan sekarang</button>
      </div>
      <p v-if="!sync.items.length" class="hint">Tidak ada item di antrean.</p>
      <ul class="queue">
        <li v-for="item in sync.items" :key="item.clientActivityId" :data-client-id="item.clientActivityId" :data-state="item.state">
          <strong>{{ describe(item) }}</strong>
          <span class="state">{{ labels[item.state] }}</span>
          <span class="hint">Dicatat {{ date.format(new Date(item.createdAt)) }}</span>
          <span v-if="item.code && reasons[item.code]" class="hint">{{ reasons[item.code] }}</span>
          <button v-if="sync.editable(item)" type="button" class="secondary" @click="cancel(item)">Batalkan</button>
        </li>
      </ul>
    </template>
  </section>
</template>
