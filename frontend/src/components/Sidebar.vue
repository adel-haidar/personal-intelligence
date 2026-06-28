<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
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
import { useBilling } from '../composables/useBilling'

const { t } = useI18n()
const router = useRouter()
const { status: billingStatus, meetsPlan } = useBilling()

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
  requiresPlan?: 'pro' | 'max'
}

const NAV_MAIN: NavItem[] = [
  { key: 'dashboard', to: '/overview',  icon: 'dashboard' },
  { key: 'brain',     to: '/memory',    icon: 'brain',    brain: true },
  { key: 'signal',    to: '/signal',    icon: 'signal',   requiresPlan: 'pro' },
  { key: 'stories',   to: '/stories',   icon: 'stories',  requiresPlan: 'max' },
  { key: 'aria',      to: '/aria',      icon: 'aria',     requiresPlan: 'pro' },
  { key: 'pulse',     to: '/pulse',     icon: 'pulse' },
  { key: 'health',    to: '/health',    icon: 'health' },
  { key: 'finances',  to: '/finances',  icon: 'finances' },
  // Email assistant deactivated for the first release — re-add when EMAIL_ENABLED is on.
  { key: 'jobs',      to: '/job',       icon: 'job' },
]

/** True when the item is gated and the user's plan doesn't meet the requirement. */
function isLocked(item: NavItem): boolean {
  if (!item.requiresPlan) return false
  if (!billingStatus.value?.billing_enabled) return false
  return !meetsPlan(item.requiresPlan)
}

// Nav items are real <a> links (open-in-new-tab, middle-click, right-click all
// work). For locked tiers we intercept the activation and route to /subscribe
// instead; `navigate` already no-ops on modifier-clicks so ⌘/ctrl-click on an
// unlocked item still opens a new tab via the href.
function handleNavClick(item: NavItem, navigate: (e: MouseEvent) => void, e: MouseEvent) {
  if (isLocked(item)) {
    e.preventDefault()
    router.push(`/subscribe?feature=${encodeURIComponent(item.to)}`)
    return
  }
  navigate(e)
}

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
    <nav class="pi-nav" :aria-label="t('a11y.primaryNav')">
      <RouterLink
        v-for="item in NAV_MAIN"
        :key="item.to"
        :to="item.to"
        custom
        v-slot="{ href, isActive, navigate }"
      >
        <a
          :href="href"
          :class="['pi-nav__item', item.brain ? 'pi-nav__item--brain' : '', isActive ? 'pi-nav__item--active' : '', isLocked(item) ? 'pi-nav__item--locked' : '']"
          :aria-current="isActive ? 'page' : undefined"
          :aria-label="isLocked(item) ? t('a11y.lockedFeature', { name: t('nav.' + item.key) }) : t('nav.' + item.key)"
          @click="handleNavClick(item, navigate, $event)"
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

          <!-- Tier lock badge (billing enabled + plan insufficient) -->
          <span
            v-if="isLocked(item)"
            class="pi-nav__lock-badge"
            aria-hidden="true"
          >{{ item.requiresPlan?.toUpperCase() }}</span>
        </a>
      </RouterLink>

      <!-- Divider + system nav -->
      <div class="pi-nav__sep" />

      <RouterLink
        v-for="item in NAV_SYS"
        :key="item.to"
        :to="item.to"
        custom
        v-slot="{ href, isActive, navigate }"
      >
        <a
          :href="href"
          :class="['pi-nav__item', isActive ? 'pi-nav__item--active' : '']"
          :aria-current="isActive ? 'page' : undefined"
          :aria-label="t('nav.' + item.key)"
          @click="navigate"
        >
          <PIIcon :name="item.icon" :size="18" />
          <span class="pi-nav__label">{{ t('nav.' + item.key) }}</span>
        </a>
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
