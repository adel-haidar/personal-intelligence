<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'
import BrandMark from './ui/BrandMark.vue'
import BrainPulse from './ui/BrainPulse.vue'
import PIIcon from './ui/PIIcon.vue'
import Avatar from './ui/Avatar.vue'
import ModeToggle from './ui/ModeToggle.vue'
import { useToast } from './ui/useToast'
import { useBrainOrganiser } from '../composables/useBrainOrganiser'

// Always-visible Brain Organiser signal: the sidebar is mounted for the whole
// authenticated session, so it owns the single status poller and fires the
// result toast on completion/failure (it lives inside the ToastProvider).
const toast = useToast()
const { running: organiserRunning, ensurePolling, onTransition } = useBrainOrganiser()
let offTransition: (() => void) | null = null

onMounted(() => {
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
  label: string
  to: string
  icon: string
  brain?: boolean
}

const NAV_MAIN: NavItem[] = [
  { label: 'Dashboard',    to: '/overview',  icon: 'dashboard' },
  { label: 'Your Brain',   to: '/memory',    icon: 'brain',    brain: true },
  { label: 'Signal',       to: '/signal',    icon: 'signal' },
  { label: 'Pulse',        to: '/pulse',     icon: 'pulse' },
  { label: 'Health',       to: '/health',    icon: 'health' },
  { label: 'Finances',     to: '/finances',  icon: 'finances' },
  // Email assistant deactivated for the first release — re-add when EMAIL_ENABLED is on.
  { label: 'Job hunt',     to: '/job',       icon: 'job' },
]

const NAV_SYS: NavItem[] = [
  { label: 'Settings',     to: '/settings',  icon: 'settings' },
  { label: 'How it works', to: '/about',     icon: 'help' },
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
            title="Your brain is being organised…"
            aria-label="Your brain is being organised"
            style="font-size: 16px; line-height: 1; width: 18px; text-align: center; flex: 0 0 auto;"
          >💤</span>
          <BrainPulse v-else-if="item.brain" :size="18" />
          <PIIcon v-else :name="item.icon" :size="18" />

          <span class="pi-nav__label">
            <template v-if="item.brain && memoryCount === 0">
              <span style="color: var(--text-tertiary)">
                Your Brain
                <span class="pi-nav__hint">&nbsp;· Start here →</span>
              </span>
            </template>
            <template v-else>{{ item.label }}</template>
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
          <span class="pi-nav__label">{{ item.label }}</span>
        </button>
      </RouterLink>
    </nav>

    <!-- User footer -->
    <div class="pi-sidebar__user">
      <Avatar :name="userName" :size="32" />
      <div style="min-width: 0; flex: 1">
        <div class="pi-sidebar__user-name">{{ userName }}</div>
        <div class="pi-sidebar__user-meta">{{ userPlan }}</div>
      </div>
      <div style="margin-left: auto; flex: 0 0 auto">
        <ModeToggle :with-label="false" />
      </div>
    </div>
  </aside>
</template>
