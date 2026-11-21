<script setup lang="ts">
import { useAuth } from './session'
const auth = useAuth()
</script>

<template>
  <a class="skip-link" href="#content">Langsung ke konten</a>
  <header class="topbar">
    <RouterLink to="/" class="wordmark"><span aria-hidden="true">D</span>Duit Log</RouterLink>
    <nav v-if="auth.profile" aria-label="Akun">
      <RouterLink :to="auth.profile.emailVerified ? '/account' : '/verify-email'">Akun</RouterLink>
      <RouterLink to="/sessions">Perangkat</RouterLink>
    </nav>
  </header>
  <main id="content" tabindex="-1">
    <p v-if="auth.loadError" class="notice error" role="alert">{{ auth.loadError }}</p>
    <RouterView v-slot="{ Component, route }">
      <component :is="Component" :key="route.name" />
    </RouterView>
  </main>
</template>
