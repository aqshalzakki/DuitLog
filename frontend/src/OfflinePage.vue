<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { type Profile, useAuth } from './session'
import { VaultError, useVault, validPassphrase } from './vault/store'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const vault = useVault()
const busy = ref(false)
const error = ref('')
const notice = ref('')
const recoveryShown = ref('') // shown once during setup or rotation, cleared right after
const form = ref({ pin: '', passphrase: '', confirm: '', recovery: '', method: 'passphrase', secret: '', newPin: '',
  current: '', newPassphrase: '', erase: '' })
const date = new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' })
const online = computed(() => !!auth.profile?.emailVerified)

const messages: Record<string, string> = {
  WRONG_SECRET: 'Kunci tidak cocok. Periksa kembali dan coba lagi.',
  INVALID: 'Periksa isian. PIN 6 angka, passphrase minimal 12 karakter dan tidak memuat PIN.',
  EXISTS: 'Data offline untuk akun ini sudah ada di perangkat. Setup tidak menimpanya.',
  STORAGE: 'Penyimpanan perangkat gagal. Tidak ada yang disimpan.',
  CORRUPTED: 'Data offline rusak atau tidak dapat diverifikasi. Tidak ada data yang ditampilkan.',
  EXPIRED: 'Validasi online diperlukan sebelum data offline dapat dibuka.',
  LOCKED: 'Data offline terkunci.',
}

async function run(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await work()
  } catch (failure) {
    error.value = failure instanceof VaultError ? messages[failure.code] : 'Permintaan gagal diproses.'
  } finally {
    busy.value = false
  }
}

async function revalidate() {
  const profile = await auth.authorized<Profile>('/me')
  await vault.revalidate(profile)
}

const begin = () => run(async () => {
  const { pin, passphrase, confirm } = form.value
  if (!/^\d{6}$/.test(pin) || !validPassphrase(passphrase, pin) || passphrase !== confirm) throw new VaultError('INVALID')
  recoveryShown.value = await vault.prepare()
})

const enroll = () => run(async () => {
  await vault.enroll(form.value.pin, form.value.passphrase, form.value.recovery)
  recoveryShown.value = ''
  form.value = { ...form.value, pin: '', passphrase: '', confirm: '', recovery: '' }
  notice.value = 'Akses Offline aktif.'
})

const unlock = () => run(async () => {
  const secret = form.value.secret
  await vault.unlock(form.value.method === 'passphrase' ? { passphrase: secret } : { recovery: secret })
  form.value.secret = ''
  if (online.value) await revalidate().catch(() => undefined)
  notice.value = vault.expired ? '' : 'Data offline terbuka.'
  // Back to the page that asked for the unlock, in-app only (a full load would lock again).
  const back = route.query.back
  if (!vault.expired && typeof back === 'string' && back.startsWith('/') && !back.startsWith('//')) await router.replace(back)
})

const resetPin = () => run(async () => {
  await vault.resetPin(form.value.newPin)
  form.value.newPin = ''
  notice.value = 'PIN baru tersimpan.'
})

const changePassphrase = () => run(async () => {
  await vault.rotate({ passphrase: form.value.current }, { passphrase: form.value.newPassphrase })
  form.value = { ...form.value, current: '', newPassphrase: '' }
  notice.value = 'Passphrase diganti.'
})

const newRecovery = () => run(async () => { recoveryShown.value = vault.draftRecovery() })

const replaceRecovery = () => run(async () => {
  await vault.rotate({ passphrase: form.value.current }, { recovery: form.value.recovery })
  recoveryShown.value = ''
  form.value = { ...form.value, current: '', recovery: '' }
  notice.value = 'Recovery Key baru aktif. Recovery Key lama tidak berlaku.'
})

const validateNow = () => run(async () => {
  await revalidate()
  notice.value = vault.expired ? '' : 'Validasi online berhasil.'
})

const erase = () => run(async () => {
  if (form.value.erase !== 'HAPUS') throw new VaultError('INVALID')
  await vault.erase()
  form.value.erase = ''
  notice.value = 'Data offline di perangkat ini dihapus.'
})
</script>

