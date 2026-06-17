<script setup lang="ts">
/** Full-screen reading mode for a post — larger Lora body, pinned Like/Dislike. */
import { ref } from 'vue'
import type { Post } from '../../composables/useContent'
import SeededAvatar from './SeededAvatar.vue'
import TonePill from './TonePill.vue'
import ScoreText from './ScoreText.vue'
import FeedVoteButton from './FeedVoteButton.vue'
import { ShareButton } from '../ui'
import { seededThumb } from './seeded'
import { headline, readMinutes, age, firstUrl, linkHost } from './post-format'

const props = defineProps<{ post: Post; vote?: 'up' | 'down' | null }>()
const emit = defineEmits<{ (e: 'vote', like: boolean): void; (e: 'close'): void }>()

const v = ref<'up' | 'down' | null>(props.vote ?? null)
function doVote(like: boolean) {
  v.value = like ? 'up' : 'down'
  emit('vote', like)
}
const url = firstUrl(props.post.body)
const handle = props.post.creator_slug || props.post.creator_name.toLowerCase().replace(/\s+/g, '-')
</script>

<template>
  <div class="rd">
    <div class="rd__scroll">
      <div class="rd__inner">
        <button class="rd__back" @click="emit('close')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M15 18l-6-6 6-6"/></svg>
          Back to Pulse
        </button>
        <div class="rd__meta">
          <TonePill v-if="post.tone" :tone="post.tone" />
          <ScoreText :score="post.score" />
          <span class="rd__read t-mono">{{ readMinutes(post.body) }} min read</span>
        </div>
        <h1 class="rd__title">{{ headline(post.body) }}</h1>
        <div class="rd__by">
          <SeededAvatar :name="post.creator_name" :image="post.creator_avatar" :size="32" />
          <div>
            <div class="rd__name">{{ post.creator_name }}</div>
            <div class="rd__handle t-mono">@{{ handle }} · {{ age(post.created_at) }}</div>
          </div>
        </div>
        <p class="rd__body">{{ post.body }}</p>
        <div v-if="post.image_url" class="rd__img" :style="{ backgroundImage: `url(${post.image_url})` }" />
        <template v-if="url">
          <div class="rd__eyebrow t-mono">Sources</div>
          <a class="rd__src" :href="url" target="_blank" rel="noopener">
            <span class="rd__fav" :style="seededThumb(post.creator_name)" />
            <span class="rd__srctitle">{{ linkHost(url) }}</span>
          </a>
        </template>
      </div>
    </div>
    <div class="rd__bar">
      <FeedVoteButton label="Like" color="var(--success)" icon="up" :active="v === 'up'" @click="doVote(true)" />
      <FeedVoteButton label="Dislike" color="var(--danger)" icon="down" :active="v === 'down'" @click="doVote(false)" />
      <ShareButton kind="pulse_post" :ref-id="post.id" :text="`${post.creator_name} on Pulse`" />
    </div>
  </div>
</template>

<style scoped>
.rd { position: fixed; inset: 0; z-index: 90; background: var(--background-page); display: flex; flex-direction: column; animation: fade 0.15s ease; }
@keyframes fade { from { opacity: 0; } to { opacity: 1; } }
.rd__scroll { flex: 1; overflow-y: auto; }
.rd__inner { max-width: 680px; margin: 0 auto; padding: 32px 24px; }
.rd__back { display: inline-flex; align-items: center; gap: 6px; background: none; border: 0; color: var(--accent-primary); cursor: pointer; font-size: var(--text-sm); margin-bottom: 20px; }
.rd__meta { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.rd__read { font-size: var(--text-xs); color: var(--text-tertiary); }
.rd__title { font-family: var(--font-display); font-weight: 600; font-size: 22px; line-height: 1.3; color: var(--text-primary); }
.rd__by { display: flex; align-items: center; gap: 10px; margin: 16px 0; }
.rd__name { font-family: var(--font-display); font-weight: 500; font-size: var(--text-md); color: var(--text-primary); }
.rd__handle { font-size: var(--text-xs); color: var(--text-tertiary); }
.rd__body { font-family: var(--font-serif); font-size: 16px; line-height: 1.75; color: var(--text-primary); white-space: pre-wrap; }
.rd__img { aspect-ratio: 16/9; border-radius: var(--radius-sm); background-size: cover; background-position: center; margin-top: 16px; }
.rd__eyebrow { margin-top: 16px; font-size: var(--text-xs); color: var(--text-tertiary); }
.rd__src { display: flex; align-items: center; gap: 10px; margin-top: 8px; padding: 10px; border-radius: var(--radius-sm); background: var(--background-raised); border: 1px solid var(--border-medium); text-decoration: none; }
.rd__fav { width: 18px; height: 18px; border-radius: 4px; flex: 0 0 auto; }
.rd__srctitle { font-size: var(--text-sm); color: var(--accent-primary); }
.rd__bar { display: flex; gap: 10px; padding: 12px 24px; border-top: 1px solid var(--border-subtle); }
</style>
