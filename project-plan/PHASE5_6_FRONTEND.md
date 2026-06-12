# PHASE 5 + 6 — Frontend: PULSE Feed + SIGNAL Player
## Agent: OpenAI Codex
## Depends on: Phase 1 (API routes must exist), Phases 3/4 (data helps but mocks are fine)

---

## Design System Reference

Existing dashboard uses the **"Soviet Bureaucratic"** aesthetic:
- Background: `#0a0a0f` (near-black)
- Surface: `#12121a`
- Accent: `#4a6fa5` (cold steel blue)
- Gold: `#c9a84c` (muted gold)
- Text: `#e8e8e8`
- Font: `JetBrains Mono` or `IBM Plex Mono` (monospace everywhere)
- Zero rounded corners — all `border-radius: 0`
- Borders: `1px solid #2a2a3e`
- No shadows — use borders instead

**Do not deviate from this aesthetic. Everything must feel like a classified government media portal.**

---

# PHASE 5 — PULSE Social Feed

## File: `frontend/src/views/PulseFeed.vue`

### Layout

```
┌──────────────────────────────────────────────────┐
│  PULSE // AI CONTENT FEED            [▼ FILTERS] │
│  ──────────────────────────────────────────────  │
│  SORT: [LATEST] [TOP] [UNRATED]                  │
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │  PostCard × N (scrollable list)            │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  [LOAD MORE]                                     │
└──────────────────────────────────────────────────┘
```

### API Integration
```typescript
GET /api/content/posts?page=1&limit=10&sort=created_at_desc
// Response: { posts: PostOut[], total: int, page: int }
```

---

## Component: `frontend/src/components/PostCard.vue`

### Props
```typescript
interface Post {
  id: string
  creator: { name: string; avatar_url: string; slug: string; score: number }
  topic: { name: string }
  body: string
  image_url: string | null
  tone: 'critical' | 'supportive' | 'satirical' | 'informative'
  created_at: string
  score: number
}
```

### Visual Layout
```
┌─────────────────────────────────────────────────┐
│ [AVATAR 40px] MAKSIM VOLKOV          [SCORE 0.8]│
│               @maksim-volkov · 2h ago            │
│               ████ SATIRICAL                     │
├─────────────────────────────────────────────────┤
│  TOPIC: Moving to Switzerland →                  │
├─────────────────────────────────────────────────┤
│  [IMAGE if present — full width, max-h 300px]   │
├─────────────────────────────────────────────────┤
│  Post body text here...                          │
│                                                  │
├─────────────────────────────────────────────────┤
│  [▲ LIKE]  [▼ DISLIKE]  [→ SHARE LINK]          │
└─────────────────────────────────────────────────┘
```

### Tone Badge Colors
| Tone | Border color | Label |
|------|-------------|-------|
| `critical` | `#c94a4a` | ██ CRITICAL |
| `supportive` | `#4ac94a` | ██ SUPPORTIVE |
| `satirical` | `#c9a84c` | ██ SATIRICAL |
| `informative` | `#4a6fa5` | ██ INTEL |

### Creator Score Display
Show `score` as a small `[0.82]` badge next to name.
Color: green if > 0.6, gold if 0.4–0.6, red if < 0.4.

### Interaction Handling
```typescript
// On like click:
await fetch('/api/content/interactions', {
  method: 'POST',
  body: JSON.stringify({
    content_id: post.id,
    content_type: 'post',
    action: 'like'
  })
})
// Optimistically update UI: highlight like button, update local score display

// On dislike click: same with action: 'dislike'
// Visual: show a small "FEEDBACK LOGGED" toast (1.5s, bottom right)
```

---

# PHASE 6 — SIGNAL Video Platform

## File: `frontend/src/views/SignalPlayer.vue`

### Layout (Two-panel: list left, player right on desktop; stacked on mobile)