<template>
  <section class="card account-card" aria-labelledby="page-title" :data-vault-status="vault.status">
    <h1 id="page-title">Akses Offline</h1>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p class="notice success" role="status" :hidden="!notice">{{ notice }}</p>

    <template v-if="vault.status === 'none' && !recoveryShown">
      <template v-if="online">
        <p class="intro">Opsional. Simpan draft dan transaksi tertunda terenkripsi di perangkat ini.</p>
        <form @submit.prevent="begin">
          <label for="pin">PIN 6 angka</label>
          <input id="pin" v-model="form.pin" inputmode="numeric" autocomplete="off" maxlength="6" pattern="\d{6}" required>
          <p class="hint">PIN hanya membuka kunci layar sementara, bukan pengganti passphrase.</p>
          <label for="passphrase">Passphrase</label>
          <input id="passphrase" v-model="form.passphrase" type="password" autocomplete="off" minlength="12" required>
          <p class="hint">Minimal 12 karakter dan tidak memuat PIN. Diperlukan setelah browser ditutup.</p>
          <label for="passphrase-confirm">Ulangi passphrase</label>
          <input id="passphrase-confirm" v-model="form.confirm" type="password" autocomplete="off" required>
          <button class="primary" :disabled="busy">Lanjut</button>
        </form>
      </template>
      <p v-else class="intro">Akses Offline belum aktif di perangkat ini. Aktifkan saat online.</p>
    </template>

    <form v-if="recoveryShown" @submit.prevent="vault.status === 'none' ? enroll() : replaceRecovery()">
      <h2>Recovery Key</h2>
      <p class="intro">Simpan di tempat aman di luar perangkat ini. Kunci ini tidak disimpan di server dan hanya
        ditampilkan sekali. Tanpa kunci ini dan passphrase, data offline tidak dapat dibuka.</p>
      <output id="recovery-key" class="recovery">{{ recoveryShown }}</output>
      <label for="recovery-confirm">Ketik ulang Recovery Key</label>
      <input id="recovery-confirm" v-model="form.recovery" autocomplete="off" spellcheck="false" required>
      <template v-if="vault.status !== 'none'">
        <label for="rotate-current">Passphrase saat ini</label>
        <input id="rotate-current" v-model="form.current" type="password" autocomplete="off" required>
      </template>
      <button class="primary" :disabled="busy">{{ vault.status === 'none' ? 'Aktifkan Akses Offline' : 'Ganti Recovery Key' }}</button>
    </form>

    <p v-if="vault.status === 'corrupt'" class="notice error" role="alert">
      Data offline di perangkat ini tidak lengkap atau rusak. Setup baru tidak akan menimpanya.
    </p>

    <form v-if="vault.status === 'hard'" @submit.prevent="unlock">
      <p class="intro">Data offline terkunci. Buka dengan passphrase atau Recovery Key. PIN tidak cukup setelah browser ditutup.</p>
      <fieldset class="choice">
        <legend>Cara membuka</legend>
        <label><input v-model="form.method" type="radio" value="passphrase" name="method"> Passphrase</label>
        <label><input v-model="form.method" type="radio" value="recovery" name="method"> Recovery Key</label>
      </fieldset>
      <label for="unlock-secret">{{ form.method === 'passphrase' ? 'Passphrase' : 'Recovery Key' }}</label>
      <input id="unlock-secret" v-model="form.secret" :type="form.method === 'passphrase' ? 'password' : 'text'"
        autocomplete="off" spellcheck="false" required>
      <button class="primary" :disabled="busy">Buka data offline</button>
    </form>

    <template v-if="vault.status === 'unlocked' && !recoveryShown">
      <p v-if="vault.expired" class="notice error" role="alert">
        Validasi online terakhir lebih dari 7 hari lalu atau jam perangkat mundur. Data tetap tersimpan, tetapi
        tidak dapat dibuka sampai divalidasi online.
      </p>
      <p class="intro">
        Data offline terbuka di tab ini.
        <span v-if="vault.verifiedAt">Validasi online terakhir {{ date.format(new Date(vault.verifiedAt)) }}.</span>
      </p>
      <div class="actions">
        <button v-if="online" type="button" class="secondary" :disabled="busy" @click="validateNow">Validasi sekarang</button>
        <button type="button" class="secondary" :disabled="busy" @click="vault.hardLock()">Kunci sekarang</button>
      </div>
      <template v-if="!vault.expired">
        <form @submit.prevent="resetPin">
          <h2>Ganti PIN</h2>
          <label for="new-pin">PIN baru</label>
          <input id="new-pin" v-model="form.newPin" inputmode="numeric" autocomplete="off" maxlength="6" pattern="\d{6}" required>
          <button class="secondary" :disabled="busy">Simpan PIN</button>
        </form>
        <form @submit.prevent="changePassphrase">
          <h2>Ganti passphrase</h2>
          <label for="current-passphrase">Passphrase saat ini</label>
          <input id="current-passphrase" v-model="form.current" type="password" autocomplete="off" required>
          <label for="new-passphrase">Passphrase baru</label>
          <input id="new-passphrase" v-model="form.newPassphrase" type="password" autocomplete="off" minlength="12" required>
          <button class="secondary" :disabled="busy">Ganti passphrase</button>
        </form>
        <div class="actions">
          <button type="button" class="secondary" :disabled="busy" @click="newRecovery">Buat Recovery Key baru</button>
        </div>
      </template>
    </template>

    <form v-if="['hard', 'unlocked', 'corrupt'].includes(vault.status) && !recoveryShown" class="danger" @submit.prevent="erase">
      <h2>Hapus data offline</h2>
      <p class="hint">Menghapus draft dan transaksi tertunda yang belum tersinkron di perangkat ini secara permanen.
        Recovery Key tidak dapat mengembalikannya.</p>
      <label for="erase-confirm">Ketik HAPUS untuk konfirmasi</label>
      <input id="erase-confirm" v-model="form.erase" autocomplete="off" required>
      <button class="secondary" :disabled="busy">Hapus permanen</button>
    </form>
  </section>
</template>
