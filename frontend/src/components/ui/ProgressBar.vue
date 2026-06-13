<script setup lang="ts">
interface Props {
  value: number
  label?: string
  showPct?: boolean
  variant?: 'amber' | 'success' | 'danger'
  thin?: boolean
  note?: string
}

const props = withDefaults(defineProps<Props>(), {
  showPct: true,
  thin: false,
})

function cls(): string[] {
  const c = ['pi-progress']
  if (props.variant) c.push(`pi-progress--${props.variant}`)
  if (props.thin) c.push('pi-progress--thin')
  return c
}
</script>

<template>
  <div :class="cls()">
    <div v-if="label || showPct" class="pi-progress__head">
      <span v-if="label" class="pi-progress__label">{{ label }}</span>
      <span v-if="showPct" class="pi-progress__pct">{{ Math.round(value) }}%</span>
    </div>
    <div class="pi-progress__track">
      <div class="pi-progress__fill" :style="{ width: `${value}%` }" />
    </div>
    <span v-if="note" class="pi-progress__pct" style="margin-top: 2px">{{ note }}</span>
  </div>
</template>
