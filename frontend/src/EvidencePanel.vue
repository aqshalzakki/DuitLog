<script setup lang="ts">
// Evidence of one confirmed activity (SCR-13, PR-FILE-01..06): status, view/download, replace, remove,
// and retry of a failed upload with the same upload id. Its state never changes the financial status.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  ACCEPT, EVIDENCE_STATES, type Evidence, checkFile, evidenceBlob, evidenceError, fetchEvidence, removeEvidence,
  sizeText, uploadEvidence,
} from './evidence'

const props = defineProps<{ activityId: string; deleted: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const evidence = ref<Evidence | null>()
const loadFailed = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const confirming = ref(false)
const preview = ref<string>() // object URL of an image being shown
const failed = ref<{ file: File; uploadId: string }>() // kept so "Coba lagi" reuses the upload id
const input = ref<HTMLInputElement>()
const polls = ref(0)
let timer: ReturnType<typeof setTimeout> | undefined

const image = computed(() => evidence.value?.contentType.startsWith('image/'))

async function load() {
  try {
    evidence.value = await fetchEvidence(props.activityId)
    loadFailed.value = false
  } catch {
    loadFailed.value = true
  }
  clearTimeout(timer)
  // The worker re-checks a new file within seconds; poll briefly, then let the user reload.
  if (evidence.value?.status === 'QUARANTINED' && polls.value < 30) {
    polls.value += 1
    timer = setTimeout(() => void load().then(() => evidence.value?.status !== 'QUARANTINED' && emit('changed')), 2000)
  }
}

function closePreview() {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = undefined
}

async function send(file: File, uploadId: string) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    evidence.value = await uploadEvidence(props.activityId, file, uploadId)
    failed.value = undefined
    notice.value = 'Bukti diunggah dan sedang diperiksa.'
    closePreview()
    polls.value = 0
    emit('changed')
    await load()
  } catch (problem) {
    failed.value = { file, uploadId }
    error.value = evidenceError(problem)
  } finally {
    busy.value = false
  }
}

function picked() {
  const file = input.value?.files?.[0]
  if (input.value) input.value.value = ''
  if (!file) return
  const problem = checkFile(file)
  if (problem) {
    error.value = problem
    return
  }
  void send(file, crypto.randomUUID())
}

async function show() {
  if (preview.value) return closePreview()
  busy.value = true
  error.value = ''
  try {
    preview.value = URL.createObjectURL(await evidenceBlob(props.activityId))
  } catch (problem) {
    error.value = evidenceError(problem)
  } finally {
    busy.value = false
  }
}

async function download() {
  if (!evidence.value) return
  busy.value = true
  error.value = ''
  try {
    const url = URL.createObjectURL(await evidenceBlob(props.activityId))
    const link = Object.assign(document.createElement('a'), { href: url, download: evidence.value.fileName })
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  } catch (problem) {
    error.value = evidenceError(problem)
  } finally {
    busy.value = false
  }
}

async function remove() {
  busy.value = true
  error.value = ''
  try {
    await removeEvidence(props.activityId)
    confirming.value = false
    closePreview()
    notice.value = 'Bukti dilepas dari transaksi.'
    emit('changed')
    await load()
  } catch (problem) {
    error.value = evidenceError(problem)
  } finally {
    busy.value = false
  }
}

onMounted(load)
onUnmounted(() => {
  clearTimeout(timer)
  closePreview()
})
</script>

<template>
  <section aria-labelledby="evidence-title" data-evidence>
    <h2 id="evidence-title">Bukti</h2>
    <div role="status" aria-live="polite">
      <p v-if="notice" class="notice success" data-evidence-notice>{{ notice }}</p>
    </div>
    <p v-if="error" class="notice error" role="alert" data-evidence-error>{{ error }}
      <button v-if="failed" type="button" class="secondary small" :disabled="busy"
        @click="send(failed.file, failed.uploadId)">Coba lagi</button></p>
    <p v-if="loadFailed" class="hint">Status bukti gagal dimuat. <button type="button" class="link-button" @click="load">Coba lagi</button></p>
    <p v-else-if="evidence === undefined" class="hint">Memuat bukti…</p>
    <p v-else-if="evidence === null" class="hint">Belum ada bukti. JPG, PNG, WebP, atau PDF, maksimal 10 MB.</p>
    <div v-else class="evidence" :data-evidence-status="evidence.status">
      <div>
        <strong>{{ evidence.fileName }}</strong>
        <p>{{ evidence.contentType === 'application/pdf' ? 'PDF' : 'Gambar' }} · {{ sizeText(evidence.size) }} ·
          <span class="state">{{ EVIDENCE_STATES[evidence.status] }}</span></p>
        <p v-if="evidence.status === 'QUARANTINED'" class="hint">Berkas diperiksa sebelum bisa dibuka.
          <button v-if="polls >= 30" type="button" class="link-button" @click="polls = 0; load()">Periksa lagi</button></p>
        <p v-if="evidence.status === 'REJECTED'" class="hint">Berkas tidak lolos pemeriksaan. Ganti dengan berkas lain.</p>
      </div>
      <div v-if="evidence.status === 'AVAILABLE'" class="row-actions">
        <button v-if="image" type="button" class="secondary small" :disabled="busy" :aria-expanded="!!preview"
          @click="show">{{ preview ? 'Tutup' : 'Lihat' }}</button>
        <button type="button" class="secondary small" :disabled="busy" @click="download">Unduh</button>
      </div>
    </div>
    <img v-if="preview" :src="preview" class="evidence-preview" :alt="'Pratinjau bukti ' + evidence?.fileName">

    <div v-if="!deleted && evidence !== undefined" class="actions">
      <label class="secondary file-button" :class="{ disabled: busy }">
        {{ evidence && evidence.status !== 'REJECTED' ? 'Ganti bukti' : 'Lampirkan bukti' }}
        <input ref="input" type="file" class="visually-hidden" :accept="ACCEPT" :disabled="busy" data-evidence-input
          @change="picked">
      </label>
      <button v-if="evidence && evidence.status !== 'REJECTED' && !confirming" type="button" class="secondary"
        :disabled="busy" @click="confirming = true">Hapus bukti</button>
    </div>
    <div v-if="confirming" class="notice info" data-evidence-confirm>
      <p>Lepas bukti ini dari transaksi? Transaksinya tidak berubah, dan pelepasan tercatat di audit.</p>
      <div class="actions">
        <button type="button" class="secondary" :disabled="busy" @click="remove">Ya, hapus bukti</button>
        <button type="button" class="secondary" :disabled="busy" @click="confirming = false">Batal</button>
      </div>
    </div>
  </section>
</template>
