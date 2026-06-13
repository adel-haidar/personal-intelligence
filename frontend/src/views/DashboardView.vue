<script setup lang="ts">
/**
 * DashboardView — Mission control. Route: /overview
 *
 * Data sources (each fetched independently via Promise.allSettled):
 *   GET /api/auth/me           → User (display_name, onboarding_completed)
 *   GET /api/memory/stats      → MemoryStats (total, last_updated)
 *   GET /api/memory?page=1&page_size=5   → 5 recent memories for activity feed
 *   GET /api/content/posts?page=1&page_size=5  → Pulse module stat + activity
 *   GET /api/content/videos?page=1&page_size=5 → Signal module stat + activity
 *   GET /api/health/trends     → Health module (latest resting_hr)
 *
 * Brain-health heuristic (documented):
 *   score = Math.min(100, Math.floor(total * 1.2))
 *   ≤25  → Empty   (danger)
 *   ≤50  → Starting (amber)
 *   ≤75  → Growing  (amber)
 *   >75  → Rich     (success)
 *
 * Failure isolation:
 *   Promise.allSettled wraps all six calls. A rejected health/content call
 *   leaves that section in its empty/error state without blanking the page.
 *   The /me call is also wrapped; if it fails the greeting falls back to
 *   "Good {time of day}." and no onboarding banner is shown.
 */

import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiButton from '../components/ui/PiButton.vue'
import IconButton from '../components/ui/IconButton.vue'
import PIIcon from '../components/ui/PIIcon.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import { requireAuth } from '../composables/useAuth'
import { API_BASE } from '../config/env'
import type { User } from '../types/user'
import type { MemoryStats } from '../types/memory'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MemoryItem {
  memory_id: string
  title: string
  created_at: string
  tags: string[]
}

interface PostItem {
  id?: string
  post_id?: string
  created_at: string
  creator_name?: string
  title?: string
}

interface VideoItem {
  id?: string
  video_id?: string
  created_at: string
  title?: string
  status?: string
}

interface HealthTrends {
  days: string[]
  series: {
    resting_hr?: (number | null)[]
    steps?: (number | null)[]
    [key: string]: (number | null)[] | undefined
  }
}

type BrainBandVariant = 'danger' | 'amber' | 'success'
interface BrainBand {
  label: string
  variant: BrainBandVariant
}

interface ActivityItem {
  icon: string
  text: string
  time: string
  ts: number
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const router = useRouter()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const me = ref<User | null>(null)
const memStats = ref<MemoryStats>({ total: 0, last_updated: null })
const recentMemories = ref<MemoryItem[]>([])
const postTotal = ref<number | null>(null)
const recentPosts = ref<PostItem[]>([])
const videoTotal = ref<number | null>(null)
const recentVideos = ref<VideoItem[]>([])
const restingHr = ref<number | null>(null)

const loading = ref(true)

// Onboarding banner: dismissed for the current session via sessionStorage
const BANNER_KEY = 'pi_dashboard_banner_dismissed'
const bannerDismissed = ref(sessionStorage.getItem(BANNER_KEY) === '1')

function dismissBanner(): void {
  bannerDismissed.value = true
  sessionStorage.setItem(BANNER_KEY, '1')
}

// ---------------------------------------------------------------------------
// Greeting + date stamp
// ---------------------------------------------------------------------------
const now = new Date()
const hour = now.getHours()
const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

const dateStamp = now.toLocaleDateString('en-GB', {
  weekday: 'short',
  day: '2-digit',
  month: 'short',
}) + ' ' + now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

// ---------------------------------------------------------------------------
// Brain-health heuristic
// ---------------------------------------------------------------------------
function brainScore(total: number): number {
  return Math.min(100, Math.floor(total * 1.2))
}

function brainBand(score: number): BrainBand {
  if (score <= 25) return { label: 'Empty', variant: 'danger' }
  if (score <= 50) return { label: 'Starting', variant: 'amber' }
  if (score <= 75) return { label: 'Growing', variant: 'amber' }
  return { label: 'Rich', variant: 'success' }
}

const healthScore = computed(() => brainScore(memStats.value.total))
const healthBand = computed(() => brainBand(healthScore.value))

// ---------------------------------------------------------------------------
// Relative time helper
// ---------------------------------------------------------------------------
function relativeTime(iso: string | null): string {
  if (!iso) return 'Not started yet'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min${mins === 1 ? '' : 's'} ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? '' : 's'} ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  const months = Math.floor(days / 30)
  return `${months} month${months === 1 ? '' : 's'} ago`
}

