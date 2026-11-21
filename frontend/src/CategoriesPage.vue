<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { type Op, newOp, send, useFinance } from './finance'
import { REASONS } from './messages'

type Category = { id: string; name: string; archived: boolean; version: number }

const finance = useFinance()
const busy = ref(false)
const message = ref<{ tone: string; text: string }>()
const name = ref('')
const editing = ref<string>()
const rename = ref('')
const ops: Record<string, Op> = {}

const list = computed(() => (finance.snapshot?.categories ?? []) as Category[])
const active = computed(() => list.value.filter((c) => !c.archived))
const archived = computed(() => list.value.filter((c) => c.archived))

onMounted(() => finance.load())

async function run(key: string, path: string, method: string, body: Record<string, unknown>, done: string) {
  if (busy.value) return false
  busy.value = true
  message.value = undefined
  try {
    let op = ops[key]
    if (!op || op.state === 'rejected' || op.state === 'confirmed') op = ops[key] = newOp(path, method)
    if (op.state !== 'checking') op.body = body
    await send(op)
    if (op.state === 'confirmed') {
      message.value = { tone: 'success', text: done }
      await finance.load()
      return true
    }
    message.value = op.state === 'checking'
      ? { tone: 'info', text: 'Hasilnya belum diketahui. Tekan lagi untuk memeriksa; tidak akan diterapkan dua kali.' }
      : { tone: 'error', text: REASONS[op.code ?? ''] ?? 'Tindakan ini belum dapat diterapkan.' }
    return false
  } finally {
    busy.value = false
  }
}

async function add() {
  const value = name.value.trim()
  if (!value) {
    message.value = { tone: 'error', text: 'Isi nama kategori.' }
    return
  }
  if (await run('add', '/categories', 'POST', { name: value }, `Kategori ${value} ditambahkan.`)) name.value = ''
}

function startRename(c: Category) {
  editing.value = c.id
  rename.value = c.name
}

async function saveRename(c: Category) {
  const value = rename.value.trim()
  if (!value) return
  if (await run('rename:' + c.id, '/categories/' + c.id, 'PATCH', { expectedVersion: c.version, name: value }, 'Nama kategori diganti.')) {
    editing.value = undefined
  }
}

const toggle = (c: Category) => run(c.id, `/categories/${c.id}/${c.archived ? 'restore' : 'archive'}`, 'POST',
  { expectedVersion: c.version }, c.archived ? `${c.name} aktif kembali.` : `${c.name} diarsipkan. Transaksi lama tetap memakainya.`)
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title">
    <h1 id="page-title">Kategori</h1>
    <div role="status" aria-live="polite">
      <p v-if="message" class="notice" :class="message.tone" data-category-message>{{ message.text }}</p>
    </div>
    <p v-if="!finance.live" class="notice info">Pengelolaan kategori hanya tersedia saat online.</p>
    <template v-else>
      <p class="intro">Kategori opsional. Transaksi tanpa kategori dilaporkan sebagai Tanpa kategori.</p>
      <h2>Aktif</h2>
      <p v-if="!active.length" class="hint">Belum ada kategori aktif.</p>
      <ul class="recent" data-categories>
        <li v-for="c in active" :key="c.id" :data-category="c.name">
          <form v-if="editing === c.id" class="inline" @submit.prevent="saveRename(c)">
            <label :for="'rename-' + c.id" class="visually-hidden">Nama baru untuk {{ c.name }}</label>
            <input :id="'rename-' + c.id" v-model="rename" autocomplete="off" maxlength="60">
            <button class="secondary" :disabled="busy">Simpan</button>
            <button type="button" class="secondary small" @click="editing = undefined">Batal</button>
          </form>
          <template v-else>
            <strong>{{ c.name }}</strong>
            <div class="row-actions">
              <button type="button" class="secondary small" @click="startRename(c)">Ganti nama</button>
              <button type="button" class="secondary small" :disabled="busy" @click="toggle(c)">Arsipkan</button>
            </div>
          </template>
        </li>
      </ul>
      <template v-if="archived.length">
        <h2>Diarsipkan</h2>
        <p class="hint">Tidak bisa dipilih untuk transaksi baru, tetapi tetap tampil pada transaksi lama.</p>
        <ul class="recent">
          <li v-for="c in archived" :key="c.id" :data-category="c.name">
            <strong>{{ c.name }}</strong>
            <button type="button" class="secondary small" :disabled="busy" @click="toggle(c)">Aktifkan kembali</button>
          </li>
        </ul>
      </template>
      <form novalidate @submit.prevent="add">
        <h2>Tambah kategori</h2>
        <label for="category-name">Nama</label>
        <input id="category-name" v-model="name" autocomplete="off" maxlength="60">
        <button class="primary" :disabled="busy">Tambah kategori</button>
      </form>
    </template>
  </section>
</template>
