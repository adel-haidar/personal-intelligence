<script setup lang="ts">
import PIIcon from './PIIcon.vue'

interface Props {
  icon?: string
  title?: string
  desc?: string
  serif?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  icon: 'spark',
  serif: false,
})
</script>

<template>
  <div class="pi-empty">
    <span v-if="icon" class="pi-empty__icon">
      <PIIcon :name="icon" :size="28" />
    </span>
    <div v-if="title" class="pi-empty__title">{{ title }}</div>
    <div
      v-if="desc"
      class="pi-empty__desc"
      :style="serif ? { fontFamily: 'var(--font-serif)' } : undefined"
    >{{ desc }}</div>
    <slot name="action" />
  </div>
</template>
