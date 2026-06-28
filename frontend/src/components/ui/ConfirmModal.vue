<script setup lang="ts">
import { ref } from 'vue'
import PiButton from './PiButton.vue'
import { useFocusTrap } from '../../composables/useFocusTrap'

interface Props {
  open: boolean
  title: string
  body?: string
  confirmLabel?: string
  danger?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  confirmLabel: 'Confirm',
  danger: false,
})

const emit = defineEmits<{ close: []; confirm: [] }>()

const dialogEl = ref<HTMLElement | null>(null)
useFocusTrap(dialogEl, () => props.open, { onEscape: () => emit('close') })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="pi-modal-overlay"
      @click="emit('close')"
    >
      <div
        ref="dialogEl"
        class="pi-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pi-modal-title"
        :aria-describedby="body ? 'pi-modal-body' : undefined"
        @click.stop
      >
        <h2 id="pi-modal-title" class="pi-modal__title">{{ title }}</h2>
        <div v-if="body" id="pi-modal-body" class="pi-modal__body">{{ body }}</div>
        <div class="pi-modal__actions">
          <PiButton variant="secondary" @click="emit('close')">Cancel</PiButton>
          <PiButton :variant="danger ? 'danger' : 'primary'" @click="emit('confirm')">
            {{ confirmLabel }}
          </PiButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>
