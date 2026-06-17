<script setup lang="ts">
/**
 * StoriesFilm — Film detail page.
 * Fetches film data from the real /api/stories/films/{id} endpoint.
 * Genre/score/year/topics/"why" removed — not in real API.
 * Uses category chip, premise, watch_progress, related films.
 */
import { computed, ref, onMounted, watch } from 'vue'
import type { StoriesView, StoryItem } from '../../composables/useStories'
import {
  fetchFilm,
  stPosterStyle,
  stProgressPct,
  stLeftLabel,
  stFmt,
  stDurLabel,
  postLike,
} from '../../composables/useStories'
import StoryPoster from './StoryPoster.vue'
import StorySection from './StorySection.vue'
import { ShareButton } from '../ui'

const props = defineProps<{
  id: string
}>()

const emit = defineEmits<{
  (e: 'navigate', v: StoriesView): void
  (e: 'play', item: StoryItem, ep?: number): void
}>()

const film = ref<StoryItem | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const liked = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    film.value = await fetchFilm(props.id)
    liked.value = film.value.liked ?? false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.id, load)

const related = computed((): StoryItem[] => film.value?.related?.filter((r) => r.status !== 'generating') ?? [])
const progressPct = computed(() => stProgressPct(film.value?.watch_progress))
const leftLabel = computed(() => stLeftLabel(film.value?.watch_progress))
const resumeLabel = computed(() => {
  const wp = film.value?.watch_progress
  if (!wp) return 'Play'
  return `Continue from ${stFmt(wp.position_seconds)}`
})

async function toggleLike() {
  if (!film.value) return
  const next = !liked.value
  liked.value = next
  try {
    await postLike({ content_type: 'film', content_id: film.value.id, liked: next })
  } catch {
    liked.value = !next // revert
  }
}
</script>

<template>
  <!-- loading -->
  <div v-if="loading" class="st-loading">Loading…</div>

  <!-- error -->
  <div v-else-if="error" class="st-error">
    <p>{{ error }}</p>
    <button class="back-btn" @click="load()">Retry</button>
  </div>

  <div v-else-if="film">
    <!-- back -->
    <button class="back-btn" @click="emit('navigate', { name: 'library' })">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="transform: rotate(180deg)"><path d="M9 18l6-6-6-6"/></svg>
      Back to Stories
    </button>

    <!-- landscape key visual -->
    <div
      class="st-detail-hero"
      :style="film.poster_url || film.thumbnail_url
        ? { backgroundImage: `url(${film.poster_url ?? film.thumbnail_url})`, backgroundSize: 'cover', backgroundPosition: 'center' }
        : stPosterStyle(film.title)"
    >
      <div class="st-cine" />
      <div class="st-detail-hero__body">
        <span v-if="film.category" class="st-chip">{{ film.category.toUpperCase().slice(0, 8) }}</span>
        <div class="st-detail-hero__title">{{ film.title }}</div>
      </div>
    </div>

    <!-- two-column grid -->
    <div class="st-detail-grid">
      <!-- left: metadata + content -->
      <div>
        <div class="t-mono t-secondary" style="font-size: var(--text-sm); margin-bottom: var(--space-5)">
          <template v-if="film.duration_seconds">{{ stDurLabel(film.duration_seconds) }} · </template>
          <template v-if="film.category">{{ film.category }}</template>
        </div>

        <div v-if="film.premise">
          <div class="st-eyebrow" style="margin-bottom: var(--space-3)">Premise</div>
          <p class="t-serif" style="font-size: var(--text-md); line-height: 1.75; margin-bottom: var(--space-6)">
            {{ film.premise }}
          </p>
        </div>

        <!-- generating notice -->
        <div v-if="film.status === 'generating'" class="st-generating">
          This film is still being generated.
        </div>
      </div>

      <!-- right: sticky play panel -->
      <div class="st-play-panel">
        <div v-if="progressPct != null" class="progress-bar" style="margin-bottom: var(--space-3)">
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: progressPct + '%' }" />
          </div>
          <div class="t-mono t-tertiary" style="font-size: var(--text-xs); margin-top: var(--space-1)">{{ leftLabel }}</div>
        </div>
        <button
          class="play-cta"
          :class="{ 'play-cta--amber': progressPct != null }"
          :disabled="film.status !== 'ready'"
          @click="film && emit('play', film)"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>
          {{ film.status === 'generating' ? 'Generating…' : resumeLabel }}
        </button>
        <button class="like-btn" :class="{ 'like-btn--on': liked }" @click="toggleLike">
          <svg width="16" height="16" viewBox="0 0 24 24" :fill="liked ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8"><path d="M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z"/></svg>
          {{ liked ? 'Liked' : 'Like' }}
        </button>
        <ShareButton
          v-if="film.status === 'ready'"
          class="st-share"
          kind="stories_film"
          :ref-id="film.id"
          :text="film.title"
        />
      </div>
    </div>

    <!-- More like this -->
    <StorySection v-if="related.length > 0" title="More like this">
      <StoryPoster
        v-for="f in related"
        :key="f.id"
        :item="f"
        @click="emit('navigate', { name: 'film', id: f.id })"
      />
    </StorySection>
  </div>
