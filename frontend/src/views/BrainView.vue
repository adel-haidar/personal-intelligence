<script setup lang="ts">
/**
 * BrainView — "Your Brain" memory page.
 * Route: /memory
 *
 * API calls:
 *   GET  /api/memory/stats         → initial stats (total, last_updated)
 *   GET  /api/memory?page=&page_size=&q=  → paginated list with server-side search
 *   POST /api/memory/text          → create a new memory (title, content, tags)
 *   DELETE /api/memory/{id}        → via deleteMemory() from useMemories
 *   POST /api/file                 → multipart file upload (reuses fetch directly)
 *
 * Brain-impact heuristic (documented):
 *   Given total = number of saved memories:
 *     Pulse     = min(100, total * 4)      — scales fast; feed personalises quickly
 *     Signal    = min(100, total * 3)      — slightly slower; needs richer context
 *     Health    = min(60,  total * 2)      — capped at 60; needs a device for >60
 *     Finances  = min(40,  total * 1.5)    — capped at 40; needs a statement for >40
 *   All values are floored and shown as integers.
 *
 * Source derivation (tags → PI_SOURCE_META key):
 *   tags includes 'file-upload'  → 'file'   (icon: attach, label: From file)
 *   tags includes 'device'       → 'device' (icon: watch,  label: Device)
 *   tags includes 'ai-summary'   → 'ai'     (icon: spark,  label: AI summary)
 *   else                         → 'manual' (icon: edit,   label: Written)
 */

import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiTextarea from '../components/ui/PiTextarea.vue'
import PiButton from '../components/ui/PiButton.vue'
import PiInput from '../components/ui/PiInput.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import Tag from '../components/ui/Tag.vue'
import PIIcon from '../components/ui/PIIcon.vue'
import IconButton from '../components/ui/IconButton.vue'
import { useToast } from '../components/ui/useToast'
import { requireAuth } from '../composables/useAuth'
import { deleteMemory } from '../composables/useMemories'
import { useBrainOrganiser } from '../composables/useBrainOrganiser'
import { API_BASE } from '../config/env'
import type { Memory, MemoryListResponse, MemoryStats, CreateMemoryPayload } from '../types/memory'

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
const toast = useToast()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const stats = ref<MemoryStats>({ total: 0, last_updated: null })
const memories = ref<Memory[]>([])
const page = ref(1)
const pages = ref(1)
const query = ref('')
const draft = ref('')
const saving = ref(false)
const uploading = ref(false)
const loadingMore = ref(false)
const initialLoading = ref(true)
const justAddedId = ref<string | null>(null)
const hoverId = ref<string | null>(null)
const viewing = ref<Memory | null>(null)  // memory shown in the "View full" modal
const fileInputRef = ref<HTMLInputElement | null>(null)
const sentinelRef = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null
let debounceTimer: ReturnType<typeof setTimeout> | null = null

// ---------------------------------------------------------------------------
// Source meta — mirrors PI_SOURCE_META from the design reference
// ---------------------------------------------------------------------------
const SOURCE_META: Record<string, { icon: string; label: string }> = {
  manual: { icon: 'edit',   label: 'Written' },
  file:   { icon: 'attach', label: 'From file' },
  device: { icon: 'watch',  label: 'Device' },
  ai:     { icon: 'spark',  label: 'AI summary' },
}

function deriveSource(tags: string[]): keyof typeof SOURCE_META {
  if (tags.includes('file-upload')) return 'file'
  if (tags.includes('device'))      return 'device'
  if (tags.includes('ai-summary'))  return 'ai'
  return 'manual'
}

// ---------------------------------------------------------------------------
// Brain-impact heuristic
// ---------------------------------------------------------------------------
const brainImpact = computed(() => {
  const t = stats.value.total
  return {
    pulse:    Math.min(100, Math.floor(t * 4)),
    signal:   Math.min(100, Math.floor(t * 3)),
    health:   Math.min(60,  Math.floor(t * 2)),
    finances: Math.min(40,  Math.floor(t * 1.5)),
  }
})

