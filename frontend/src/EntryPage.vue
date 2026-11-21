<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ACCEPT, checkFile, evidenceError, sizeText, uploadEvidence } from './evidence'
import { check, newOp, send, useEntries, useFinance } from './finance'
import { REASONS } from './messages'
import { KINDS, accountZone, instant, localInput, parseAmount, rupiah } from './money'
import { ApiError, useAuth } from './session'
import { SyncError, useSync } from './sync/engine'
import { VaultError, useVault } from './vault/store'

const KIND_BY_PATH: Record<string, string> = { increase: 'INCREASE', deduct: 'DEDUCT', loan: 'LOAN', repayment: 'REPAYMENT' }
const route = useRoute()
const router = useRouter()
const auth = useAuth()
const vault = useVault()
const sync = useSync()
const finance = useFinance()
const entries = useEntries()

const kind = KIND_BY_PATH[route.params.kind as string] ?? 'INCREASE'
const receivable = kind === 'LOAN' || kind === 'REPAYMENT'
const fixId = typeof route.query.fix === 'string' ? route.query.fix : undefined
const editId = typeof route.query.edit === 'string' ? route.query.edit : undefined
const key = fixId ? 'fix:' + fixId : editId ? 'edit:' + editId : kind
const busy = ref(false)
const failure = ref('')
const errors = ref<Record<string, string>>({})

const viaVault = computed(() => vault.status === 'unlocked' && !vault.expired)
const online = computed(() => !!auth.profile?.emailVerified)
// Evidence goes up only after the activity is confirmed online (BR-FILE-04); a queued offline item has no
// server id yet, so there the file is attached later from the transaction detail.
const direct = computed(() => online.value && !viaVault.value && !editId && !fixId)
const evidenceFile = ref<File>()
const evidenceUpload = ref('') // one upload id per chosen file, reused by "Coba lagi"
const evidenceState = ref<{ tone: string; text: string; retry?: boolean }>()

function pickEvidence(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  const problem = file && checkFile(file)
  errors.value = { ...errors.value, evidence: problem ?? '' }
  evidenceFile.value = file && !problem ? file : undefined
  evidenceUpload.value = crypto.randomUUID()
  if (problem) (event.target as HTMLInputElement).value = ''
}

async function attachEvidence() {
  const activityId = draft.op?.result?.resourceId
  if (!evidenceFile.value || !activityId) return
  evidenceState.value = { tone: 'info', text: 'Mengunggah bukti…' }
  try {
    await uploadEvidence(activityId, evidenceFile.value, evidenceUpload.value)
    evidenceState.value = { tone: 'success', text: 'Bukti diunggah dan sedang diperiksa sebelum bisa dibuka.' }
  } catch (error) {
    evidenceState.value = { tone: 'error', text: evidenceError(error), retry: true }
  }
}

function fresh(): Record<string, string | boolean> {
  return { amount: '', when: localInput(), title: '', description: '', categoryId: '', borrower: '', affect: true,
    newBorrower: '' }
}
const draft = entries.draft(key, fresh)
const f = draft.fields
// From a borrower's page: preselect it on a form nobody has started.
if (receivable && typeof route.query.borrower === 'string' && !f.borrower && !draft.op && !draft.queued) {
  f.borrower = 's:' + route.query.borrower
}

const queuedItem = computed(() => sync.items.find((item) => item.clientActivityId === draft.queued))
const pendingBorrowers = computed(() => sync.items.filter((item) => item.type === 'BORROWER' && item.state !== 'SYNCED'))
// An edit may keep the archived borrower or category it already has; nothing archived can be newly chosen.
const borrowers = computed(() => (finance.snapshot?.borrowers ?? []).filter((b) => !b.archived || 's:' + b.id === f.kept))
const categories = computed(() => (finance.snapshot?.categories ?? []).filter((c) => !c.archived || c.id === f.kept))
const chosen = computed(() => borrowers.value.find((b) => 's:' + b.id === f.borrower))
const locked = computed(() => busy.value || !!draft.queued || (!!draft.op && draft.op.state !== 'rejected'))

