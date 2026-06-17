<script setup lang="ts">
/**
 * Persistent ARIA mini-player. Fixed to the right of the sidebar, spanning the
 * content area. Visible once a track has played this session; reads the
 * module-scoped useAria() singleton so playback survives navigation.
 */
import { useAria, arArtBackground, arFmt, AR_MOOD_COLOR } from '../../composables/useAria'
import { ShareButton } from '../ui'

const { track, playing, progress, remaining, isLiked, toggle, next, prev, toggleLike, openNow, seek, volume, setVolume } = useAria()

function onVolume(e: Event) {
  setVolume(Number((e.target as HTMLInputElement).value))
}
function onSeek(e: MouseEvent) {
  const el = e.currentTarget as HTMLElement
  const r = el.getBoundingClientRect()
  seek(((e.clientX - r.left) / r.width) * 100)
}
</script>

<template>
  <div v-if="track" class="amp" :style="{ '--mood': AR_MOOD_COLOR[track.mood] }">
    <div class="amp__bar" @click="onSeek"><div class="amp__bar-fill" :style="{ width: progress + '%' }" /></div>
    <div class="amp__row">
      <button class="amp__art" :style="arArtBackground(track)" aria-label="Open now playing" @click="openNow">
        <span v-if="track.kind === 'podcast'" class="amp__mic" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8"/></svg>
        </span>
      </button>
      <div class="amp__meta" @click="openNow">
        <div class="amp__title">{{ track.title }}</div>
        <div class="amp__sub mono">{{ track.mood }} · {{ arFmt(remaining) }} left</div>
      </div>
      <button class="amp__icon" :class="{ 'amp__icon--liked': isLiked(track.id) }" aria-label="Like" @click="toggleLike(track.id)">
        <svg width="18" height="18" viewBox="0 0 24 24" :fill="isLiked(track.id) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8"><path d="M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z"/></svg>
      </button>
      <ShareButton
        class="amp__share"
        variant="icon"
        :kind="track.kind === 'podcast' ? 'aria_podcast' : 'aria_track'"
        :ref-id="track.id"
        :text="track.title"
      />
      <button class="amp__icon" aria-label="Previous" @click="prev">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h2v14H6zM20 5v14l-9-7z"/></svg>
      </button>
      <button class="amp__icon amp__icon--play" aria-label="Play/pause" @click="toggle">
        <svg v-if="playing" width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>
        <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      </button>
      <button class="amp__icon" aria-label="Next" @click="next">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M16 5h2v14h-2zM4 5l9 7-9 7z"/></svg>
      </button>
      <input class="amp__vol" type="range" min="0" max="100" :value="volume" @input="onVolume" aria-label="Volume" />
    </div>
  </div>
</template>

<style scoped>
.amp {
  position: fixed; left: var(--sidebar-w); right: 0; bottom: 0; height: 64px; z-index: 60;
  background: color-mix(in srgb, var(--mood) 7%, var(--background-surface));
  border-top: 1px solid var(--border-subtle);
}
.amp__bar { position: absolute; top: 0; left: 0; right: 0; height: 2px; cursor: pointer; }
.amp__bar-fill { height: 100%; background: var(--brain-amber); }
.amp__row { display: flex; align-items: center; gap: 12px; height: 100%; padding: 0 16px; }
.amp__art { position: relative; width: 44px; height: 44px; border-radius: 8px; border: 0; cursor: pointer; flex: 0 0 auto; }
.amp__mic { position: absolute; right: 3px; bottom: 3px; color: #fff; opacity: 0.7; display: flex; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.6)); }
.amp__meta { min-width: 0; flex: 1; cursor: pointer; }
.amp__title { font-family: var(--font-display); font-weight: 500; font-size: 14px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.amp__sub { font-size: 12px; color: var(--text-tertiary); }
.mono { font-family: var(--font-mono); }
.amp__icon { background: none; border: 0; color: var(--text-secondary); cursor: pointer; display: flex; padding: 4px; }
.amp__icon--play { color: var(--accent-primary); }
.amp__icon--liked { color: var(--brain-amber); }
.amp__vol { width: 90px; accent-color: var(--accent-primary); }
</style>
