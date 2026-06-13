<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, RouterView } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import ToastProvider from './components/ui/ToastProvider.vue'
import { isAuthenticated, hasRefreshToken, refreshTokens } from './composables/useAuth'

const route = useRoute()
// Render without the sidebar shell only on the full-bleed screens (/onboarding)
// and for visitors who aren't signed in (login, register, oauth callback, and the
// public /about page viewed logged-out). A signed-in user visiting a public page —
// e.g. "How it works" → /about from the sidebar — still gets the shell so they can
// navigate back. Re-evaluates on every route change (which accompanies auth changes).
const isBare = computed(() => !!route.meta.fullscreen || !isAuthenticated())

onMounted(async () => {
  if (!isAuthenticated() && hasRefreshToken()) {
    try { await refreshTokens() } catch { /* router guard handles the redirect */ }
  }
})
</script>

<template>
  <ToastProvider>
    <!-- Full-bleed screens + signed-out visitors render without the sidebar shell -->
    <RouterView v-if="isBare" />

    <!-- Authenticated shell: sidebar + scrollable content -->
    <div v-else class="pi-shell">
      <Sidebar />
      <main class="pi-main">
        <div class="pi-main__inner">
          <RouterView />
        </div>
      </main>
    </div>
  </ToastProvider>
</template>