onMounted(async () => {
  await Promise.all([finance.load(), sync.refresh()])
  if (finance.live && finance.snapshot?.state.opening === 'pending') return router.replace({ name: 'onboarding' })
  if (!f.whenSet && !f.original) f.when = localInput() // shown in the account zone, now that it is known
  if (fixId && !draft.loaded) {
    const item = sync.items.find((entry) => entry.clientActivityId === fixId)
    if (item) {
      const p = item.payload
      Object.assign(f, {
        amount: p.amount ?? '', when: p.effectiveAt ? localInput(Date.parse(p.effectiveAt as string)) : localInput(),
        title: p.title ?? '', description: p.description ?? '', categoryId: p.categoryId ?? '',
        borrower: p.borrowerId ? 's:' + p.borrowerId : p.borrowerClientId ? 'c:' + p.borrowerClientId : '',
        affect: p.affectCashBalance !== false, original: p.effectiveAt ?? '',
      })
    }
    draft.loaded = true
  }
  // A finished edit starts over from the server's current version; an unfinished one survives a Soft Lock.
  if (editId && (!draft.loaded || draft.op?.state === 'confirmed')) await loadEdit()
})

/** Confirmed activity edit: online only, against the version shown. */
async function loadEdit() {
  failure.value = ''
  try {
    const a = await auth.authorized<Record<string, any>>('/activities/' + editId) // eslint-disable-line @typescript-eslint/no-explicit-any
    if (a.kind !== kind || a.deleted) {
      failure.value = 'Transaksi ini tidak dapat diubah di sini.'
      return
    }
    const borrower = a.borrowerId ? 's:' + a.borrowerId : ''
    Object.assign(f, {
      amount: a.amount, when: localInput(Date.parse(a.effectiveAt)), whenSet: false, original: a.effectiveAt,
      title: a.title ?? '', description: a.description ?? '', categoryId: a.categoryId ?? '', borrower,
      affect: a.affectCashBalance !== false, version: a.version, kept: borrower || a.categoryId || '',
    })
    draft.op = undefined
    draft.loaded = true
  } catch (error) {
    failure.value = error instanceof ApiError && error.status === 404 ? 'Transaksi tidak ditemukan.' : 'Transaksi gagal dimuat.'
  }
}

function fields() {
  const next: Record<string, string> = {}
  const amount = parseAmount(String(f.amount))
  if (!amount) next.amount = 'Masukkan nominal Rupiah bulat lebih dari Rp0.'
  // An untouched time field means "now": the exact instant, not the minute shown (which could fall
  // before a snapshot taken seconds ago and be absorbed by it).
  // A correction keeps the original instant unless the time is edited.
  const at = f.whenSet ? instant(String(f.when)) : f.original || new Date(Date.now()).toISOString()
  // The device clock is only an early check; the server decides with its own time.
  if (!at) next.when = 'Masukkan tanggal dan waktu.'
  else if (Date.parse(at) > Date.now()) next.when = 'Waktu efektif tidak boleh di masa depan.'
  if (receivable && !f.borrower) next.borrower = 'Pilih peminjam.'
  errors.value = next
  if (Object.keys(next).length) return undefined
  const out: Record<string, unknown> = { kind, amount, effectiveAt: at }
  for (const name of ['title', 'description'] as const) if (String(f[name]).trim()) out[name] = String(f[name]).trim()
  if (!receivable && f.categoryId) out.categoryId = f.categoryId
  if (receivable) {
    const ref = String(f.borrower)
    out[ref.startsWith('c:') ? 'borrowerClientId' : 'borrowerId'] = ref.slice(2)
    out.affectCashBalance = !!f.affect
  }
  return out
}

function explain(error: unknown) {
  if (error instanceof VaultError) return REASONS[error.code] ?? 'Data offline tidak dapat dipakai.'
  if (error instanceof SyncError) return 'Item ini tidak dapat diubah sekarang. Periksa Sinkronisasi.'
  return 'Permintaan gagal diproses.'
}