// ---------------------------------------------------------------------------
// Date formatting
// ---------------------------------------------------------------------------
function formatDate(iso: string): string {
  try {
    return iso.slice(0, 10) // YYYY-MM-DD
  } catch {
    return iso
  }
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function fetchStats(): Promise<void> {
  const token = await requireAuth()
  const res = await fetch(`${API_BASE}/api/memory/stats`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Stats failed: ${res.status}`)
  stats.value = await res.json() as MemoryStats
}

async function fetchMemories(reset = false): Promise<void> {
  if (reset) {
    page.value = 1
    memories.value = []
  }
  if (loadingMore.value) return

  loadingMore.value = true
  try {
    const token = await requireAuth()
    const params = new URLSearchParams({
      page:      String(page.value),
      page_size: '20',
    })
    if (query.value.trim()) params.set('q', query.value.trim())

    const res = await fetch(`${API_BASE}/api/memory?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(`Memories failed: ${res.status}`)
    const data = await res.json() as MemoryListResponse

    if (reset) {
      memories.value = data.items
    } else {
      memories.value.push(...data.items)
    }
    pages.value = data.pages
  } finally {
    loadingMore.value = false
  }
}

// ---------------------------------------------------------------------------
// Initial load
// ---------------------------------------------------------------------------
// Brain Organiser: live "sleeping" state for the banner (shared 10s poller).
const { status: organiserStatus, running: organiserRunning, ensurePolling: ensureOrganiserPolling } = useBrainOrganiser()

onMounted(async () => {
  ensureOrganiserPolling()
  try {
    await Promise.all([fetchStats(), fetchMemories(true)])
  } catch (err) {
    toast((err as Error).message ?? 'Failed to load memories', 'error')
  } finally {
    initialLoading.value = false
  }
  setupObserver()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  if (debounceTimer) clearTimeout(debounceTimer)
})

// ---------------------------------------------------------------------------
// Search debounce
// ---------------------------------------------------------------------------
watch(query, () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(async () => {
    try {
      await fetchMemories(true)
    } catch (err) {
      toast((err as Error).message ?? 'Search failed', 'error')
    }
  }, 300)
})

// ---------------------------------------------------------------------------
// Infinite scroll sentinel
// ---------------------------------------------------------------------------
function setupObserver(): void {
  observer?.disconnect()
  if (!sentinelRef.value) return
  observer = new IntersectionObserver(async (entries) => {
    if (!entries[0]?.isIntersecting) return
    if (page.value >= pages.value) return
    if (loadingMore.value) return
    page.value += 1
    try {
      await fetchMemories(false)
    } catch (err) {
      toast((err as Error).message ?? 'Failed to load more', 'error')
    }
  }, { threshold: 0.1 })
  observer.observe(sentinelRef.value)
}

watch(sentinelRef, (el) => {
  if (el) setupObserver()
})

// ---------------------------------------------------------------------------
// Save memory
// ---------------------------------------------------------------------------
async function saveMemory(): Promise<void> {
  const content = draft.value.trim()
  if (!content || saving.value) return

  saving.value = true
  try {
    const title = content.length <= 60
      ? content
      : content.slice(0, 57) + '…'
    const payload: CreateMemoryPayload = { title, content, tags: ['note'] }

    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/memory/text`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(`Save failed: ${res.status}`)
    const { memory_id } = await res.json() as { memory_id: string }

    // Optimistic prepend
    const optimistic: Memory = {
      memory_id,
      title,
      content,
      tags: ['note'],
      created_at: new Date().toISOString(),
      updated_at: null,
    }
    memories.value.unshift(optimistic)
    justAddedId.value = memory_id
    setTimeout(() => { justAddedId.value = null }, 800)

    draft.value = ''
    toast('Memory saved to your brain', 'success')

    // Refresh stats
    await fetchStats()
  } catch (err) {
    toast((err as Error).message ?? 'Failed to save memory', 'error')
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------------------
// File attach
// ---------------------------------------------------------------------------
function triggerFileInput(): void {
  fileInputRef.value?.click()
}

async function handleFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (files.length === 0) return
  input.value = '' // reset so same file(s) can be re-selected

  uploading.value = true
  try {
    const token = await requireAuth()
    const form = new FormData()
    for (const file of files) form.append('files', file)

    const res = await fetch(`${API_BASE}/api/file`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    })
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`)

    toast(
      files.length === 1
        ? 'File attached to your brain'
        : `${files.length} files attached to your brain`,
      'success',
    )
    // Refresh both stats and list to show new file-backed memory
    await Promise.all([fetchStats(), fetchMemories(true)])
    await nextTick()
    setupObserver()
  } catch (err) {
    toast((err as Error).message ?? 'Upload failed', 'error')
  } finally {
    uploading.value = false
  }
}

