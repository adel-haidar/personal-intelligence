<script setup lang="ts">
/**
 * SIGNAL — editorial, discovery-first channel: masthead → category chips →
 * featured hero → Recent → by-category sections, with inline search and a
 * full-bleed player overlay. Replaces the old library-column + side player.
 */
import { computed, onMounted, ref } from 'vue'
import { useSignalLibrary, type Video } from '../composables/useContent'
import FeedChip from '../components/feed/FeedChip.vue'
import FeaturedCard from '../components/feed/FeaturedCard.vue'
import SignalSection from '../components/feed/SignalSection.vue'
import SignalVideoCard from '../components/feed/SignalVideoCard.vue'
import SignalSearch from '../components/feed/SignalSearch.vue'
import SignalPlayerOverlay from '../components/feed/SignalPlayerOverlay.vue'
import { fmtSecs, isPlayable, isProcessing } from '../components/feed/video-util'
import BrainBanner from '../components/BrainBanner.vue'

const { videos, loading, error, topicNames, loadMore } = useSignalLibrary()

const cat = ref('All')
const searching = ref(false)
const playing = ref<Video | null>(null)

onMounted(() => loadMore())

const catOf = (v: Video) => topicNames.value[v.topic_id] ?? ''
const cats = computed(() => [...new Set(videos.value.map(catOf).filter(Boolean))].sort())
const inCat = (v: Video) => cat.value === 'All' || catOf(v) === cat.value
const filtered = computed(() => videos.value.filter(inCat))

const featured = computed<Video | null>(() => {
  const ready = filtered.value.filter(isPlayable)
  const pool = ready.length ? ready : filtered.value
  return pool.length ? pool.reduce((a, b) => (a.score >= b.score ? a : b)) : null
})
const recent = computed(() => filtered.value.filter((v) => v.id !== featured.value?.id))

// A topic earns its own row only if it has enough videos to fill one;
// topics with a single video are pooled into "Miscellaneous" so we don't
// waste a full row (and the user's scroll) on one card.
const MIN_ROW = 2
const byCategory = computed(() => {
  const sections = cats.value
    .map((c) => ({ cat: c, vids: videos.value.filter((v) => catOf(v) === c && v.id !== featured.value?.id) }))
    .filter((s) => s.vids.length > 0)
  const rows = sections.filter((s) => s.vids.length >= MIN_ROW).map((s) => ({ ...s, misc: false }))
  const misc = sections.filter((s) => s.vids.length < MIN_ROW).flatMap((s) => s.vids)
  return misc.length ? [...rows, { cat: 'Miscellaneous', vids: misc, misc: true }] : rows
})

const relatedFor = (v: Video) =>
  videos.value.filter((x) => x.id !== v.id && isPlayable(x) && catOf(x) === catOf(v)).slice(0, 8)

function play(v: Video) {
  if (!isProcessing(v)) playing.value = v
}
</script>

<template>
  <div v-if="searching" class="signal">
    <SignalSearch :videos="videos" :topic-names="topicNames" @play="(v) => { searching = false; play(v) }" @cancel="searching = false" />
  </div>

  <div v-else class="signal">
    <BrainBanner />

    <!-- masthead -->
    <div class="signal__masthead">
      <span class="signal__title">SIGNAL</span>
      <button class="signal__search" aria-label="Search" @click="searching = true">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.3-4.3"/></svg>
      </button>
    </div>

    <!-- category chips -->
    <div v-if="cats.length" class="signal__chips">
      <FeedChip label="All" :active="cat === 'All'" @click="cat = 'All'" />
      <FeedChip v-for="c in cats" :key="c" :label="c" :active="cat === c" @click="cat = c" />
    </div>

    <!-- loading / error -->
    <div v-if="loading && videos.length === 0" class="signal__skeleton">
      <div class="signal__skhero" />
      <div class="signal__skrow"><div v-for="n in 4" :key="n" class="signal__skcard" /></div>
    </div>
    <div v-else-if="error" class="signal__error">
      <p>Couldn't load your videos.</p>
      <button class="signal__retry" @click="loadMore">Try again</button>
    </div>

    <template v-else-if="filtered.length === 0">
      <div class="signal__empty">No videos yet. Add to your brain and your channel will fill up.</div>
    </template>

    <template v-else>
      <!-- featured hero -->
      <FeaturedCard
        v-if="featured"
        :seed="featured.creator_name"
        :image="featured.thumbnail_url"
        :title="featured.title"
        :meta-name="featured.creator_name"
        :meta-trailing="`· ${featured.score.toFixed(2)}`"
        @click="play(featured)"
      >
        <template #topLeft><FeedChip :label="catOf(featured) || 'Signal'" :active="true" /></template>
        <template #topRight><span class="t-mono signal__herodur">{{ fmtSecs(featured.duration_seconds) }}</span></template>
        <template #center>
          <span class="signal__playbtn" :class="{ 'signal__playbtn--off': isProcessing(featured) }">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          </span>
        </template>
      </FeaturedCard>

      <!-- recent / filtered -->
      <SignalSection :title="cat === 'All' ? 'Recent' : cat" :see-all="false">
        <SignalVideoCard v-for="v in recent" :key="v.id" :video="v" @play="play(v)" />
      </SignalSection>

      <!-- by category (only on All) -->
      <template v-if="cat === 'All'">
        <SignalSection v-for="s in byCategory" :key="s.cat" :title="s.cat" accent :see-all="!s.misc" @all="cat = s.cat">
          <SignalVideoCard v-for="v in s.vids" :key="v.id" :video="v" @play="play(v)" />
        </SignalSection>
      </template>
    </template>

    <SignalPlayerOverlay
      v-if="playing"
      :video="playing"
      :category="catOf(playing)"
      :related="relatedFor(playing)"
      @close="playing = null"
      @play="(v) => (playing = v)"
    />
  </div>
</template>

<style scoped>
.signal { max-width: var(--content-dashboard); margin: 0 auto; padding: 8px 0 48px; }
.signal__masthead { display: flex; align-items: center; justify-content: space-between; padding: 0 4px 12px; }
.signal__title { font-family: var(--font-display); font-weight: 600; font-size: 15px; letter-spacing: 0.1em; color: var(--text-primary); }
.signal__search { background: none; border: 0; color: var(--text-primary); cursor: pointer; display: flex; padding: 6px; }
.signal__chips { display: flex; gap: 8px; overflow-x: auto; padding: 2px 4px 18px; }
.signal__herodur { color: #fff; font-family: var(--font-mono); font-size: var(--text-xs); }
.signal__playbtn { width: 52px; height: 52px; border-radius: 50%; background: rgba(255,255,255,0.22); border: 1px solid rgba(255,255,255,0.3); backdrop-filter: blur(4px); display: grid; place-items: center; color: #fff; }
.signal__playbtn--off { opacity: 0.4; }
.signal__skeleton { display: flex; flex-direction: column; gap: 20px; }
.signal__skhero { height: 260px; border-radius: var(--radius-md); background: var(--background-raised); }
.signal__skrow { display: flex; gap: 16px; }
.signal__skcard { width: 220px; height: 150px; border-radius: var(--radius-sm); background: var(--background-raised); }
.signal__error, .signal__empty { text-align: center; padding: 48px 16px; color: var(--text-secondary); font-family: var(--font-serif); }
.signal__retry { margin-top: 12px; height: 36px; padding: 0 16px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: transparent; color: var(--text-secondary); cursor: pointer; }
</style>
