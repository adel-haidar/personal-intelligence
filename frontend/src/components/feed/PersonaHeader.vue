<script setup lang="ts">
/** Facebook-style profile header for a selected persona: a tinted cover band,
 * overlapping avatar, name, bio and post count. */
import { computed } from 'vue'
import type { Creator } from '../../composables/useContent'
import SeededAvatar from './SeededAvatar.vue'
import { seededColor } from './seeded'

const props = defineProps<{ creator: Creator; postCount: number }>()
const emit = defineEmits<{ (e: 'back'): void }>()

const cover = computed(() => {
  const c = seededColor(props.creator.name)
  return `linear-gradient(135deg, ${c} 0%, color-mix(in srgb, ${c} 55%, var(--background-base)) 100%)`
})
</script>

<template>
  <header class="ph">
    <div class="ph__cover" :style="{ background: cover }">
      <button class="ph__back" @click="emit('back')" aria-label="Back to all personas">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
        All personas
      </button>
    </div>
    <div class="ph__body">
      <div class="ph__avatar"><SeededAvatar :name="creator.name" :image="creator.avatar_url" :size="88" /></div>
      <div class="ph__info">
        <h2 class="ph__name">{{ creator.name }}</h2>
        <div class="ph__handle t-mono">@{{ creator.slug }} · {{ postCount }} {{ postCount === 1 ? 'post' : 'posts' }}</div>
        <p v-if="creator.bio" class="ph__bio">{{ creator.bio }}</p>
      </div>
    </div>
  </header>
</template>

<style scoped>
.ph { border: 1px solid var(--border-subtle); border-radius: var(--radius-md); overflow: hidden; background: var(--background-surface); margin-bottom: 14px; }
.ph__cover { height: 132px; position: relative; }
.ph__back {
  position: absolute; top: 12px; left: 12px; display: inline-flex; align-items: center; gap: 6px;
  height: 32px; padding: 0 12px; border: 0; border-radius: 999px; cursor: pointer;
  background: color-mix(in srgb, var(--background-base) 70%, transparent);
  color: var(--text-primary); font-size: var(--text-sm); backdrop-filter: blur(6px);
}
.ph__back:hover { background: var(--background-base); }
.ph__body { display: flex; align-items: flex-end; gap: 16px; padding: 0 20px 18px; }
.ph__avatar { margin-top: -44px; border: 4px solid var(--background-surface); border-radius: 999px; }
.ph__info { padding-bottom: 2px; min-width: 0; }
.ph__name { font-family: var(--font-display); font-weight: 600; font-size: 22px; color: var(--text-primary); margin: 0; }
.ph__handle { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 2px; }
.ph__bio { font-family: var(--font-serif); font-size: var(--text-base); color: var(--text-secondary); margin: 8px 0 0; line-height: 1.5; }
</style>
