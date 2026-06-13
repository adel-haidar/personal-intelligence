<script setup lang="ts">
import PIIcon from './PIIcon.vue'

interface Props {
  modelValue?: string
  icon?: string
  error?: string
  placeholder?: string
  type?: string
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  type: 'text',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [v: string]
}>()
</script>

<template>
  <div :class="['pi-input-wrap', icon ? 'has-icon' : '']">
    <span v-if="icon" class="pi-input__icon">
      <PIIcon :name="icon" :size="16" />
    </span>
    <input
      :class="['pi-input', error ? 'pi-input--error' : '']"
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      v-bind="$attrs"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
  </div>
</template>