const brainSubline = computed(() => {
  const t = memStats.value.total
  if (t === 0) return 'Not started yet'
  const last = memStats.value.last_updated ? `Last updated ${relativeTime(memStats.value.last_updated)}` : 'Not started yet'
  return last
})

// ---------------------------------------------------------------------------
// Recent activity feed
// ---------------------------------------------------------------------------
const activityFeed = computed((): ActivityItem[] => {
  const items: ActivityItem[] = []

  for (const m of recentMemories.value) {
    items.push({
      icon: 'spark',
      text: 'You added a memory',
      time: relativeTime(m.created_at),
      ts: new Date(m.created_at).getTime(),
    })
  }

  for (const p of recentPosts.value) {
    const who = p.creator_name ? ` by ${p.creator_name}` : ''
    items.push({
      icon: 'pulse',
      text: `Pulse generated a post${who}`,
      time: relativeTime(p.created_at),
      ts: new Date(p.created_at).getTime(),
    })
  }

  for (const v of recentVideos.value) {
    const title = v.title ? `: ${v.title}` : ''
    items.push({
      icon: 'signal',
      text: `Signal video ready${title}`,
      time: relativeTime(v.created_at),
      ts: new Date(v.created_at).getTime(),
    })
  }

  return items
    .sort((a, b) => b.ts - a.ts)
    .slice(0, 6)
})

const activityEmpty = computed(
  () => !loading.value && activityFeed.value.length === 0,
)

// ---------------------------------------------------------------------------
// Module card states
// ---------------------------------------------------------------------------
const pulseEmpty = computed(() => postTotal.value === null || postTotal.value === 0)
const signalEmpty = computed(() => videoTotal.value === null || videoTotal.value === 0)
const healthEmpty = computed(() => restingHr.value === null)

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function authHeader(): Promise<HeadersInit> {
  const token = await requireAuth()
  return { Authorization: `Bearer ${token}` }
}

async function fetchMe(): Promise<void> {
  const headers = await authHeader()
  const res = await fetch(`${API_BASE}/api/auth/me`, { headers })
  if (!res.ok) throw new Error(`/me failed: ${res.status}`)
  const data = await res.json() as { user: User }
  me.value = data.user
}

async function fetchMemoryStats(): Promise<void> {
  const headers = await authHeader()
  const res = await fetch(`${API_BASE}/api/memory/stats`, { headers })
  if (!res.ok) throw new Error(`/memory/stats failed: ${res.status}`)
  memStats.value = await res.json() as MemoryStats
}

async function fetchRecentMemories(): Promise<void> {
  const headers = await authHeader()
  const res = await fetch(`${API_BASE}/api/memory?page=1&page_size=5`, { headers })
  if (!res.ok) throw new Error(`/memory failed: ${res.status}`)
  const data = await res.json() as { items: MemoryItem[]; total: number }
  recentMemories.value = data.items
}

async function fetchPosts(): Promise<void> {
  const headers = await authHeader()
  const res = await fetch(`${API_BASE}/api/content/posts?page=1&page_size=5`, { headers })
  if (!res.ok) throw new Error(`/content/posts failed: ${res.status}`)
  const data = await res.json() as { items: PostItem[]; total: number }
  postTotal.value = data.total
  recentPosts.value = data.items
}

async function fetchVideos(): Promise<void> {
  const headers = await authHeader()
  const res = await fetch(`${API_BASE}/api/content/videos?page=1&page_size=5`, { headers })
  if (!res.ok) throw new Error(`/content/videos failed: ${res.status}`)
  const data = await res.json() as { items: VideoItem[]; total: number }
  videoTotal.value = data.total
  recentVideos.value = data.items
}

async function fetchHealthTrends(): Promise<void> {
  const headers = await authHeader()
  const res = await fetch(`${API_BASE}/api/health/trends`, { headers })
  if (!res.ok) throw new Error(`/health/trends failed: ${res.status}`)
  const data = await res.json() as HealthTrends
  // Latest non-null value from resting_hr series
  const series = data.series?.resting_hr ?? []
  for (let i = series.length - 1; i >= 0; i--) {
    if (series[i] !== null && series[i] !== undefined) {
      restingHr.value = series[i] as number
      break
    }
  }
}

onMounted(async () => {
  // All six fetches are independent — use allSettled so one failure can't
  // prevent the rest of the dashboard from rendering.
  await Promise.allSettled([
    fetchMe(),
    fetchMemoryStats(),
    fetchRecentMemories(),
    fetchPosts(),
    fetchVideos(),
    fetchHealthTrends(),
  ])
  loading.value = false
})
</script>

