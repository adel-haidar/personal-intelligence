<script setup lang="ts">
import PageHead from '../components/ui/PageHead.vue'
import PiCard from '../components/ui/PiCard.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PiButton from '../components/ui/PiButton.vue'
</script>

<template>
  <div style="max-width: var(--content-reading); margin: 0 auto">
    <PageHead
      title="Finances"
      desc="Private financial analysis, read from documents you upload. Nothing is shared."
    />
    <PiCard>
      <EmptyState
        icon="finances"
        title="No financial data yet"
        desc="Upload a bank statement or invoice and your brain will summarise trends here — entirely on your server."
      >
        <template #action>
          <PiButton variant="secondary" icon="upload">Upload a statement</PiButton>
        </template>
      </EmptyState>
    </PiCard>
  </div>
</template>
