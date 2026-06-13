<script setup lang="ts">
type Tone = 'critical' | 'satirical' | 'supportive' | 'informative'

interface Props {
  tone: Tone
}

defineProps<Props>()

const TONE_LABEL: Record<Tone, string> = {
  critical: 'Critical',
  satirical: 'Satirical',
  supportive: 'Supportive',
  informative: 'Informative',
}
</script>

<template>
  <span :class="`pi-tone pi-tone--${tone}`">
    <span class="pi-tone__dot" />
    {{ TONE_LABEL[tone] ?? tone }}
  </span>
</template>
