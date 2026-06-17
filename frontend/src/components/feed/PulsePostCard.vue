<script setup lang="ts">
/** A PULSE feed post in one of three editorial formats (A image / B text-only /
 * C external source), chosen by content. */
import { computed } from 'vue'
import type { Post } from '../../composables/useContent'
import SeededAvatar from './SeededAvatar.vue'
import TonePill from './TonePill.vue'
import ScoreText from './ScoreText.vue'
import FeedVoteButton from './FeedVoteButton.vue'
import { ShareButton } from '../ui'
import { seededThumb } from './seeded'
import { headline, readMinutes, postFormat, age, toneTint, firstUrl, linkHost } from './post-format'

const props = withDefaults(
  defineProps<{
    post: Post
    vote?: 'up' | 'down' | null
    compact?: boolean
    showMediaUpgradeHint?: boolean
  }>(),
  { vote: null, compact: false, showMediaUpgradeHint: false },
)
const emit = defineEmits<{
  (e: 'vote', like: boolean): void
  (e: 'open'): void
  (e: 'upgrade'): void
}>()

const fmt = computed(() => postFormat(props.post))
const handle = computed(() => props.post.creator_slug || props.post.creator_name.toLowerCase().replace(/\s+/g, '-'))
const url = computed(() => firstUrl(props.post.body))
</script>

<template>
  <!-- Format B: text-only, tone-tinted, body is the hero -->
  <div v-if="fmt === 'B'" class="pc pc--b" :style="{ background: toneTint(post.tone) }">
    <div class="pc__row">
      <TonePill v-if="post.tone" :tone="post.tone" />
      <span class="pc__spacer" />
      <ScoreText :score="post.score" />
    </div>
    <p class="pc__serif pc__body" :class="compact ? 'clamp-4' : 'clamp-2'" @click="emit('open')">{{ post.body }}</p>
    <div class="pc__brow">
      <SeededAvatar :name="post.creator_name" :image="post.creator_avatar" :size="24" />
      <span class="pc__age">{{ post.creator_name.split(' ')[0] }} · {{ age(post.created_at) }}</span>
      <button class="pc__icon" :class="{ on: vote === 'up' }" style="--c: var(--success)" @click.stop="emit('vote', true)" aria-label="Like">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
      </button>
      <button class="pc__icon" :class="{ on: vote === 'down' }" style="--c: var(--danger)" @click.stop="emit('vote', false)" aria-label="Dislike">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>
      </button>
      <ShareButton variant="icon" kind="pulse_post" :ref-id="post.id" :text="`${post.creator_name} on Pulse`" @click.stop />
    </div>
  </div>

  <!-- Formats A & C: card with header + headline -->
  <div v-else class="pc pc--card">
    <div class="pc__header">
      <SeededAvatar :name="post.creator_name" :image="post.creator_avatar" :size="36" />
      <div class="pc__who">
        <div class="pc__name">{{ post.creator_name }}</div>
        <div class="pc__handle t-mono">@{{ handle }} · {{ age(post.created_at) }}</div>
      </div>
      <TonePill v-if="post.tone" :tone="post.tone" />
      <ScoreText :score="post.score" />
    </div>

    <h3 class="pc__topic" @click="emit('open')">{{ headline(post.body) }}</h3>

    <div
      v-if="fmt === 'A' && post.image_url"
      class="pc__img"
      :style="{ backgroundImage: `url(${post.image_url})` }"
      @click="emit('open')"
    />
    <div
      v-else-if="fmt === 'A' && showMediaUpgradeHint"
      class="pc__img-gate"
      role="button"
      tabindex="0"
      @click="emit('upgrade')"
      @keydown.enter="emit('upgrade')"
    >
      <span class="pc__img-gate__text">Upgrade to Pro for images &amp; video</span>
    </div>
    <div
      v-else-if="fmt === 'A'"
      class="pc__img"
      :style="seededThumb(post.creator_name)"
      @click="emit('open')"
    />

    <p class="pc__serif pc__body clamp-3" @click="emit('open')">{{ post.body }}</p>

    <a v-if="fmt === 'C' && url" class="pc__src" :href="url" target="_blank" rel="noopener">
      <span class="pc__fav" :style="{ background: 'var(--accent-primary)' }" />
      <span class="pc__srcmeta">
        <span class="pc__srchost t-mono">{{ linkHost(url) }}</span>
        <span class="pc__srctitle">{{ headline(post.body) }}</span>
      </span>
    </a>

    <button v-if="fmt === 'A'" class="pc__more" @click="emit('open')">Show more</button>

    <div class="pc__actions">
      <FeedVoteButton label="Like" color="var(--success)" icon="up" :active="vote === 'up'" @click="emit('vote', true)" />
      <FeedVoteButton label="Dislike" color="var(--danger)" icon="down" :active="vote === 'down'" @click="emit('vote', false)" />
      <FeedVoteButton :label="fmt === 'C' ? 'Open source' : 'Open'" color="var(--accent-primary)" icon="open" @click="emit('open')" />
      <ShareButton kind="pulse_post" :ref-id="post.id" :text="`${post.creator_name} on Pulse`" @click.stop />
      <span class="pc__read t-mono">{{ readMinutes(post.body) }} min read</span>
    </div>
  </div>
