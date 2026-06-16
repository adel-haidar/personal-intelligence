import { ref } from 'vue'
import { requireAuth } from './useAuth'
import { API_BASE } from '../config/env'

// ── Types (match the real API: flat creator_* fields from the SQL join) ────

export type Tone = 'critical' | 'supportive' | 'satirical' | 'informative'

export interface Post {
  id: string
  creator_id: string
  topic_id: string
  body: string
  image_url: string | null
  image_prompt: string | null
  tone: Tone | null
  score: number
  total_interactions: number
  created_at: string
  creator_name: string
  creator_avatar: string | null
  // Present once the backend join exposes them; badge degrades gracefully
  creator_slug?: string
  creator_score?: number
  creator_bio?: string
}

export interface Topic {
  id: string
  name: string
  slug: string
  source: string
  weight: number
  used_count: number
  last_used_at: string | null
  created_at: string
}

export type PostSort = 'latest' | 'top' | 'unrated'

export type VideoStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface Video {
  id: string
  creator_id: string
  topic_id: string
  title: string
  description: string | null
  video_url: string | null
  thumbnail_url: string | null
  duration_seconds: number | null
  status: VideoStatus
  score: number
  total_interactions: number
  created_at: string
  creator_name: string
  creator_avatar: string | null
}

export interface Creator {
  id: string
  slug: string
  name: string
  avatar_url: string | null
  bio: string | null
  score: number
  is_active: boolean
}

export type InteractionAction =
  | 'like'
  | 'dislike'
  | 'skip'
  | 'watch_complete'
  | 'watch_partial'
  | 'view'

interface Paged<T> {
  items: T[]
  total: number
  page: number
  pages: number
}

// ── Base URL (same convention as useHealth) ────────────────────────────────

const BASE = `${API_BASE}/api/content`

// ── Helpers ────────────────────────────────────────────────────────────────

async function authedGet<T>(path: string): Promise<T> {
  const token = await requireAuth()
  const res = await fetch(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export async function logInteraction(
  contentId: string,
  contentType: 'post' | 'video',
  action: InteractionAction,
  watchPct?: number,
): Promise<void> {
  const token = await requireAuth()
  const res = await fetch(`${BASE}/interactions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      content_id: contentId,
      content_type: contentType,
      action,
      watch_pct: watchPct ?? null,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
}

// ── PULSE feed store (composable, no Pinia) ────────────────────────────────

const PAGE_SIZE = 10

export function usePulseFeed() {
  const posts = ref<Post[]>([])
  const page = ref(0)
  const pages = ref(1)
  const total = ref(0)
  const sort = ref<PostSort>('latest')
  // null = all personas; otherwise scope the feed to one creator server-side.
  const creator = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const hasMore = () => page.value < pages.value

  async function loadMore(): Promise<void> {
    if (loading.value || !hasMore()) return
    loading.value = true
    error.value = null
    try {
      const next = page.value + 1
      const creatorQuery = creator.value ? `&creator_id=${creator.value}` : ''
      const data = await authedGet<Paged<Post>>(
        `/posts?page=${next}&page_size=${PAGE_SIZE}&sort=${sort.value}${creatorQuery}`,
      )
      posts.value = next === 1 ? data.items : [...posts.value, ...data.items]
      page.value = data.page
      pages.value = data.pages
      total.value = data.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  function reset(): void {
    page.value = 0
    pages.value = 1
    posts.value = []
  }

  async function setSort(s: PostSort): Promise<void> {
    if (sort.value === s && page.value > 0) return
    sort.value = s
    reset()
    await loadMore()
  }

  // Select a persona (or null for the full feed) and reload from the server so
  // we see *all* of that creator's posts, not just the ones already paged in.
  async function setCreator(id: string | null): Promise<void> {
    if (creator.value === id && page.value > 0) return
    creator.value = id
    reset()
    await loadMore()
  }

  return { posts, page, pages, total, sort, creator, loading, error, hasMore, loadMore, setSort, setCreator }
}

// ── Creator personas (the "people" of the PULSE feed) ──────────────────────

export function useCreators() {
  const creators = ref<Creator[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      creators.value = await authedGet<Creator[]>('/creators')
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  return { creators, loading, error, load }
}

// ── SIGNAL video library (composable, no Pinia) ────────────────────────────

const VIDEO_PAGE_SIZE = 20

export function useSignalLibrary() {
  const videos = ref<Video[]>([])
  const selected = ref<Video | null>(null)
  const page = ref(0)
  const pages = ref(1)
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // id → name / creator lookups (videos rows carry only creator_name/avatar;
  // topic name and creator slug/bio/score come from separate endpoints)
  const topicNames = ref<Record<string, string>>({})
  const creators = ref<Record<string, Creator>>({})

  const hasMore = () => page.value < pages.value

  async function loadMore(): Promise<void> {
    if (loading.value || !hasMore()) return
    loading.value = true
    error.value = null
    try {
      const next = page.value + 1
      const data = await authedGet<Paged<Video>>(
        `/videos?page=${next}&page_size=${VIDEO_PAGE_SIZE}`,
      )
      videos.value = next === 1 ? data.items : [...videos.value, ...data.items]
      page.value = data.page
      pages.value = data.pages
      total.value = data.total
      // Auto-select the first playable video on initial load
      if (!selected.value) {
        selected.value = data.items.find(v => v.status === 'ready' && v.video_url) ?? null
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
    void loadLookups()
  }

  let lookupsLoaded = false
  async function loadLookups(): Promise<void> {
    if (lookupsLoaded) return
    lookupsLoaded = true
    try {
      const [topicsData, creatorList] = await Promise.all([
        authedGet<Paged<Topic>>('/topics?page_size=200'),
        authedGet<Creator[]>('/creators'),
      ])
      topicNames.value = Object.fromEntries(topicsData.items.map(t => [t.id, t.name]))
      creators.value = Object.fromEntries(creatorList.map(c => [c.id, c]))
    } catch {
      lookupsLoaded = false // lookups are decoration — retry on next loadMore()
    }
  }

  function select(v: Video): void {
    selected.value = v
  }

  return {
    videos, selected, page, pages, total, loading, error,
    topicNames, creators, hasMore, loadMore, select,
  }
}
