<script setup lang="ts">
interface Props {
  modelValue: string
  options: string[]
  label?: string
}

defineProps<Props>()
const emit = defineEmits<{ 'update:modelValue': [v: string] }>()
</script>

<template>
  <label class="pi-select">
    <span v-if="label" class="pi-select__label">{{ label }}</span>
    <select
      :value="modelValue"
      style="background: transparent; border: 0; color: var(--text-primary); font: inherit; cursor: pointer"
      @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    >
      <option v-for="o in options" :key="o" :value="o">{{ o }}</option>
    </select>
  </label>
</template>
