<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, RouterView } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import ToastProvider from './components/ui/ToastProvider.vue'
import AriaMiniPlayer from './components/aria/AriaMiniPlayer.vue'
import AriaNowPlaying from './components/aria/AriaNowPlaying.vue'
import SignalPlayerOverlay from './components/feed/SignalPlayerOverlay.vue'
import { isAuthenticated, hasRefreshToken, refreshTokens, requireAuth } from './composables/useAuth'
import { useAria } from './composables/useAria'
import { useSignalPlayer } from './composables/useSignalPlayer'
import { useI18n } from './i18n'
import { API_BASE } from './config/env'

const route = useRoute()
const { setLocale } = useI18n()
// App-level music state: the mini-player persists across navigation, so it lives
// here in the shell (above the router), never inside a page component.
const { track: ariaTrack } = useAria()
// SIGNAL playback is also app-level: the player persists across navigation and
// docks to a bottom mini-bar when collapsed. Reserve space for that bar too.
const { current: signalVideo, expanded: signalExpanded } = useSignalPlayer()
const signalMini = computed(() => !!signalVideo.value && !signalExpanded.value)

// Apply the account's saved language so the choice follows the user across
// devices (localStorage already gave an instant, flash-free default on load).
async function applyAccountLanguage() {
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
    if (!res.ok) return
    const { user } = await res.json()
    if (user?.language_preference) setLocale(user.language_preference)
  } catch { /* best-effort */ }
}
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
  if (isAuthenticated()) applyAccountLanguage()
})
</script>

<template>
  <ToastProvider>
    <!-- Full-bleed screens + signed-out visitors render without the sidebar shell -->
    <RouterView v-if="isBare" />

    <!-- Authenticated shell: sidebar + scrollable content -->
    <div v-else class="pi-shell">
      <Sidebar />
      <main class="pi-main" :class="{ 'pi-main--mini': ariaTrack || signalMini }">
        <div class="pi-main__inner">
          <RouterView />
        </div>
      </main>
      <!-- ARIA: persistent mini-player + full Now Playing overlay (app-level). -->
      <AriaMiniPlayer />
      <AriaNowPlaying />
      <!-- SIGNAL: persistent full-screen / docked mini video player (app-level). -->
      <SignalPlayerOverlay />
    </div>
  </ToastProvider>
</template>

<style scoped>
/* Reserve space so page content never hides behind the 64px mini-player. */
.pi-main--mini :deep(.pi-main__inner) { padding-bottom: 80px; }
</style>
