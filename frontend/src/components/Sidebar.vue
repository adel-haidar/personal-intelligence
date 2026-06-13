<script setup lang="ts">
import { RouterLink } from 'vue-router'
import BrandMark from './ui/BrandMark.vue'
import BrainPulse from './ui/BrainPulse.vue'
import PIIcon from './ui/PIIcon.vue'
import Avatar from './ui/Avatar.vue'
import ModeToggle from './ui/ModeToggle.vue'

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
]

const NAV_SYS: NavItem[] = [
  { label: 'Settings',     to: '/settings',  icon: 'settings' },
  { label: 'How it works', to: '/about',     icon: 'help' },
]

const NAV_TOOLS: NavItem[] = [
  { label: 'Email',        to: '/email',      icon: 'email' },
  { label: 'Bank adviser', to: '/bank',       icon: 'bank' },
  { label: 'Job hunt',     to: '/job',        icon: 'job' },
  { label: 'Hermes',       to: '/hermes',     icon: 'hermes' },
  { label: 'Files',        to: '/repository', icon: 'repository' },
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
          <!-- Brain item gets animated BrainPulse instead of a static icon -->
          <BrainPulse v-if="item.brain" :size="18" />
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

      <!-- Divider + legacy tools -->
      <div class="pi-nav__sep" />
      <span class="pi-nav__section-label">Tools</span>

      <RouterLink
        v-for="item in NAV_TOOLS"
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
