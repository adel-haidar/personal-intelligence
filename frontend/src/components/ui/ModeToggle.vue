<script setup lang="ts">
import PIIcon from './PIIcon.vue'
import { useTheme } from '../../composables/useTheme'

interface Props {
  withLabel?: boolean
}

const props = withDefaults(defineProps<Props>(), { withLabel: true })

const { theme, toggleTheme } = useTheme()
</script>

<template>
  <button
    class="pi-mode-toggle"
    :aria-label="`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`"
    @click="toggleTheme"
  >
    <PIIcon :name="theme === 'dark' ? 'moon' : 'sun'" :size="16" />
    <span v-if="withLabel" class="pi-mode-toggle__label">
      {{ theme === 'dark' ? 'Dark' : 'Light' }}
    </span>
  </button>
</template>
