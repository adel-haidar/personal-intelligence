<script setup lang="ts">
/**
 * PULSE — a Facebook-style social feed. A left rail lists every persona ("the
 * people"); clicking one scopes the centre column to that persona's posts and
 * shows a profile header. The "All personas" view keeps the editorial hero +
 * single-column news feed.
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { usePulseFeed, useCreators, logInteraction, type Post, type Tone } from '../composables/useContent'
import { useToast } from '../components/ui/useToast'
import FeedChip from '../components/feed/FeedChip.vue'
import FeaturedCard from '../components/feed/FeaturedCard.vue'
import TonePill from '../components/feed/TonePill.vue'
import ScoreText from '../components/feed/ScoreText.vue'
import FeedVoteButton from '../components/feed/FeedVoteButton.vue'
import PulsePostCard from '../components/feed/PulsePostCard.vue'
import PulseReader from '../components/feed/PulseReader.vue'
import PersonaRail from '../components/feed/PersonaRail.vue'
import PersonaHeader from '../components/feed/PersonaHeader.vue'
import { headline, readMinutes } from '../components/feed/post-format'
import BrainBanner from '../components/BrainBanner.vue'

const { posts, loading, error, hasMore, loadMore, creator, setCreator } = usePulseFeed()
const { creators, load: loadCreators } = useCreators()
const toast = useToast()

const TONES: (Tone | 'all')[] = ['all', 'informative', 'satirical', 'critical', 'supportive']
const TONE_COLOR: Record<string, string> = {
  all: 'var(--accent-primary)',
  informative: 'var(--accent-primary)',
  satirical: 'var(--brain-amber)',
  critical: 'var(--danger)',
  supportive: 'var(--success)',
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const tone = ref<Tone | 'all'>('all')
const reading = ref<Post | null>(null)
const votes = reactive<Record<string, 'up' | 'down'>>({})

onMounted(() => {
  loadMore()
  loadCreators()
})

const activeCreator = computed(() => creators.value.find((c) => c.id === creator.value) ?? null)

const filtered = computed(() => posts.value.filter((p) => tone.value === 'all' || p.tone === tone.value))

// The editorial hero only appears in the unfiltered "All personas" view.
const featured = computed<Post | null>(() =>
  creator.value === null && filtered.value.length
    ? filtered.value.reduce((a, b) => (a.score >= b.score ? a : b))
    : null,
)
const rest = computed<Post[]>(() => filtered.value.filter((p) => p.id !== featured.value?.id))

function selectPersona(id: string | null) {
  tone.value = 'all'
  reading.value = null
  void setCreator(id)
}

async function vote(post: Post, like: boolean) {
  votes[post.id] = like ? 'up' : 'down'
  try {
    await logInteraction(post.id, 'post', like ? 'like' : 'dislike')
    toast('Feedback saved')
  } catch { /* best-effort */ }
}
</script>