// ---------------------------------------------------------------------------
// Delete memory
// ---------------------------------------------------------------------------
async function handleDelete(id: string): Promise<void> {
  try {
    await deleteMemory(id)
    memories.value = memories.value.filter(m => m.memory_id !== id)
    toast('Memory deleted', 'success')
    await fetchStats()
  } catch (err) {
    toast((err as Error).message ?? 'Delete failed', 'error')
  }
}

// ---------------------------------------------------------------------------
// Derived
// ---------------------------------------------------------------------------
const isEmpty = computed(() => !initialLoading.value && stats.value.total === 0 && memories.value.length === 0)
const hasMore = computed(() => page.value < pages.value)
</script>

<template>
  <div class="brain-view">
    <!-- ------------------------------------------------------------------ -->
    <!-- Hero                                                                 -->
    <!-- ------------------------------------------------------------------ -->
    <div class="brain-hero">
      <BrainPulse :size="48" :slow="true" aria-hidden="true" />
      <h1 class="brain-hero__title">Your Brain</h1>
      <div class="t-mono brain-hero__count">
        {{ stats.total }} {{ stats.total === 1 ? 'memory' : 'memories' }}
      </div>
      <p class="t-serif brain-hero__sub">
        Everything you share here makes the platform smarter.
      </p>
    </div>

    <!-- ------------------------------------------------------------------ -->
    <!-- Brain sleeping banner (only while the organiser runs)                -->
    <!-- ------------------------------------------------------------------ -->
    <div v-if="organiserRunning" class="brain-sleep" role="status">
      <div class="brain-sleep__head">
        <span class="brain-sleep__emoji" aria-hidden="true">💤</span>
        <span class="brain-sleep__title">Your brain is sleeping</span>
      </div>
      <p class="brain-sleep__body">
        Duplicates are being removed and related memories are being merged.
        New memories can still be added.
      </p>
      <div class="brain-sleep__progress">
        <span class="t-mono brain-sleep__stage">
          Stage {{ organiserStatus?.stage ?? 1 }} of 3 — {{ organiserStatus?.stage_label ?? 'Organising' }}
        </span>
        <ProgressBar :value="organiserStatus?.progress_pct ?? 0" variant="amber" :show-pct="true" />
      </div>
    </div>

    <!-- ------------------------------------------------------------------ -->
    <!-- Add memory card                                                      -->
    <!-- ------------------------------------------------------------------ -->
    <PiCard class="brain-add">
      <div class="brain-add__label">What's on your mind?</div>
      <PiTextarea
        v-model="draft"
        :serif="true"
        placeholder="Write about your work, your goals, what you're going through. No format. No rules. Any language."
        style="min-height: 140px"
      />
      <div class="brain-add__footer">
        <PiButton
          variant="ghost"
          size="compact"
          icon="attach"
          :loading="uploading"
          @click="triggerFileInput"
        >
          Attach file
        </PiButton>
        <input
          ref="fileInputRef"
          type="file"
          multiple
          aria-hidden="true"
          tabindex="-1"
          style="display: none"
          @change="handleFileChange"
        />
        <div class="brain-add__right">
          <span class="pi-counter">{{ draft.length }} chars</span>
          <PiButton
            variant="primary"
            icon-right="arrowRight"
            :disabled="!draft.trim() || saving"
            :loading="saving"
            @click="saveMemory"
          >
            Save
          </PiButton>
        </div>
      </div>
    </PiCard>

    <!-- ------------------------------------------------------------------ -->
    <!-- Empty state                                                          -->
    <!-- ------------------------------------------------------------------ -->
    <div v-if="isEmpty" class="brain-empty t-serif">
      <p class="brain-empty__lead">This is where your brain lives.</p>
      <p>Tell it who you are. Write about your work, your goals, what you find interesting, what you're going through. There's no format. No rules. Any language.</p>
      <p>The more you write, the more Private Internet becomes specifically yours.</p>
    </div>

    <!-- ------------------------------------------------------------------ -->
    <!-- Populated state                                                      -->
    <!-- ------------------------------------------------------------------ -->
    <template v-else-if="!initialLoading">
      <!-- Brain impact panel -->
      <PiCard class="brain-impact">
        <div class="brain-impact__title">Your brain powers</div>
        <div class="brain-impact__bars">
          <ProgressBar label="Pulse feed"     :value="brainImpact.pulse"    variant="amber" />
          <ProgressBar label="Signal videos"  :value="brainImpact.signal"   variant="amber" />
          <ProgressBar label="Health"         :value="brainImpact.health"   variant="amber" note="Connect a device to improve" />
          <ProgressBar label="Finances"       :value="brainImpact.finances" variant="amber" note="Upload a statement to improve" />
        </div>
      </PiCard>

      <!-- Search -->
      <div class="brain-search">
        <PiInput
          v-model="query"
          icon="search"
          placeholder="Search your memories"
        />
      </div>

      <!-- Memory list -->
      <div class="brain-list">
        <PiCard
          v-for="m in memories"
          :key="m.memory_id"
          :hover="true"
          class="brain-card"
          :style="m.memory_id === justAddedId ? { animation: 'pi-slide-down .2s var(--ease)' } : undefined"
          @mouseenter="hoverId = m.memory_id"
          @mouseleave="hoverId = null"
        >
          <!-- Card header: source chip + date -->
          <div class="brain-card__head">
            <span class="brain-card__source">
              <PIIcon :name="SOURCE_META[deriveSource(m.tags)].icon" :size="14" />
              {{ SOURCE_META[deriveSource(m.tags)].label }}
            </span>
            <span class="t-mono brain-card__date">{{ formatDate(m.created_at) }}</span>
          </div>

          <!-- Body (Lora, truncated to 200 chars) -->
          <p
            class="t-serif brain-card__body"
            :style="deriveSource(m.tags) === 'file' ? { fontStyle: 'italic' } : undefined"
          >
            {{ m.content.length > 200 ? m.content.slice(0, 200) + '…' : m.content }}
          </p>

          <!-- Footer: tags + hover actions -->
          <div class="brain-card__footer">
            <div class="brain-card__tags">
              <Tag v-for="t in m.tags" :key="t">{{ t }}</Tag>
            </div>
            <div
              class="brain-card__actions"
              :style="{ opacity: hoverId === m.memory_id ? 1 : 0 }"
            >
              <PiButton variant="ghost" size="compact" @click.stop="viewing = m">View full</PiButton>
              <PiButton
                variant="ghost"
                size="compact"
                @click.stop="handleDelete(m.memory_id)"
              >
                Delete
              </PiButton>
            </div>
          </div>
        </PiCard>

        <!-- Infinite scroll sentinel -->
        <div
          ref="sentinelRef"
          class="brain-sentinel t-mono"
          :style="{ visibility: hasMore ? 'visible' : 'hidden' }"
          aria-hidden="true"
        >
          Loading older memories…
        </div>
      </div>
    </template>

    <!-- ------------------------------------------------------------------ -->
    <!-- View full modal                                                      -->
    <!-- ------------------------------------------------------------------ -->
    <div v-if="viewing" class="brain-modal" @click.self="viewing = null">
      <div class="brain-modal__panel" role="dialog" aria-modal="true">
        <div class="brain-modal__head">
          <span class="brain-modal__source">
            <PIIcon :name="SOURCE_META[deriveSource(viewing.tags)].icon" :size="14" />
            {{ SOURCE_META[deriveSource(viewing.tags)].label }}
          </span>
          <span class="t-mono brain-modal__date">{{ formatDate(viewing.created_at) }}</span>
          <IconButton icon="close" label="Close" @click="viewing = null" />
        </div>
        <h2 v-if="viewing.title" class="brain-modal__title">{{ viewing.title }}</h2>
        <p class="t-serif brain-modal__body">{{ viewing.content }}</p>
        <div v-if="viewing.tags.length" class="brain-modal__tags">
          <Tag v-for="t in viewing.tags" :key="t">{{ t }}</Tag>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Brain sleeping banner */
