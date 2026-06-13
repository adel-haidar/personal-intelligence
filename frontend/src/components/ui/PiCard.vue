<script setup lang="ts">
interface Props {
  hover?: boolean
  selected?: boolean
  flush?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  hover: false,
  selected: false,
  flush: false,
})

function cls(): string[] {
  const c = ['pi-card']
  if (props.hover) c.push('pi-card--hover')
  if (props.selected) c.push('pi-card--selected')
  if (props.flush) c.push('pi-card--flush')
  return c
}
</script>

<template>
  <div :class="cls()" v-bind="$attrs">
    <slot />
  </div>
</template>
