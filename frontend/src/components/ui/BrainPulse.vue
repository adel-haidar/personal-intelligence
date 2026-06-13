<script setup lang="ts">
// Brain Pulse — 4 amber dots orbiting a center at different radii/speeds.
// Mirrors BrainPulse from pi-icons.jsx.
// Always aria-hidden. Respects prefers-reduced-motion via CSS in tokens.css.

interface Props {
  size?: number
  slow?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  size: 16,
  slow: false,
})

const k = props.size / 16
const r = [6 * k, 9 * k, 7 * k, 11 * k]
const dot = Math.max(2, Math.round(2.4 * k))

const styleVars: Record<string, string | number> = {
  width: props.size + 'px',
  height: props.size + 'px',
  '--bp-dot': dot + 'px',
  '--r1': r[0] + 'px',
  '--r2': r[1] + 'px',
  '--r3': r[2] + 'px',
  '--r4': r[3] + 'px',
}

function orbitDuration(n: number): string | undefined {
  if (!props.slow) return undefined
  return (24 + n * 4) + 's'
}
</script>

<template>
  <span class="brain-pulse" :style="styleVars" aria-hidden="true">
    <span class="bp-center" />
    <span
      v-for="n in [1, 2, 3, 4]"
      :key="n"
      :class="`bp-orbit bp-o${n}`"
      :style="orbitDuration(n) ? { animationDuration: orbitDuration(n) } : undefined"
    >
      <span class="bp-dot" />
    </span>
  </span>
</template>