.brain-sleep {
  background: var(--brain-amber-surface);
  border-left: 3px solid var(--brain-amber);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  margin-bottom: var(--space-5);
}
.brain-sleep__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.brain-sleep__emoji { font-size: 18px; line-height: 1; }
.brain-sleep__title {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-md);
  color: var(--text-primary);
}
.brain-sleep__body {
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin: 0 0 var(--space-4);
  max-width: 60ch;
}
.brain-sleep__stage {
  display: block;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
}

/* Container */
.brain-view {
  max-width: var(--content-reading);
  margin: 0 auto;
  padding-bottom: var(--space-12);
}

/* Hero */
.brain-hero {
  text-align: center;
  padding-top: var(--space-6);
  margin-bottom: var(--space-8);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

.brain-hero .brain-pulse {
  margin-bottom: var(--space-4);
}

.brain-hero__title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
  margin-top: var(--space-4);
}

.brain-hero__count {
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.brain-hero__sub {
  color: var(--text-secondary);
  font-size: var(--text-md);
  margin-top: var(--space-3);
  font-style: italic;
  line-height: 1.6;
}

/* Add card */
.brain-add {
  margin-bottom: var(--space-6);
}

.brain-add__label {
  font-family: var(--font-display);
  font-weight: 500;
  margin-bottom: var(--space-3);
  color: var(--text-primary);
}

.brain-add__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-3);
  gap: var(--space-3);
  flex-wrap: wrap;
}

