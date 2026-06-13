<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, RouterView } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import ToastProvider from './components/ui/ToastProvider.vue'
import { isAuthenticated, hasRefreshToken, refreshTokens } from './composables/useAuth'

const route = useRoute()
const isPublic = computed(() => !!route.meta.public)

onMounted(async () => {
  if (!isAuthenticated() && hasRefreshToken()) {
    try { await refreshTokens() } catch { /* router guard handles the redirect */ }
  }
})
</script>

<template>
  <ToastProvider>
    <!-- Public routes (login, register, about) render full-screen -->
    <RouterView v-if="isPublic" />

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
