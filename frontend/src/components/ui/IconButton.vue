<script setup lang="ts">
import PIIcon from './PIIcon.vue'

interface Props {
  icon: string
  size?: number
  label: string
}

const props = withDefaults(defineProps<Props>(), { size: 18 })
</script>

<template>
  <button class="pi-btn pi-btn--icon" :aria-label="label" :title="label" v-bind="$attrs">
    <PIIcon :name="icon" :size="size" />
  </button>
</template>
