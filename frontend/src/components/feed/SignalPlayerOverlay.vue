<script setup lang="ts">
/** Full-bleed SIGNAL player with a docked mini mode.
 *
 * Driven by the app-level useSignalPlayer() singleton and mounted once in
 * App.vue, so playback persists across navigation. When `expanded` is false it
 * collapses to a 64px bottom bar; the same <video> element stays mounted, so
 * audio/video keep playing through the transition.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Video } from '../../composables/useContent'
import { logInteraction } from '../../composables/useContent'
import { useSignalPlayer } from '../../composables/useSignalPlayer'
import { useToast } from '../ui/useToast'
import { ShareButton } from '../ui'
import FeedChip from './FeedChip.vue'
import ScoreText from './ScoreText.vue'
import FeedVoteButton from './FeedVoteButton.vue'
import SignalVideoCard from './SignalVideoCard.vue'
import { seededHero } from './seeded'
import { fmtSecs } from './video-util'

const { current: video, related, category, expanded, play, minimize, expand, close } =
  useSignalPlayer()

const toast = useToast()
const el = ref<HTMLVideoElement | null>(null)
// On wide viewports the "More like this" rail sits beside the video as a vertical
// list (cards fill the rail); on narrow ones it stays a horizontal scroll row.
const wide = ref(false)
let mq: MediaQueryList | undefined
function syncWide() { wide.value = !!mq?.matches }
const playing = ref(true)
const cur = ref(0)
const dur = ref(0)
const controls = ref(true)
const showSources = ref(false)
const vote = ref<'up' | 'down' | null>(null)
let hideTimer: ReturnType<typeof setTimeout> | undefined

const pct = computed(() => (dur.value > 0 ? (cur.value / dur.value) * 100 : 0))

// Reset transient playback state whenever a new video starts.
watch(video, (v) => {
  cur.value = 0
  dur.value = v?.duration_seconds ?? 0
  vote.value = null
  showSources.value = false
  playing.value = true
  controls.value = true
})

function poke() {
  controls.value = true
  clearTimeout(hideTimer)
  hideTimer = setTimeout(() => { if (playing.value) controls.value = false }, 3000)
}
function toggle() {
  const v = el.value
  if (!v) return
  if (v.paused) v.play(); else v.pause() // @play / @pause update `playing`
  poke()
}
/** Tap on the stage: toggle when expanded, otherwise pop back to full-screen. */
function onStage() { expanded.value ? toggle() : expand() }
function skip(secs: number) { if (el.value) { el.value.currentTime = Math.max(0, el.value.currentTime + secs); poke() } }
function seekBar(e: MouseEvent) {
  const v = el.value
  if (!v || !dur.value) return
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  v.currentTime = ((e.clientX - r.left) / r.width) * dur.value
}
function onTime() { if (el.value) cur.value = el.value.currentTime }
function onMeta() { if (el.value && el.value.duration) dur.value = el.value.duration }
function setVolume(e: Event) { if (el.value) el.value.volume = Number((e.target as HTMLInputElement).value) / 100 }
function fullscreen() { el.value?.requestFullscreen?.() }

function playRelated(v: Video) {
  play(v, { related: related.value.filter((r) => r.id !== v.id), category: category.value })
}

async function doVote(like: boolean) {
  if (!video.value) return
  vote.value = like ? 'up' : 'down'
  try { await logInteraction(video.value.id, 'video', like ? 'like' : 'dislike'); toast('Feedback saved') } catch { /* best-effort */ }
}

onMounted(() => {
  poke()
  mq = window.matchMedia('(min-width: 1024px)')
  syncWide()
  mq.addEventListener('change', syncWide)
})
onBeforeUnmount(() => {
  clearTimeout(hideTimer)
  mq?.removeEventListener('change', syncWide)
})
</script>

