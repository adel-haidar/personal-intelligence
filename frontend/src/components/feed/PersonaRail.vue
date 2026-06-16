<script setup lang="ts">
/** Facebook-style "people" rail: an All entry plus every PULSE persona. Click a
 * persona to scope the feed to their posts. Renders as a left sidebar on wide
 * screens and a horizontal avatar strip on mobile (driven by parent CSS). */
import type { Creator } from '../../composables/useContent'
import SeededAvatar from './SeededAvatar.vue'

defineProps<{ creators: Creator[]; selected: string | null; loading?: boolean }>()
const emit = defineEmits<{ (e: 'select', id: string | null): void }>()
</script>

<template>
  <nav class="prail" aria-label="Personas">
    <div class="prail__head">People</div>

    <button class="prail__item" :class="{ on: selected === null }" @click="emit('select', null)">
      <span class="prail__all">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      </span>
      <span class="prail__meta">
        <span class="prail__name">All personas</span>
        <span class="prail__bio">Everyone in your feed</span>
      </span>
    </button>

    <button
      v-for="c in creators"
      :key="c.id"
      class="prail__item"
      :class="{ on: selected === c.id }"
      @click="emit('select', c.id)"
    >
      <SeededAvatar :name="c.name" :image="c.avatar_url" :size="40" />
      <span class="prail__meta">
        <span class="prail__name">{{ c.name }}</span>
        <span class="prail__bio">{{ c.bio || '@' + c.slug }}</span>
      </span>
    </button>

    <div v-if="loading && creators.length === 0" class="prail__hint">Loading personas…</div>
  </nav>
</template>

<style scoped>
.prail { display: flex; flex-direction: column; gap: 4px; }
.prail__head { font-family: var(--font-display); font-weight: 600; font-size: var(--text-sm); color: var(--text-secondary); padding: 4px 8px 8px; }
.prail__item {
  display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
  padding: 8px; border: 0; background: transparent; border-radius: var(--radius-md);
  cursor: pointer; color: var(--text-primary); transition: background 0.12s ease;
}
.prail__item:hover { background: var(--background-raised); }
.prail__item.on { background: color-mix(in srgb, var(--accent-primary) 14%, transparent); }
.prail__all {
  width: 40px; height: 40px; flex: 0 0 auto; display: grid; place-items: center;
  border-radius: 999px; background: var(--background-raised); color: var(--text-secondary);
}
.prail__meta { min-width: 0; display: flex; flex-direction: column; }
.prail__name { font-family: var(--font-display); font-weight: 500; font-size: var(--text-md); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.prail__item.on .prail__name { color: var(--accent-primary); }
.prail__bio { font-size: var(--text-xs); color: var(--text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.prail__hint { padding: 8px; font-size: var(--text-xs); color: var(--text-tertiary); }

/* Mobile: horizontal avatar strip. Parent adds .prail--strip. */
.prail--strip { flex-direction: row; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.prail--strip .prail__head { display: none; }
.prail--strip .prail__item { flex-direction: column; gap: 6px; width: 72px; flex: 0 0 auto; text-align: center; }
.prail--strip .prail__meta { align-items: center; max-width: 100%; }
.prail--strip .prail__bio { display: none; }
.prail--strip .prail__name { font-size: var(--text-xs); max-width: 64px; }
</style>
