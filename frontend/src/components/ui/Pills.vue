<script setup lang="ts">
interface Option {
  value: string | boolean | number
  label: string
}

interface Props {
  options: (string | Option)[]
  modelValue: string | boolean | number
}

defineProps<Props>()
const emit = defineEmits<{ 'update:modelValue': [v: string | boolean | number] }>()

function val(o: string | Option) {
  return typeof o === 'string' ? o : o.value
}
function label(o: string | Option) {
  return typeof o === 'string' ? o : o.label
}
</script>

<template>
  <div class="pi-pills">
    <button
      v-for="o in options"
      :key="String(val(o))"
      :class="['pi-pill', modelValue === val(o) ? 'pi-pill--active' : '']"
      @click="emit('update:modelValue', val(o))"
    >
      {{ label(o) }}
    </button>
  </div>
</template>
