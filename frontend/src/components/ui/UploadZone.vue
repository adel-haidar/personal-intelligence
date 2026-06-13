<script setup lang="ts">
import { ref } from 'vue'
import PIIcon from './PIIcon.vue'

interface Props {
  title?: string
  hint?: string
  accept?: string
  compact?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: 'Drop a file or click to upload',
})

const emit = defineEmits<{ files: [files: File[]] }>()

type UploadState = 'idle' | 'drag' | 'success'
const state = ref<UploadState>('idle')
const inputRef = ref<HTMLInputElement | null>(null)

function cls(): string[] {
  const c = ['pi-upload']
  if (state.value === 'drag') c.push('pi-upload--drag')
  if (state.value === 'success') c.push('pi-upload--success')
  return c
}

function handle(files: FileList | null) {
  if (files && files.length) {
    state.value = 'success'
    emit('files', Array.from(files))
    setTimeout(() => { state.value = 'idle' }, 2200)
  }
}

function onDragOver(e: DragEvent) { e.preventDefault(); state.value = 'drag' }
function onDragLeave(e: DragEvent) { e.preventDefault(); state.value = 'idle' }
function onDrop(e: DragEvent) { e.preventDefault(); handle(e.dataTransfer?.files ?? null) }
function onClick() { inputRef.value?.click() }
function onKeydown(e: KeyboardEvent) { if (e.key === 'Enter' || e.key === ' ') inputRef.value?.click() }
</script>

<template>
  <div
    :class="cls()"
    role="button"
    tabindex="0"
    :style="compact ? { padding: 'var(--space-5)' } : undefined"
    @click="onClick"
    @keydown="onKeydown"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="inputRef"
      type="file"
      :accept="accept"
      hidden
      multiple
      @change="handle(($event.target as HTMLInputElement).files)"
    />
    <PIIcon :name="state === 'success' ? 'check' : 'upload'" :size="compact ? 20 : 24" />
    <span class="pi-upload__title">{{ state === 'success' ? 'File received' : title }}</span>
    <span v-if="hint && state !== 'success'" class="pi-upload__hint">{{ hint }}</span>
  </div>
</template>
