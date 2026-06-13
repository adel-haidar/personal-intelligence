<script setup lang="ts">
import { provide } from 'vue'
import PIIcon from './PIIcon.vue'
import { TOAST_KEY, useToastState } from './useToast'

const { toasts, push } = useToastState()
provide(TOAST_KEY, push)
</script>

<template>
  <slot />
  <div class="pi-toast-host" aria-live="polite">
    <div
      v-for="t in toasts"
      :key="t.id"
      :class="`pi-toast pi-toast--${t.kind}`"
    >
      <span :class="`pi-toast__icon--${t.kind}`">
        <PIIcon
          :name="t.kind === 'success' ? 'check' : t.kind === 'error' ? 'close' : 'bell'"
          :size="16"
        />
      </span>
      <span class="pi-toast__msg">{{ t.msg }}</span>
    </div>
  </div>
</template>