<template>
  <div v-if="video" class="sp" :class="{ 'sp--mini': !expanded }">
    <div class="sp__scroll">
      <!-- player -->
      <div class="sp__stage" @mousemove="expanded && poke()" @click="onStage">
        <video
          ref="el"
          class="sp__video"
          :src="video.video_url ?? undefined"
          autoplay
          playsinline
          :poster="video.thumbnail_url ?? undefined"
          @timeupdate="onTime"
          @loadedmetadata="onMeta"
          @ended="playing = false"
          @play="playing = true"
          @pause="playing = false"
        />
        <div v-if="!video.video_url" class="sp__pending" :style="seededHero(video.creator_name)">
          This video is still being prepared. Check back in a few minutes.
        </div>

        <transition name="sp-fade">
          <div v-show="controls && expanded" class="sp__controls" @click.stop>
            <div class="sp__top">
              <button class="sp__icon" aria-label="Minimize" @click="minimize">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
              </button>
              <span class="sp__ttl">{{ video.title }}</span>
              <button class="sp__icon sp__icon--close" aria-label="Close" @click="close">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="sp__center">
              <button class="sp__seek" aria-label="Back 10s" @click="skip(-10)"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4V1L8 5l4 4V6a6 6 0 1 1-6 6"/></svg></button>
              <button class="sp__play" aria-label="Play/pause" @click="toggle">
                <svg v-if="playing" width="30" height="30" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>
                <svg v-else width="30" height="30" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
              </button>
              <button class="sp__seek" aria-label="Forward 10s" @click="skip(10)"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="transform:scaleX(-1)"><path d="M12 4V1L8 5l4 4V6a6 6 0 1 1-6 6"/></svg></button>
            </div>
            <div class="sp__bottom">
              <div class="sp__bar" @click="seekBar"><div class="sp__fill" :style="{ width: pct + '%' }" /></div>
              <div class="sp__brow">
                <span class="t-mono sp__time">{{ fmtSecs(cur) || '0:00' }} / {{ fmtSecs(dur) || '0:00' }}</span>
                <span class="sp__bright">
                  <input class="sp__vol" type="range" min="0" max="100" value="100" @input="setVolume" aria-label="Volume" />
                  <button class="sp__icon" aria-label="Fullscreen" @click="fullscreen"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3"/></svg></button>
                </span>
              </div>
            </div>
          </div>
        </transition>
      </div>

      <!-- mini-player control row (only when collapsed) -->
      <div v-if="!expanded" class="sp__minibar">
        <div class="sp__minimeta" @click="expand">
          <span class="sp__minititle">{{ video.title }}</span>
          <span class="sp__minisub">{{ category || video.creator_name }}</span>
        </div>
        <button class="sp__miniicon" aria-label="Play/pause" @click="toggle">
          <svg v-if="playing" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>
          <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
        </button>
        <ShareButton variant="icon" kind="signal_video" :ref-id="video.id" :text="video.title" />
        <button class="sp__miniicon" aria-label="Expand" @click="expand">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
        </button>
        <button class="sp__miniicon" aria-label="Close" @click="close">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </button>
      </div>

      <!-- full-screen-only sections -->
      <template v-if="expanded">
        <!-- meta -->
        <div class="sp__meta">
          <h1 class="sp__h">{{ video.title }}</h1>
          <div class="sp__chips">
            <span class="sp__creator">{{ video.creator_name }}</span>
            <FeedChip v-if="category" :label="category" :active="false" />
            <ScoreText :score="video.score" />
          </div>
          <p v-if="video.description" class="sp__desc">{{ video.description }}</p>
          <div class="sp__actions">
            <FeedVoteButton label="Like" color="var(--success)" icon="up" :active="vote === 'up'" @click="doVote(true)" />
            <FeedVoteButton label="Dislike" color="var(--danger)" icon="down" :active="vote === 'down'" @click="doVote(false)" />
            <ShareButton kind="signal_video" :ref-id="video.id" :text="video.title" />
          </div>
          <button class="sp__srctoggle" @click="showSources = !showSources">Sources {{ showSources ? '▴' : '▾' }}</button>
          <p v-if="showSources" class="sp__srcnote">Sources aren't listed for this video yet.</p>
        </div>

        <!-- more like this -->
        <div v-if="related.length" class="sp__more">
          <div class="sp__morehd">More like this</div>
          <div class="sp__morerow">
            <SignalVideoCard v-for="r in related" :key="r.id" :video="r" :width="200" :fluid="wide" @play="playRelated(r)" />
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.sp { position: fixed; inset: 0; z-index: 100; background: var(--background-page); overflow-y: auto; animation: sp-in 0.15s ease; }
@keyframes sp-in { from { opacity: 0; } to { opacity: 1; } }
.sp__scroll { max-width: 960px; margin: 0 auto; }
.sp__stage { position: relative; aspect-ratio: 16/9; background: #000; cursor: pointer; }
.sp__video { width: 100%; height: 100%; object-fit: contain; background: #000; }
.sp__pending { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; padding: 24px; color: #fff; font-size: var(--text-sm); }
.sp__controls { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: space-between; padding: 16px; }
.sp__controls > * { pointer-events: auto; }
.sp__top { display: flex; align-items: center; gap: 12px; }
.sp__icon { background: none; border: 0; color: #fff; cursor: pointer; display: flex; }
.sp__icon--close { margin-left: auto; }
.sp__ttl { font-family: var(--font-display); font-weight: 600; font-size: var(--text-sm); color: #fff; }
.sp__center { display: flex; align-items: center; justify-content: center; gap: 36px; }
.sp__seek { background: none; border: 0; color: #fff; cursor: pointer; display: flex; }
.sp__play { width: 60px; height: 60px; border-radius: 50%; background: var(--accent-primary); color: #fff; border: 0; cursor: pointer; display: grid; place-items: center; }
.sp__bottom { display: flex; flex-direction: column; gap: 8px; }
.sp__bar { height: 4px; border-radius: 999px; background: rgba(255,255,255,0.25); cursor: pointer; }
.sp__fill { height: 100%; border-radius: 999px; background: var(--brain-amber); }
.sp__brow { display: flex; align-items: center; justify-content: space-between; }
.sp__time { font-family: var(--font-mono); font-size: var(--text-xs); color: #fff; }
.sp__bright { display: flex; align-items: center; gap: 12px; }
.sp__vol { width: 90px; accent-color: var(--brain-amber); }
.sp__meta { padding: 20px 16px; display: flex; flex-direction: column; gap: 12px; }
.sp__h { font-family: var(--font-display); font-weight: 600; font-size: 20px; color: var(--text-primary); }
.sp__chips { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sp__creator { font-size: var(--text-sm); color: var(--text-secondary); }
.sp__desc { font-family: var(--font-serif); font-size: 15px; line-height: 1.6; color: var(--text-secondary); }
.sp__actions { display: flex; gap: 8px; }
.sp__srctoggle { align-self: flex-start; background: none; border: 0; color: var(--text-primary); font-family: var(--font-display); font-weight: 500; font-size: var(--text-md); cursor: pointer; padding: 0; }
.sp__srcnote { font-size: var(--text-sm); color: var(--text-tertiary); }
.sp__more { padding: 0 16px 48px; }
.sp__morehd { font-family: var(--font-display); font-weight: 600; font-size: 15px; color: var(--text-primary); margin: 8px 0 12px; }
.sp__morerow { display: flex; gap: 16px; overflow-x: auto; padding-bottom: 6px; }
.sp-fade-enter-active, .sp-fade-leave-active { transition: opacity 0.2s; }
.sp-fade-enter-from, .sp-fade-leave-to { opacity: 0; }

/* ── Docked mini-player ─────────────────────────────────────────────────────
   A 64px bar pinned to the bottom of the content area. The <video> stays mounted
   (just shrunk), so playback continues; only the chrome differs. */
.sp--mini {
  inset: auto; top: auto; left: var(--sidebar-w); right: 0; bottom: 0;
  height: 64px; overflow: hidden; z-index: 130;
  background: var(--background-surface); border-top: 1px solid var(--border-subtle);
  animation: none;
}
.sp--mini .sp__scroll { max-width: none; margin: 0; display: flex; align-items: center; height: 64px; padding: 0; }
.sp--mini .sp__stage { flex: 0 0 auto; width: 114px; height: 64px; aspect-ratio: auto; border-radius: 0; }
.sp--mini .sp__video { height: 64px; }
.sp__minibar { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; padding: 0 12px; }
.sp__minimeta { min-width: 0; flex: 1; cursor: pointer; }
.sp__minititle { display: block; font-family: var(--font-display); font-weight: 500; font-size: 14px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sp__minisub { display: block; font-size: 12px; color: var(--text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sp__miniicon { background: none; border: 0; color: var(--text-secondary); cursor: pointer; display: flex; padding: 6px; border-radius: 999px; }
.sp__miniicon:hover { color: var(--text-primary); background: var(--background-elevated, rgba(255,255,255,.05)); }

/* Wide viewports: video + meta on the left, "More like this" as a vertical rail
   on the right — using the side and bottom space a single row would waste. */
@media (min-width: 1024px) {
  .sp:not(.sp--mini) .sp__scroll {
    max-width: 1500px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(300px, 26vw, 400px);
    grid-template-areas: "stage rail" "meta rail";
    align-items: start;
    column-gap: 32px;
    padding: 24px 24px 56px;
  }
  .sp:not(.sp--mini) .sp__stage { grid-area: stage; border-radius: var(--radius-md); overflow: hidden; }
  .sp:not(.sp--mini) .sp__meta { grid-area: meta; padding: 20px 0 0; }
  .sp:not(.sp--mini) .sp__more { grid-area: rail; padding: 0; }
  .sp:not(.sp--mini) .sp__morehd { margin-top: 0; }
  .sp:not(.sp--mini) .sp__morerow { flex-direction: column; overflow: visible; gap: 14px; padding-bottom: 0; }
}
</style>