<template>
  <div class="pulse">
    <!-- Mobile persona strip -->
    <PersonaRail
      class="pulse__strip prail--strip"
      :creators="creators"
      :selected="creator"
      @select="selectPersona"
    />

    <div class="pulse__layout">
      <!-- Left rail: the people -->
      <aside class="pulse__rail">
        <PersonaRail :creators="creators" :selected="creator" @select="selectPersona" />
      </aside>

      <!-- Centre column: the feed -->
      <main class="pulse__main">
        <BrainBanner />

        <PersonaHeader
          v-if="activeCreator"
          :creator="activeCreator"
          :post-count="posts.length"
          @back="selectPersona(null)"
        />

        <div v-else class="pulse__masthead">
          <span class="pulse__title">PULSE</span>
        </div>

        <!-- tone chips -->
        <div class="pulse__chips">
          <FeedChip v-for="t in TONES" :key="t" :label="cap(t)" :color="TONE_COLOR[t]" :active="tone === t" @click="tone = t" />
        </div>

        <!-- loading / error -->
        <div v-if="loading && posts.length === 0" class="pulse__skeleton">
          <div v-for="n in 4" :key="n" class="pulse__sk" />
        </div>
        <div v-else-if="error" class="pulse__error">
          <p>Couldn't load your feed.</p>
          <button class="pulse__retry" @click="loadMore">Try again</button>
        </div>

        <template v-else>
          <div class="pulse__feed">
            <!-- featured hero (All personas view only) -->
            <div v-if="featured" class="pulse__feat">
              <FeaturedCard
                :seed="featured.creator_name"
                :image="featured.image_url"
                :title="headline(featured.body)"
                :meta-name="featured.creator_name"
                :meta-trailing="`· ${readMinutes(featured.body)} min read`"
                @click="reading = featured"
              >
                <template #topLeft><TonePill v-if="featured.tone" :tone="featured.tone" /></template>
                <template #topRight><ScoreText :score="featured.score" on-dark /></template>
              </FeaturedCard>
              <div class="pulse__featactions">
                <FeedVoteButton :label="`${featured.score.toFixed(2)} Like`" color="var(--success)" icon="up" :active="votes[featured.id] === 'up'" @click="vote(featured, true)" />
                <FeedVoteButton label="Dislike" color="var(--danger)" icon="down" :active="votes[featured.id] === 'down'" @click="vote(featured, false)" />
                <FeedVoteButton label="Open" color="var(--accent-primary)" icon="open" @click="reading = featured" />
              </div>
            </div>

            <!-- single-column news feed -->
            <div class="pulse__column">
              <PulsePostCard
                v-for="p in rest" :key="p.id" :post="p"
                :vote="votes[p.id] ?? null" @vote="(l) => vote(p, l)" @open="reading = p"
              />
            </div>

            <div v-if="filtered.length === 0" class="pulse__empty">
              <template v-if="activeCreator">{{ activeCreator.name }} hasn't posted yet.</template>
              <template v-else>Nothing here yet. Add to your brain and your feed will fill with stories.</template>
            </div>

            <button v-if="hasMore() && filtered.length" class="pulse__more" :disabled="loading" @click="loadMore">
              {{ loading ? 'Loading…' : 'Load more' }}
            </button>
          </div>
        </template>
      </main>
    </div>

    <PulseReader
      v-if="reading"
      :post="reading"
      :vote="votes[reading.id] ?? null"
      @vote="(l) => vote(reading!, l)"
      @close="reading = null"
    />
  </div>
</template>

<style scoped>
.pulse { max-width: var(--content-wide, 1100px); margin: 0 auto; padding: 8px 0 48px; }

/* Two-column Facebook layout on wide screens; single column on mobile. */
.pulse__layout { display: block; }
.pulse__rail { display: none; }
.pulse__strip { padding: 0 4px 12px; }

@media (min-width: 1000px) {
  .pulse__layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 28px; align-items: start; }
  .pulse__rail { display: block; position: sticky; top: 16px; }
  .pulse__strip { display: none; }
  .pulse__main { max-width: 640px; }
}

.pulse__masthead { display: flex; align-items: center; justify-content: space-between; padding: 0 4px 12px; }
.pulse__title { font-family: var(--font-display); font-weight: 600; font-size: 15px; letter-spacing: 0.1em; color: var(--text-primary); }
.pulse__chips { display: flex; gap: 8px; overflow-x: auto; padding: 2px 4px 18px; }
.pulse__feed { display: flex; flex-direction: column; gap: 14px; }
.pulse__featactions { display: flex; gap: 6px; margin-top: 10px; }
.pulse__feat { width: 100%; }
/* Facebook-style single-column news feed. */
.pulse__column { display: flex; flex-direction: column; gap: 14px; }
.pulse__skeleton { display: flex; flex-direction: column; gap: 14px; }
.pulse__sk { height: 160px; border-radius: var(--radius-md); background: var(--background-raised); animation: pulse-sk 1.4s ease-in-out infinite; }
@keyframes pulse-sk { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }
.pulse__error, .pulse__empty { text-align: center; padding: 48px 16px; color: var(--text-secondary); font-family: var(--font-serif); }
.pulse__retry { margin-top: 12px; height: 36px; padding: 0 16px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: transparent; color: var(--text-secondary); cursor: pointer; }
.pulse__more { align-self: center; margin-top: 8px; height: 40px; padding: 0 24px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: transparent; color: var(--text-secondary); cursor: pointer; font-size: var(--text-sm); }
</style>
