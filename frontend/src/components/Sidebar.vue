<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import BrandMark from './ui/BrandMark.vue'
import BrainPulse from './ui/BrainPulse.vue'
import PIIcon from './ui/PIIcon.vue'
import Avatar from './ui/Avatar.vue'
import ModeToggle from './ui/ModeToggle.vue'
import IconButton from './ui/IconButton.vue'
import { useToast } from './ui/useToast'
import { useBrainOrganiser } from '../composables/useBrainOrganiser'
import { logout, requireAuth } from '../composables/useAuth'
import { API_BASE } from '../config/env'
import { useI18n } from '../i18n'

const { t } = useI18n()

// The signed-in user (fetched, not hardcoded).
const meName = ref('')
const meMeta = ref('')
const meAvatar = ref('')

async function loadUser() {
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
    if (!res.ok) return
    const { user } = await res.json()
    meName.value = user.display_name || user.email || ''
    meMeta.value = user.email || ''
    meAvatar.value = user.avatar_url || ''
  } catch { /* not signed in / offline — keep blank */ }
}

// Hard navigation so all in-memory state (billing/organiser caches, etc.) is
// wiped — a clean slate for switching or creating a fresh account.
function onSignOut() {
  logout()
  window.location.assign('/login')
}

// Always-visible Brain Organiser signal: the sidebar is mounted for the whole
// authenticated session, so it owns the single status poller and fires the
// result toast on completion/failure (it lives inside the ToastProvider).
const toast = useToast()
const { running: organiserRunning, ensurePolling, onTransition } = useBrainOrganiser()
let offTransition: (() => void) | null = null

onMounted(() => {
  loadUser()
  ensurePolling()
  offTransition = onTransition((to, s) => {
    if (to === 'completed' && s.last_run) {
      toast(
        `💤 Brain organised — ${s.last_run.duplicates_removed} duplicates removed, ${s.last_run.clusters_merged} memories merged.`,
        'success',
      )
    } else if (to === 'failed') {
      toast('Brain organiser encountered an error. Your memories are unchanged.', 'error')
    }
  })
})
onUnmounted(() => { offTransition?.() })

// Props — wiring memory count will come in a later increment.
interface Props {
  memoryCount?: number
  userName?: string
  userPlan?: string
}

const props = withDefaults(defineProps<Props>(), {
  memoryCount: 0,
  userName: 'Adel Haidar',
  userPlan: 'Self-hosted · Owner',
})

interface NavItem {
  key: string
  to: string
  icon: string
  brain?: boolean
}

const NAV_MAIN: NavItem[] = [
  { key: 'dashboard', to: '/overview',  icon: 'dashboard' },
  { key: 'brain',     to: '/memory',    icon: 'brain',    brain: true },
  { key: 'signal',    to: '/signal',    icon: 'signal' },
  { key: 'pulse',     to: '/pulse',     icon: 'pulse' },
  { key: 'health',    to: '/health',    icon: 'health' },
  { key: 'finances',  to: '/finances',  icon: 'finances' },
  // Email assistant deactivated for the first release — re-add when EMAIL_ENABLED is on.
  { key: 'jobs',      to: '/job',       icon: 'job' },
]

const NAV_SYS: NavItem[] = [
  { key: 'settings',   to: '/settings',  icon: 'settings' },
  { key: 'howItWorks', to: '/about',     icon: 'help' },
]
</script>

<template>
  <aside class="pi-sidebar">
    <!-- Brand -->
    <div class="pi-sidebar__brand">
      <BrandMark :size="22" />
      <span class="pi-sidebar__brand-name">Private Internet</span>
    </div>

    <!-- Primary nav -->
    <nav class="pi-nav">
      <RouterLink
        v-for="item in NAV_MAIN"
        :key="item.to"
        :to="item.to"
        custom
        v-slot="{ isActive, navigate }"
      >
        <button
          :class="['pi-nav__item', item.brain ? 'pi-nav__item--brain' : '', isActive ? 'pi-nav__item--active' : '']"
          @click="navigate"
        >
          <!-- Brain item: animated BrainPulse normally; a static 💤 while the
               Brain Organiser is running ("your brain is sleeping"). -->
          <span
            v-if="item.brain && organiserRunning"
            :title="t('sidebar.organising')"
            :aria-label="t('sidebar.organising')"
            style="font-size: 16px; line-height: 1; width: 18px; text-align: center; flex: 0 0 auto;"
          >💤</span>
          <BrainPulse v-else-if="item.brain" :size="18" />
          <PIIcon v-else :name="item.icon" :size="18" />

          <span class="pi-nav__label">
            <template v-if="item.brain && memoryCount === 0">
              <span style="color: var(--text-tertiary)">
                {{ t('nav.brain') }}
                <span class="pi-nav__hint">&nbsp;· {{ t('sidebar.startHere') }}</span>
              </span>
            </template>
            <template v-else>{{ t('nav.' + item.key) }}</template>
          </span>
        </button>
      </RouterLink>

      <!-- Divider + system nav -->
      <div class="pi-nav__sep" />

      <RouterLink
        v-for="item in NAV_SYS"
        :key="item.to"
        :to="item.to"
        custom
        v-slot="{ isActive, navigate }"
      >
        <button
          :class="['pi-nav__item', isActive ? 'pi-nav__item--active' : '']"
          @click="navigate"
        >
          <PIIcon :name="item.icon" :size="18" />
          <span class="pi-nav__label">{{ t('nav.' + item.key) }}</span>
        </button>
      </RouterLink>
    </nav>

    <!-- User footer -->
    <div class="pi-sidebar__user">
      <Avatar :name="meName || userName" :src="meAvatar || undefined" :size="32" />
      <div style="min-width: 0; flex: 1">
        <div class="pi-sidebar__user-name">{{ meName || userName }}</div>
        <div class="pi-sidebar__user-meta">{{ meMeta || userPlan }}</div>
      </div>
      <div style="margin-left: auto; flex: 0 0 auto; display: flex; align-items: center; gap: var(--space-1);">
        <ModeToggle :with-label="false" />
        <IconButton icon="logout" :label="t('nav.signOut')" @click="onSignOut" />
      </div>
    </div>
  </aside>
</template>