<template>
  <div class="dash">
    <!-- -------------------------------------------------------------------- -->
    <!-- Greeting row                                                           -->
    <!-- -------------------------------------------------------------------- -->
    <div class="dash__greeting">
      <h1 class="dash__greeting-text">
        {{ greeting }}<template v-if="me">, {{ me.display_name }}</template>.
      </h1>
      <span class="t-mono dash__stamp">{{ dateStamp }}</span>
    </div>

    <!-- -------------------------------------------------------------------- -->
    <!-- Onboarding banner                                                      -->
    <!-- -------------------------------------------------------------------- -->
    <PiCard
      v-if="me && me.onboarding_completed === false && !bannerDismissed"
      class="dash__banner"
    >
      <span class="dash__banner-icon">
        <PIIcon name="spark" :size="20" />
      </span>
      <div class="dash__banner-body">
        <div class="dash__banner-title">Your setup is incomplete.</div>
        <div class="dash__banner-sub t-secondary">
          Add your introduction to unlock personalized content.
        </div>
      </div>
      <PiButton variant="secondary" size="compact" @click="router.push('/onboarding')">
        Continue setup
      </PiButton>
      <IconButton icon="close" label="Dismiss" @click="dismissBanner" />
    </PiCard>

    <!-- -------------------------------------------------------------------- -->
    <!-- Your Brain card                                                        -->
    <!-- -------------------------------------------------------------------- -->
    <PiCard class="dash__brain">
      <div class="dash__brain-top">
        <BrainPulse :size="32" aria-hidden="true" />
        <div class="dash__brain-info">
          <div class="dash__brain-title">Your Brain</div>
          <div class="dash__brain-sub t-secondary">
            <span class="t-mono">{{ memStats.total }}</span>
            {{ memStats.total === 1 ? ' memory' : ' memories' }}
            · {{ brainSubline }}
          </div>
        </div>
        <PiButton variant="primary" icon="plus" @click="router.push('/memory')">
          Add to your brain
        </PiButton>
      </div>
      <ProgressBar
        :label="`Brain health: ${healthBand.label}`"
        :value="healthScore"
        :variant="healthBand.variant"
      />
    </PiCard>

    <!-- -------------------------------------------------------------------- -->
    <!-- Module cards                                                           -->
    <!-- -------------------------------------------------------------------- -->
    <div class="dash__modules">
      <!-- Pulse -->
      <PiCard
        :hover="true"
        class="dash__module"
        @click="router.push('/pulse')"
      >
        <span class="dash__module-name">
          <PIIcon name="pulse" :size="16" />
          Pulse
        </span>
        <template v-if="!pulseEmpty">
          <div class="dash__module-stat">{{ postTotal }}</div>
          <div class="dash__module-sub t-secondary">posts ready to read</div>
        </template>
        <template v-else>
          <div class="dash__module-empty t-tertiary">No data yet</div>
        </template>
        <PiButton
          variant="ghost"
          size="compact"
          icon-right="arrowRight"
          class="dash__module-cta"
          @click.stop="router.push('/pulse')"
        >
          {{ pulseEmpty ? 'Get started' : 'Open' }}
        </PiButton>
      </PiCard>

      <!-- Signal -->
      <PiCard
        :hover="true"
        class="dash__module"
        @click="router.push('/signal')"
      >
        <span class="dash__module-name">
          <PIIcon name="signal" :size="16" />
          Signal
        </span>
        <template v-if="!signalEmpty">
          <div class="dash__module-stat">{{ videoTotal }}</div>
          <div class="dash__module-sub t-secondary">videos ready to watch</div>
        </template>
        <template v-else>
          <div class="dash__module-empty t-tertiary">No data yet</div>
        </template>
        <PiButton
          variant="ghost"
          size="compact"
          icon-right="arrowRight"
          class="dash__module-cta"
          @click.stop="router.push('/signal')"
        >
          {{ signalEmpty ? 'Get started' : 'Watch' }}
        </PiButton>
      </PiCard>

      <!-- Health -->
      <PiCard
        :hover="true"
        class="dash__module"
        @click="router.push('/health')"
      >
        <span class="dash__module-name">
          <PIIcon name="health" :size="16" />
          Health
        </span>
        <template v-if="!healthEmpty">
          <div class="dash__module-stat">{{ restingHr }} bpm</div>
          <div class="dash__module-sub t-secondary">synced</div>
        </template>
        <template v-else>
          <div class="dash__module-empty t-tertiary">No data yet</div>
        </template>
        <PiButton
          variant="ghost"
          size="compact"
          icon-right="arrowRight"
          class="dash__module-cta"
          @click.stop="router.push('/health')"
        >
          {{ healthEmpty ? 'Get started' : 'View' }}
        </PiButton>
      </PiCard>
    </div>

    <!-- -------------------------------------------------------------------- -->
    <!-- Recent activity                                                        -->
    <!-- -------------------------------------------------------------------- -->
    <div class="dash__activity">
      <div class="dash__activity-title">Recent activity</div>

      <PiCard v-if="activityEmpty">
        <EmptyState
          icon="pulse"
          title="Nothing here yet"
          desc="Add your first memory to start generating activity across your modules."
        >
          <template #action>
            <PiButton
              variant="secondary"
              icon-right="arrowRight"
              @click="router.push('/memory')"
            >
              Add your first memory
            </PiButton>
          </template>
        </EmptyState>
      </PiCard>

      <div v-else-if="!loading" class="dash__activity-list">
        <div
          v-for="(item, i) in activityFeed"
          :key="i"
          class="dash__activity-row"
          :class="{ 'dash__activity-row--last': i === activityFeed.length - 1 }"
        >
          <span class="dash__activity-icon t-tertiary">
            <PIIcon :name="item.icon" :size="16" />
          </span>
          <span class="t-mono dash__activity-time">{{ item.time }}</span>
          <span class="dash__activity-text">{{ item.text }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── Wrapper ─────────────────────────────────────────────── */
.dash {
  max-width: var(--content-dashboard);
  margin: 0 auto;
  padding-bottom: var(--space-12);
}

/* ── Greeting ────────────────────────────────────────────── */
.dash__greeting {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
  flex-wrap: wrap;
}

.dash__greeting-text {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--text-primary);
}

