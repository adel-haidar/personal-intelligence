<script setup lang="ts">
import PIIcon from './PIIcon.vue'

interface Props {
  variant?: 'filled' | 'outlined' | 'success' | 'warning' | 'danger' | 'amber'
  icon?: string
}

const props = withDefaults(defineProps<Props>(), { variant: 'filled' })
</script>

<template>
  <span :class="`pi-badge pi-badge--${variant}`">
    <PIIcon v-if="icon" :name="icon" :size="12" />
    <slot />
  </span>
</template>
