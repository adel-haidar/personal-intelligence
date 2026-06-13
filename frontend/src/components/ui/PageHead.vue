<script setup lang="ts">
interface Props {
  title: string
  desc?: string
}

defineProps<Props>()
</script>

<template>
  <div class="pi-page-head">
    <h1 class="pi-page-head__title">{{ title }}</h1>
    <p v-if="desc" class="pi-page-head__desc">{{ desc }}</p>
    <hr class="pi-rule" />
  </div>
</template>
