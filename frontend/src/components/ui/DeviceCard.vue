<script setup lang="ts">
import { ref } from 'vue'
import PIIcon from './PIIcon.vue'
import Badge from './Badge.vue'
import PiCard from './PiCard.vue'
import UploadZone from './UploadZone.vue'

interface Props {
  icon: string
  name: string
  connected?: boolean
  lastSync?: string
  instructions?: string[]
  acceptHint?: string
}

withDefaults(defineProps<Props>(), {
  connected: false,
  instructions: () => [],
})

const emit = defineEmits<{ files: [files: File[]] }>()

const open = ref(false)
</script>

<template>
  <PiCard class="pi-device">
    <div class="pi-device__head">
      <span class="pi-device__ic">
        <PIIcon :name="icon" :size="20" />
      </span>
      <div style="flex: 1; min-width: 0">
        <div class="pi-device__name">{{ name }}</div>
        <div class="pi-device__meta">
          {{ connected ? `Last update: ${lastSync ?? '—'}` : 'No data yet' }}
        </div>
      </div>
      <Badge v-if="connected" variant="success" icon="check">Synced</Badge>
      <Badge v-else variant="outlined">Not synced</Badge>
    </div>
    <button
      class="pi-btn pi-btn--ghost pi-btn--compact"
      style="align-self: flex-start"
      @click="open = !open"
    >
      <PIIcon :name="open ? 'chevronDown' : 'chevronRight'" :size="14" />
      {{ open ? 'Hide steps' : 'How to sync' }}
    </button>
    <div v-if="open" class="pi-device__instructions">
      <ol>
        <li v-for="(s, i) in instructions" :key="i">{{ s }}</li>
      </ol>
    </div>
    <UploadZone :compact="true" :title="`Upload ${name} export`" :hint="acceptHint" @files="emit('files', $event)" />
  </PiCard>
</template>
