<script setup lang="ts">
// Static brand mark — simplified resting brain pulse for sidebar header / logo.
// Mirrors BrandMark from pi-icons.jsx.
import type { CSSProperties } from 'vue'

interface Props {
  size?: number
}

const props = withDefaults(defineProps<Props>(), { size: 22 })

const k = props.size / 22

function dot(xPct: number, yPct: number, d: number, op: number): CSSProperties {
  return {
    position: 'absolute',
    left: xPct + '%',
    top: yPct + '%',
    width: d * k + 'px',
    height: d * k + 'px',
    borderRadius: '50%',
    background: 'var(--brain-amber)',
    transform: 'translate(-50%,-50%)',
    opacity: op,
  }
}

const dots = [
  dot(50, 50, 5, 0.95),
  dot(78, 32, 3.2, 0.9),
  dot(24, 30, 3.2, 0.7),
  dot(70, 74, 3.2, 0.8),
  dot(30, 76, 3.2, 0.55),
]
</script>

<template>
  <span
    class="pi-brandmark"
    aria-hidden="true"
    :style="{ position: 'relative', width: props.size + 'px', height: props.size + 'px', display: 'inline-block', flex: '0 0 auto' }"
  >
    <span v-for="(s, i) in dots" :key="i" :style="s" />
  </span>
</template>
