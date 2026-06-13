<script setup lang="ts">
import PageHead from '../components/ui/PageHead.vue'
import PiCard from '../components/ui/PiCard.vue'
import EmptyState from '../components/ui/EmptyState.vue'
</script>

<template>
  <div style="max-width: var(--content-reading); margin: 0 auto">
    <PageHead
      title="How it works"
      desc="Private Internet runs entirely on your own server. Your data never leaves your infrastructure."
    />
    <PiCard>
      <EmptyState
        icon="shield"
        title="Your server. Your data."
        desc="Private Internet is a self-hosted intelligence platform. Everything you see here is processed on your own machine — no third-party cloud storage, no data sharing, no analytics."
        :serif="true"
      />
    </PiCard>
  </div>
</template>