</template>

<style scoped>
.st-loading {
  font-family: var(--font-body);
  font-size: var(--text-base);
  color: var(--text-tertiary);
  padding: var(--space-10) 0;
  text-align: center;
}
.st-error {
  padding: var(--space-8);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  text-align: center;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 32px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-family: var(--font-display);
  font-weight: 500;
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  margin-bottom: var(--space-4);
  transition: border-color 0.12s, color 0.12s;
}
.back-btn:hover { border-color: var(--border-medium); color: var(--text-primary); }

.st-detail-hero {
  position: relative;
  border-radius: var(--radius-lg);
  overflow: hidden;
  aspect-ratio: 21/9;
  background: var(--background-raised);
  margin-bottom: var(--space-6);
}
.st-cine {
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, rgba(12,12,20,0.92) 0%, rgba(12,12,20,0.60) 40%, rgba(12,12,20,0) 100%);
}
.st-detail-hero__body {
  position: absolute;
  left: var(--space-8);
  right: var(--space-8);
  bottom: var(--space-6);
}
.st-detail-hero__title {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-xl);
  color: #fff;
  margin-top: var(--space-3);
  line-height: 1.15;
}
.st-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--brain-amber-surface);
  color: var(--brain-amber);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.st-detail-grid {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: var(--space-8);
  align-items: start;
}
@media (max-width: 900px) {
  .st-detail-grid { grid-template-columns: 1fr; }
}

.st-eyebrow {
  font-family: var(--font-body);
  font-weight: 500;
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.st-generating {
  padding: var(--space-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  font-family: var(--font-body);
}

/* sticky play panel */
.st-play-panel { position: sticky; top: var(--space-6); display: flex; flex-direction: column; gap: var(--space-3); }
.progress-track {
  height: 4px;
  background: var(--background-raised);
  border-radius: 999px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--brain-amber);
  border-radius: 999px;
  transition: width 0.3s var(--ease);
}
.play-cta {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 44px;
  border-radius: var(--radius-sm);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-base);
  background: var(--accent-primary);
  color: #fff;
  border: none;
  cursor: pointer;
  transition: background 0.12s;
}
.play-cta:hover:not(:disabled) { background: var(--accent-hover); }
.play-cta:disabled { opacity: 0.5; cursor: not-allowed; }
.play-cta--amber { background: var(--brain-amber); color: #1c1b2e; }
.play-cta--amber:hover:not(:disabled) { opacity: 0.9; }

.like-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 40px;
  border-radius: var(--radius-sm);
  font-family: var(--font-display);
  font-weight: 500;
  font-size: var(--text-sm);
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: border-color 0.12s, color 0.12s;
}
.like-btn:hover { border-color: var(--border-medium); color: var(--text-primary); }
.like-btn--on { color: var(--brain-amber); border-color: var(--brain-amber); }
</style>
