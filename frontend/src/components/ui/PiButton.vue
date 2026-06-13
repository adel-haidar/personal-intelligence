<script setup lang="ts">
import PIIcon from './PIIcon.vue'

interface Props {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'cta'
  size?: 'default' | 'compact'
  block?: boolean
  loading?: boolean
  icon?: string
  iconRight?: string
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'primary',
  size: 'default',
  block: false,
  loading: false,
  disabled: false,
})

defineEmits<{ click: [e: MouseEvent] }>()

function cls(): string[] {
  const c = ['pi-btn', `pi-btn--${props.variant}`]
  if (props.size === 'compact') c.push('pi-btn--compact')
  if (props.block) c.push('pi-btn--block')
  return c
}
</script>

<template>
  <button :class="cls()" :disabled="disabled || loading" v-bind="$attrs">
    <span v-if="loading" class="pi-btn__spinner" aria-hidden="true" />
    <PIIcon v-if="!loading && icon" :name="icon" :size="16" />
    <slot v-if="!loading" />
    <PIIcon v-if="!loading && iconRight" :name="iconRight" :size="16" />
  </button>
</template>