async function save() {
  if (locked.value) return // one tap, one activity
  failure.value = ''
  const body = fields()
  if (!body) return
  busy.value = true
  try {
    if (fixId) {
      await sync.correct(fixId, body)
      entries.reset(key)
      await router.push('/sync')
    } else if (editId) {
      if (!online.value) failure.value = 'Mengubah transaksi tercatat hanya bisa saat online.'
      else if (draft.loaded) {
        draft.op ??= newOp('/activities/' + editId, 'PATCH')
        draft.op.body = { expectedVersion: f.version, ...body }
        await send(draft.op)
        if (draft.op.state === 'confirmed') void finance.load()
      }
    } else if (viaVault.value) {
      draft.queued = await sync.enqueue('ACTIVITY', body)
    } else if (online.value) {
      if (!draft.op || draft.op.state !== 'rejected') draft.op = newOp('/activities')
      draft.op.body = body
      await send(draft.op)
      if (draft.op.state === 'confirmed') {
        void finance.load()
        await attachEvidence()
      }
    } else {
      failure.value = 'Sedang offline. Buka Akses Offline untuk menyimpan transaksi di perangkat ini.'
    }
  } catch (error) {
    failure.value = explain(error)
  } finally {
    busy.value = false
  }
}

async function recheck() {
  if (!draft.op || busy.value) return
  busy.value = true
  try {
    await check(draft.op)
  } finally {
    busy.value = false
  }
}

async function addBorrower() {
  const name = String(f.newBorrower).trim()
  if (!name) {
    errors.value = { ...errors.value, newBorrower: 'Isi nama peminjam.' }
    return
  }
  busy.value = true
  failure.value = ''
  try {
    if (viaVault.value && !editId) { // an edit needs a server borrower id
      f.borrower = 'c:' + await sync.enqueue('BORROWER', { name })
    } else if (online.value) {
      if (!draft.borrowerOp || draft.borrowerOp.state === 'confirmed') draft.borrowerOp = newOp('/borrowers')
      draft.borrowerOp.body = { name }
      await send(draft.borrowerOp)
      if (draft.borrowerOp.state !== 'confirmed') {
        failure.value = draft.borrowerOp.state === 'checking' ? 'Hasil pembuatan peminjam belum diketahui. Coba lagi.'
          : REASONS[draft.borrowerOp.code ?? ''] ?? 'Peminjam belum dapat dibuat.'
        return
      }
      await finance.load()
      f.borrower = 's:' + draft.borrowerOp.result?.resourceId
    } else {
      failure.value = 'Sedang offline. Buka Akses Offline untuk menambah peminjam di perangkat ini.'
      return
    }
    f.newBorrower = ''
    errors.value = { ...errors.value, newBorrower: '' }
  } catch (error) {
    failure.value = explain(error)
  } finally {
    busy.value = false
  }
}

function again() {
  // New ids come with the next save; a reload would be a Hard Lock, so reset in place.
  Object.assign(f, fresh())
  draft.op = draft.borrowerOp = draft.queued = undefined
  evidenceFile.value = evidenceState.value = undefined
  errors.value = {}
  failure.value = ''
}