.dash__stamp {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  white-space: nowrap;
}

/* ── Onboarding banner ───────────────────────────────────── */
.dash__banner {
  border-left: 3px solid var(--brain-amber);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
  flex-wrap: wrap;
}

.dash__banner-icon {
  color: var(--brain-amber);
  display: flex;
  flex-shrink: 0;
}

.dash__banner-body {
  flex: 1;
  min-width: 0;
}

.dash__banner-title {
  font-family: var(--font-display);
  font-weight: 500;
  margin-bottom: 2px;
  color: var(--text-primary);
}

.dash__banner-sub {
  font-size: var(--text-sm);
}

/* ── Brain card ──────────────────────────────────────────── */
.dash__brain {
  margin-bottom: var(--space-6);
}

.dash__brain-top {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.dash__brain-info {
  flex: 1;
  min-width: 0;
}

.dash__brain-title {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-md);
  color: var(--text-primary);
  margin-bottom: 2px;
}

.dash__brain-sub {
  font-size: var(--text-sm);
}

/* ── Module grid ─────────────────────────────────────────── */
.dash__modules {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-8);
}

.dash__module {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 150px;
  cursor: pointer;
}

.dash__module-name {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-family: var(--font-display);
  font-weight: 500;
  font-size: var(--text-sm);
}

.dash__module-stat {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 24px;
  color: var(--text-primary);
  flex: 1;
  display: flex;
  align-items: center;
}

.dash__module-sub {
  font-size: var(--text-sm);
  margin-top: -6px;
}

.dash__module-empty {
  flex: 1;
  display: flex;
  align-items: center;
  font-size: var(--text-sm);
}

.dash__module-cta {
  align-self: flex-start;
}

/* ── Recent activity ─────────────────────────────────────── */
.dash__activity-title {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-md);
  color: var(--text-primary);
  margin-bottom: var(--space-4);
}

.dash__activity-list {
  display: flex;
  flex-direction: column;
}

.dash__activity-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border-subtle);
}

.dash__activity-row--last {
  border-bottom: none;
}

.dash__activity-icon {
  display: flex;
  flex-shrink: 0;
}

.dash__activity-time {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  width: 72px;
  flex-shrink: 0;
}

.dash__activity-text {
  font-size: var(--text-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Reduced-motion: suppress cursor pulse on brain-pulse if user prefers */
@media (prefers-reduced-motion: reduce) {
  .dash__brain-top .brain-pulse .bp-orbit {
    animation-duration: 0s;
  }
}
</style>