</template>

<style scoped>
.pc { border-radius: var(--radius-md); border: 1px solid var(--border-subtle); }
.pc--card { background: var(--background-surface); padding: 16px; }
.pc--b { padding: 16px; display: flex; flex-direction: column; }
.pc__row { display: flex; align-items: center; gap: 8px; }
.pc__spacer { flex: 1; }
.pc__serif { font-family: var(--font-serif); color: var(--text-primary); }
.pc__body { font-size: var(--text-base); line-height: 1.6; cursor: pointer; }
.pc--b .pc__body { margin: 12px 0; font-size: 16px; }
.clamp-2, .clamp-3, .clamp-4 { display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }
.clamp-2 { -webkit-line-clamp: 2; }
.clamp-3 { -webkit-line-clamp: 3; }
.clamp-4 { -webkit-line-clamp: 4; }
.pc__brow { display: flex; align-items: center; gap: 8px; margin-top: auto; }
.pc__age { flex: 1; min-width: 0; font-size: var(--text-xs); color: var(--text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pc__icon { width: 30px; height: 30px; display: grid; place-items: center; border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; border-radius: var(--radius-sm); }
.pc__icon.on { color: var(--c); }
.pc__header { display: flex; align-items: flex-start; gap: 10px; }
.pc__who { flex: 1; min-width: 0; }
.pc__name { font-family: var(--font-display); font-weight: 500; font-size: var(--text-md); color: var(--text-primary); }
.pc__handle { font-size: var(--text-xs); color: var(--text-tertiary); }
.pc__topic { font-family: var(--font-display); font-weight: 600; font-size: 16px; line-height: 1.3; color: var(--text-primary); margin: 10px 0 8px; cursor: pointer; }
.pc__img { aspect-ratio: 16/9; border-radius: var(--radius-sm); background-size: cover; background-position: center; margin-bottom: 10px; cursor: pointer; }
.pc__img-gate {
  aspect-ratio: 16/9;
  border-radius: var(--radius-sm);
  background: var(--background-raised);
  border: 1px dashed var(--border-medium);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 10px;
  cursor: pointer;
}
.pc__img-gate__text {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  text-align: center;
  padding: 0 var(--space-4);
}
.pc__more { padding: 2px 0; margin-top: 2px; border: 0; background: none; color: var(--accent-primary); font-size: var(--text-sm); cursor: pointer; }
.pc__src { display: flex; gap: 10px; align-items: center; padding: 10px; margin: 4px 0 0; border-radius: var(--radius-sm); background: var(--background-raised); border: 1px solid var(--border-medium); text-decoration: none; }
.pc__fav { width: 18px; height: 18px; border-radius: 4px; flex: 0 0 auto; }
.pc__srcmeta { min-width: 0; }
.pc__srchost { display: block; font-size: var(--text-xs); color: var(--text-tertiary); }
.pc__srctitle { display: block; font-size: var(--text-sm); font-weight: 500; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pc__actions { display: flex; align-items: center; gap: 6px; margin-top: 12px; }
.pc__read { margin-left: auto; font-size: var(--text-xs); color: var(--text-tertiary); }
</style>