.brain-add__right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

/* Empty state */
.brain-empty {
  text-align: center;
  padding: var(--space-12) var(--space-6);
  color: var(--text-secondary);
  font-size: 18px;
  line-height: 1.8;
  max-width: 560px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.brain-empty__lead {
  color: var(--text-primary);
}

/* Impact panel */
.brain-impact {
  margin-bottom: var(--space-6);
}

.brain-impact__title {
  font-family: var(--font-display);
  font-weight: 500;
  margin-bottom: var(--space-4);
  color: var(--text-primary);
}

.brain-impact__bars {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Search */
.brain-search {
  margin-bottom: var(--space-4);
}

/* Memory list */
.brain-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* Memory card */
.brain-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.brain-card__source {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.brain-card__date {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.brain-card__body {
  color: var(--text-primary);
  font-size: var(--text-base);
  line-height: 1.7;
  /* Long unbroken strings (e.g. pasted JSON) must wrap, not spill the card. */
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: pre-wrap;
}

/* View full modal */
.brain-modal {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background: color-mix(in srgb, var(--background-page) 75%, transparent);
  animation: pi-fade-in 0.15s var(--ease);
}

.brain-modal__panel {
  background: var(--background-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-menu);
  width: 100%;
  max-width: 640px;
  max-height: 80vh;
  overflow-y: auto;
  padding: var(--space-6);
}

.brain-modal__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.brain-modal__source {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.brain-modal__date {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-left: auto;
}

.brain-modal__title {
  font-family: var(--font-display);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-3);
  overflow-wrap: anywhere;
}

.brain-modal__body {
  color: var(--text-primary);
  font-size: var(--text-base);
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  margin-bottom: var(--space-4);
}

.brain-modal__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.brain-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-3);
  min-height: 24px;
  gap: var(--space-2);
}

.brain-card__tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.brain-card__actions {
  display: flex;
  gap: var(--space-1);
  transition: opacity .12s var(--ease);
  flex-shrink: 0;
}

/* Sentinel */
.brain-sentinel {
  text-align: center;
  padding: var(--space-4);
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
</style>
