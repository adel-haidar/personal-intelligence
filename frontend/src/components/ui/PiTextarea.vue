<script setup lang="ts">
interface Props {
  modelValue?: string
  serif?: boolean
  placeholder?: string
  disabled?: boolean
  maxlength?: number
}

const props = withDefaults(defineProps<Props>(), {
  serif: false,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [v: string]
}>()
</script>

<template>
  <textarea
    :class="['pi-textarea', serif ? 'pi-textarea--serif' : '']"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :maxlength="maxlength"
    v-bind="$attrs"
    @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>