```
┌──────────────────┬───────────────────────────────┐
│  SIGNAL          │                               │
│  VIDEO LIBRARY   │   [VIDEO PLAYER]              │
│  ─────────────── │   ─────────────────────────── │
│  [VideoCard]     │   title                       │
│  [VideoCard]     │   creator badge + score       │
│  [VideoCard]     │   topic tag                   │
│  [VideoCard]     │   description (2 sentences)   │
│  ...             │   ─────────────────────────── │
│                  │   [▲ LIKE] [▼ DISLIKE]        │
└──────────────────┴───────────────────────────────┘
```

## Component: `frontend/src/components/VideoCard.vue`

### Props
```typescript
interface Video {
  id: string
  creator: { name: string; avatar_url: string; score: number }
  topic: { name: string }
  title: string
  description: string
  thumbnail_url: string
  duration_seconds: number
  status: 'pending' | 'processing' | 'ready' | 'failed'
  score: number
  created_at: string
}
```

### Visual
```
┌────────────────────────────────┐
│  [THUMBNAIL — 16:9 aspect]    │
│  ┌─────────────────────────┐  │
│  │ PROCESSING...  ████░░░░ │  │  ← shown if status != 'ready'
│  └─────────────────────────┘  │
├────────────────────────────────┤
│  VIDEO TITLE (truncate 2 lines)│
│  MAKSIM VOLKOV · 2:34          │
│  [SCORE 0.7]                   │
└────────────────────────────────┘
```

For `status: 'processing'`: show animated progress bar with text "RENDERING..."
For `status: 'failed'`: show red border + "GENERATION FAILED" overlay.

## Video Player Section

Use native HTML5 `<video>` element:
```html
<video
  ref="videoEl"
  :src="selectedVideo.video_url"
  controls
  preload="metadata"
  @timeupdate="onTimeUpdate"
  @ended="onVideoEnded"
  @play="onPlay"
/>
```

### Watch Tracking
```typescript
// Track watch percentage
const watchPct = computed(() => currentTime.value / duration.value)

// On ended (100% watched):
await logInteraction(video.id, 'watch_complete', 1.0)

// On component unmount or video switch, if watchPct > 0.1 and < 1.0:
await logInteraction(video.id, 'watch_partial', watchPct.value)

// If unmount with watchPct < 0.1: log 'skip'
```

This is the core RL signal source — watch percentage is more honest than clicks.

---

## Shared Component: `frontend/src/components/CreatorBadge.vue`

Used in both PostCard and VideoCard.

```
[AVATAR 32px] NAME  [●] active / [○] score < 0.3
```

- Avatar: if null, generate a geometric avatar from creator slug (SVG, deterministic)
- On click: future feature (creator profile page) — for now just show a tooltip with bio

---

## Navigation Integration

Add to existing sidebar nav:
```typescript
{ path: '/pulse', label: 'PULSE', icon: 'broadcast' }
{ path: '/signal', label: 'SIGNAL', icon: 'film' }
```

---

## State Management

Use Vue 3 `composables`:

```typescript
// composables/useContent.ts
export function usePulseFeed() {
  const posts = ref<Post[]>([])
  const page = ref(1)
  const loading = ref(false)
  async function loadMore() { ... }
  return { posts, loading, loadMore }
}

export function useSignalLibrary() {
  const videos = ref<Video[]>([])
  const selected = ref<Video | null>(null)
  async function load() { ... }
  function select(v: Video) { selected.value = v }
  return { videos, selected, load, select }
}
```

No Vuex/Pinia needed for this module — composables are sufficient.

---

## Loading States

All loading states use the Soviet aesthetic:
- Skeleton: `background: repeating-linear-gradient(90deg, #12121a 0px, #1e1e2e 40px, #12121a 80px)`
- Animation: `animation: scan 1.5s infinite` (horizontal scan line)
- Text placeholders: `████████ ███████` (using Unicode blocks, not CSS)

---

## Completion Criteria
- [ ] PULSE feed shows posts with correct tone badges
- [ ] Like/dislike sends interaction to API and updates UI
- [ ] SIGNAL library shows video cards with thumbnails
- [ ] Clicking a video loads it in the player
- [ ] Watch percentage logged on video switch/unmount
- [ ] Processing/failed status displayed correctly in VideoCard
- [ ] No rounded corners anywhere
- [ ] Monospace font used throughout
- [ ] Mobile-responsive (single column)
