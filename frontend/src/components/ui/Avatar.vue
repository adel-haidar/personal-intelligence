<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  name?: string
  color?: string
  size?: number
  src?: string
}

const props = withDefaults(defineProps<Props>(), {
  name: '?',
  size: 36,
})

const initials = computed(() => {
  return props.name
    .split(/\s+/)
    .map(w => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
})

const style = computed(() => {
  const fs = Math.round(props.size * 0.4)
  const s: Record<string, string | number> = {
    width: props.size + 'px',
    height: props.size + 'px',
    fontSize: fs + 'px',
  }
  if (props.src) {
    s.backgroundImage = `url(${props.src})`
  } else {
    s.background = props.color ?? 'var(--accent-primary)'
  }
  return s
})
</script>

<template>
  <span class="pi-avatar" :style="style">
    <template v-if="!src">{{ initials }}</template>
  </span>
</template>