const result = computed(() => {
  const item = queuedItem.value
  if (item) {
    if (item.state === 'SYNCED') return { tone: 'success', title: 'Transaksi berhasil dicatat', text: 'Saldo resmi sudah diperbarui.' }
    if (item.state === 'CHECKING_OUTCOME') return { tone: 'info', title: 'Memeriksa hasil transaksi', text: 'Jangan catat ulang. Hasilnya diperiksa otomatis.' }
    if (item.state === 'CONFLICT' || item.state === 'BLOCKED') {
      return { tone: 'error', title: 'Transaksi belum dapat disimpan', text: REASONS[item.code ?? ''] ?? 'Perbaiki di Sinkronisasi.' }
    }
    return online.value && item.state === 'SYNCING'
      ? { tone: 'info', title: 'Menyinkronkan', text: 'Transaksi sedang dikirim.' }
      : { tone: 'info', title: 'Transaksi tersimpan offline', text: 'Masih tertunda dan belum masuk laporan resmi.' }
  }
  const op = draft.op
  if (!op || op.state === 'idle' || op.state === 'sending') return undefined
  if (op.state === 'confirmed' && editId) {
    return { tone: 'success', title: 'Perubahan tersimpan', text: 'Saldo, piutang, dan selisih snapshot sesudahnya sudah dihitung ulang.' }
  }
  if (op.state === 'confirmed') return { tone: 'success', title: 'Transaksi berhasil dicatat', text: op.code ? REASONS[op.code] : 'Saldo resmi sudah diperbarui.' }
  if (op.state === 'checking') return { tone: 'info', title: 'Memeriksa hasil transaksi', text: 'Respons tidak sampai. Jangan catat ulang; periksa hasilnya.' }
  return { tone: 'error', title: 'Transaksi belum dapat disimpan', text: REASONS[op.code ?? ''] ?? 'Periksa isian lalu simpan lagi.' }
})
const done = computed(() => !!draft.queued || draft.op?.state === 'confirmed')
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title" :data-entry-kind="kind">
    <h1 id="page-title">{{ fixId ? 'Perbaiki ' : editId ? 'Ubah ' : '' }}{{ KINDS[kind] }}</h1>
    <p v-if="failure" class="notice error" role="alert">{{ failure }}</p>
    <div role="status" aria-live="polite">
      <div v-if="result" class="notice" :class="result.tone" data-entry-result>
        <strong>{{ result.title }}</strong>
        <p>{{ result.text }}</p>
      </div>
      <div v-if="evidenceState" class="notice" :class="evidenceState.tone" data-entry-evidence>
        <p>{{ evidenceState.text }}</p>
        <div v-if="evidenceState.retry" class="actions">
          <button type="button" class="secondary small" @click="attachEvidence">Coba unggah lagi</button>
          <RouterLink v-if="draft.op?.result?.resourceId" :to="'/activity/' + draft.op.result.resourceId">Buka detail</RouterLink>
        </div>
      </div>
    </div>
    <p v-if="!viaVault && !online" class="notice error" role="alert">
      Sedang offline. <RouterLink :to="{ path: '/offline', query: { back: route.fullPath } }">Buka Akses Offline</RouterLink>
      untuk mencatat di perangkat ini.
    </p>
    <p v-if="viaVault && !online" class="hint">Offline: transaksi disimpan terenkripsi di perangkat dan dikirim saat online.</p>

    <form novalidate @submit.prevent="save">
      <fieldset :disabled="locked" class="plain">
        <label for="amount">Nominal (Rp)</label>
        <input id="amount" v-model="f.amount" inputmode="numeric" autocomplete="off" required
          :aria-invalid="!!errors.amount" :aria-describedby="errors.amount ? 'amount-error' : undefined">
        <p v-if="errors.amount" id="amount-error" class="field-error">{{ errors.amount }}</p>

        <template v-if="receivable">
          <label for="borrower">Peminjam</label>
          <select id="borrower" v-model="f.borrower" :aria-invalid="!!errors.borrower"
            :aria-describedby="errors.borrower ? 'borrower-error' : 'borrower-hint'">
            <option value="">Pilih peminjam</option>
            <option v-for="b in borrowers" :key="b.id" :value="'s:' + b.id">{{ b.name }} · sisa {{ rupiah(b.outstanding) }}</option>
            <option v-for="b in pendingBorrowers" :key="b.clientActivityId" :value="'c:' + b.clientActivityId">
              {{ b.payload.name }} (belum tersinkron)</option>
          </select>
          <p v-if="errors.borrower" id="borrower-error" class="field-error">{{ errors.borrower }}</p>
          <p id="borrower-hint" class="hint">
            <template v-if="kind === 'REPAYMENT' && chosen">Sisa piutang yang diketahui {{ rupiah(chosen.outstanding) }}. Keputusan akhir mengikuti kronologi di server.</template>
            <template v-else-if="String(f.borrower).startsWith('c:')">Menunggu profil peminjam tersinkron terlebih dahulu.</template>
          </p>
          <label for="new-borrower">Peminjam baru</label>
          <div class="inline">
            <input id="new-borrower" v-model="f.newBorrower" autocomplete="off"
              :aria-describedby="errors.newBorrower ? 'new-borrower-error' : undefined">
            <button type="button" class="secondary" @click="addBorrower">Tambah peminjam</button>
          </div>
          <p v-if="errors.newBorrower" id="new-borrower-error" class="field-error">{{ errors.newBorrower }}</p>
          <label class="check"><input v-model="f.affect" type="checkbox"> Memengaruhi saldo utama</label>
          <p class="hint">{{ f.affect ? (kind === 'LOAN' ? 'Pinjaman mengurangi saldo utama.' : 'Pembayaran menambah saldo utama.')
            : 'Tidak memengaruhi saldo: hanya piutang yang berubah.' }}</p>
        </template>

        <label for="when">Tanggal dan waktu efektif ({{ accountZone() }})</label>
        <input id="when" v-model="f.when" type="datetime-local" required @input="f.whenSet = true" :aria-invalid="!!errors.when"
          :aria-describedby="errors.when ? 'when-error' : undefined">
        <p v-if="errors.when" id="when-error" class="field-error">{{ errors.when }}</p>

        <details>
          <summary>Rincian opsional</summary>
          <label for="title">Judul</label>
          <input id="title" v-model="f.title" autocomplete="off" maxlength="120">
          <template v-if="!receivable">
            <label for="category">Kategori</label>
            <select id="category" v-model="f.categoryId">
              <option value="">Tanpa kategori</option>
              <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </template>
          <label for="description">Deskripsi</label>
          <textarea id="description" v-model="f.description" rows="3" maxlength="1000"></textarea>
          <template v-if="direct">
            <label for="evidence">Bukti (opsional)</label>
            <input id="evidence" type="file" :accept="ACCEPT" :aria-invalid="!!errors.evidence"
              :aria-describedby="errors.evidence ? 'evidence-error' : 'evidence-hint'" @change="pickEvidence">
            <p v-if="errors.evidence" id="evidence-error" class="field-error">{{ errors.evidence }}</p>
            <p v-else id="evidence-hint" class="hint">{{ evidenceFile ? evidenceFile.name + ' · ' + sizeText(evidenceFile.size)
              : 'JPG, PNG, WebP, atau PDF, maksimal 10 MB. Diunggah setelah transaksi tercatat.' }}</p>
          </template>
          <p v-else-if="!editId && !fixId" class="hint">Bukti bisa dilampirkan dari detail transaksi setelah tercatat di server.</p>
        </details>
        <button class="primary">{{ fixId ? 'Simpan perbaikan' : editId ? 'Simpan perubahan' : 'Simpan' }}</button>
      </fieldset>
    </form>

    <div class="actions">
      <button v-if="draft.op?.state === 'checking'" type="button" class="secondary" :disabled="busy" @click="recheck">Periksa hasil</button>
      <RouterLink v-if="queuedItem && queuedItem.state !== 'SYNCED'" to="/sync">Buka Sinkronisasi</RouterLink>
      <button v-if="editId && draft.op?.code === 'VERSION_CONFLICT'" type="button" class="secondary" :disabled="busy"
        @click="loadEdit">Muat versi terbaru</button>
      <RouterLink v-if="editId" :to="'/activity/' + editId">Kembali ke detail</RouterLink>
      <button v-if="done && !editId" type="button" class="secondary" @click="again">Catat lagi</button>
      <RouterLink v-if="done && !editId" to="/">Ke Beranda</RouterLink>
    </div>
  </section>
</template>
