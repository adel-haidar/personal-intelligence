<script setup lang="ts">
interface Props {
  value: number
}

const props = defineProps<Props>()

function band(): 'high' | 'mid' | 'low' {
  if (props.value > 0.65) return 'high'
  if (props.value >= 0.4) return 'mid'
  return 'low'
}
</script>

<template>
  <span :class="`pi-score pi-score--${band()}`">{{ value.toFixed(2) }}</span>
</template>
