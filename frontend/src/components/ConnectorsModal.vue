<script setup lang="ts">
/**
 * ConnectorsModal — "Connect your world"
 *
 * Shows the available connector tiles pulled from GET /api/connectors.
 * States per tile:
 *   !configured           → disabled, "Not available" note
 *   configured+!connected → "Connect" button (opens OAuth popup)
 *   connected             → "Connected", imported_count, last_sync_at, Sync + Disconnect
 *   connected+running     → "Importing…" + BrainPulse instead of Sync button
 */

import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import BrainPulse from './ui/BrainPulse.vue'
import IconButton from './ui/IconButton.vue'
import PiButton from './ui/PiButton.vue'
import { useToast } from './ui/useToast'
import { useConnectors, onConnectSuccess, onConnectError } from '../composables/useConnectors'
import { useFocusTrap } from '../composables/useFocusTrap'
import type { Connector } from '../types/connector'

const emit = defineEmits<{
  close: []
  importFinished: [id: string]
}>()

const toast = useToast()
const {
  connectors,
  loading,
  fetchConnectors,
  connect,
  sync,
  disconnect,
} = useConnectors()

// Track per-connector busy state (connecting / syncing / disconnecting)
const busy = ref<Record<string, boolean>>({})

// ── Relative time helper ──────────────────────────────────────────────────────
function relativeTime(iso: string | null): string {
  if (!iso) return 'Never'
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1)  return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24)   return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

// ── Connector state helpers ───────────────────────────────────────────────────
function isRunning(c: Connector): boolean {
  return c.connected && (c.status === 'running' || c.status === 'importing')
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function handleConnect(c: Connector): Promise<void> {
  busy.value[c.id] = true
  try {
    await connect(c.id, (id) => {
      // onDone: import finished — refresh list + notify parent
      fetchConnectors()
      emit('importFinished', id)
    })
  } catch (err) {
    toast((err as Error).message ?? 'Connection failed', 'error')
  } finally {
    busy.value[c.id] = false
  }
}

async function handleSync(c: Connector): Promise<void> {
  busy.value[c.id] = true
  try {
    await sync(c.id, (id) => {
      fetchConnectors()
      emit('importFinished', id)
    })
    toast(`Sync started for ${c.display_name}`, 'success')
    await fetchConnectors()
  } catch (err) {
    toast((err as Error).message ?? 'Sync failed', 'error')
  } finally {
    busy.value[c.id] = false
  }
}

async function handleDisconnect(c: Connector): Promise<void> {
  busy.value[c.id] = true
  try {
    await disconnect(c.id)
    toast(`${c.display_name} disconnected`, 'success')
    await fetchConnectors()
  } catch (err) {
    toast((err as Error).message ?? 'Disconnect failed', 'error')
  } finally {
    busy.value[c.id] = false
  }
}

// ── OAuth popup message callbacks ─────────────────────────────────────────────
let unsubSuccess: (() => void) | null = null
let unsubError:   (() => void) | null = null

onMounted(async () => {
  await fetchConnectors()

  unsubSuccess = onConnectSuccess((id) => {
    const c = connectors.value.find(x => x.id === id)
    toast(`Connected — importing your ${c?.display_name ?? id} content…`, 'success')
  })

  unsubError = onConnectError((id) => {
    const c = connectors.value.find(x => x.id === id)
    toast(`Could not connect ${c?.display_name ?? id}. Please try again.`, 'error')
  })
})

onBeforeUnmount(() => {
  unsubSuccess?.()
  unsubError?.()
})

// ── Keyboard close + focus trap (modal is mounted only while open) ─────────────
const dialogEl = ref<HTMLElement | null>(null)
useFocusTrap(dialogEl, () => true, { onEscape: () => emit('close') })

// Tile order is driven by the backend (GET /api/connectors).
const orderedConnectors = computed<Connector[]>(() => connectors.value)
</script>

<template>
  <!-- Overlay -->
  <div
    ref="dialogEl"
    class="cm-overlay"
    role="dialog"
    aria-modal="true"
    aria-label="Connect your world"
    @click.self="$emit('close')"
  >
    <div class="cm-panel">
      <!-- Header -->
      <div class="cm-header">
        <div class="cm-header__titles">
          <h2 class="cm-title">Connect your world</h2>
          <p class="cm-subtitle t-serif">
            Bring what you already know into your brain. Read-only, and you can disconnect anytime.
          </p>
        </div>
        <IconButton icon="close" label="Close" class="cm-close" @click="$emit('close')" />
      </div>

      <!-- Loading skeleton -->
      <div v-if="loading" class="cm-grid">
        <div v-for="n in 3" :key="n" class="cm-tile cm-tile--skeleton">
          <div class="pi-skeleton cm-tile__icon-skel" />
          <div class="pi-skeleton cm-tile__name-skel" />
          <div class="pi-skeleton cm-tile__status-skel" />
        </div>
      </div>

      <!-- Connector grid -->
      <div v-else class="cm-grid">
        <div
          v-for="c in orderedConnectors"
          :key="c.id"
          class="cm-tile"
          :class="{
            'cm-tile--unavailable': !c.configured,
            'cm-tile--connected':   c.connected,
            'cm-tile--running':     isRunning(c),
          }"
        >
          <!-- Brand icon -->
          <div class="cm-tile__icon" aria-hidden="true">
            <!-- Google Drive -->
            <svg v-if="c.id === 'gdrive'" viewBox="0 0 32 32" class="brand-icon">
              <path d="M10.9 2 2 17.2l4.5 7.8L15.5 9.8 10.9 2zm10.2 0H10.9l9.2 15.9h10.4L21.1 2zm10.4 15.9H10.9l-4.4 7.6h21.3l-6.3-7.6z" fill="currentColor"/>
            </svg>
            <!-- Notion -->
            <svg v-else-if="c.id === 'notion'" viewBox="0 0 32 32" class="brand-icon">
              <path fill-rule="evenodd" clip-rule="evenodd" d="M5.5 3.6l16.8-1.2c2.1-.2 2.6 0 3.9 1l4.1 2.9c.7.5.9.6.9 1.4v20.3c0 1.3-.5 2-1.7 2.1L8 31.1c-1 .1-1.5-.1-2-.7L2.4 26c-.5-.6-.6-1.1-.6-1.7V5.6c0-1 .5-1.9 1.7-2zm16 1.8L7.2 6.5c-.9.1-1.2.5-1.2 1.1v17.5c0 .7.2 1 .8 1.1l17.2 1.2c.8 0 1.3-.3 1.3-1.3V6.7c0-.9-.4-1.2-1.4-1.3l-.3-.1zM20.5 9c.3-.6 1.4-.5 1.4.2v11.1c0 .7-.3.9-.9 1l-12 .6c-.7 0-.8-.2-.8-.9V10c0-.6.2-.8.7-1L20.5 9zM9.5 11l.3 1.1H19.3V11L9.5 11zm0 3v1h9.8v-1H9.5zm0 3v1h7v-1h-7z" fill="currentColor"/>
            </svg>
            <!-- GitHub -->
            <svg v-else-if="c.id === 'github'" viewBox="0 0 32 32" class="brand-icon">
              <path fill-rule="evenodd" clip-rule="evenodd" d="M16 2C8.3 2 2 8.3 2 16c0 6.2 4 11.4 9.6 13.3.7.1 1-.3 1-.7v-2.4c-3.9.8-4.7-1.9-4.7-1.9-.6-1.6-1.5-2-1.5-2-1.3-.9.1-.9.1-.9 1.4.1 2.1 1.4 2.1 1.4 1.2 2.1 3.2 1.5 4 1.1.1-.9.5-1.5.9-1.8-3.1-.4-6.3-1.6-6.3-6.9 0-1.5.5-2.8 1.4-3.7-.1-.4-.6-1.8.1-3.7 0 0 1.1-.4 3.7 1.4 1.1-.3 2.2-.4 3.3-.4 1.1 0 2.3.1 3.3.4 2.5-1.7 3.7-1.4 3.7-1.4.7 1.9.3 3.3.1 3.7.9.9 1.4 2.2 1.4 3.7 0 5.3-3.3 6.5-6.4 6.9.5.4 1 1.3 1 2.6v3.9c0 .4.3.8 1 .7C26 27.4 30 22.2 30 16c0-7.7-6.3-14-14-14z" fill="currentColor"/>
            </svg>
            <!-- Generic fallback globe icon -->
            <svg v-else viewBox="0 0 32 32" class="brand-icon">
              <circle cx="16" cy="16" r="13" stroke="currentColor" stroke-width="2" fill="none"/>
              <path d="M3 16h26M16 3c-3 4-5 8-5 13s2 9 5 13M16 3c3 4 5 8 5 13s-2 9-5 13" stroke="currentColor" stroke-width="1.8" fill="none"/>
            </svg>
          </div>

          <!-- Name -->
          <div class="cm-tile__name">{{ c.display_name }}</div>

          <!-- State chip / info -->
          <div class="cm-tile__meta">
            <!-- Real but operator hasn't configured it -->
            <template v-if="!c.configured">
              <span class="cm-chip cm-chip--unavail">Not available</span>
            </template>

            <!-- Connected -->
            <template v-else-if="c.connected">
              <span class="cm-chip cm-chip--ok">Connected</span>
              <span v-if="c.imported_count > 0" class="cm-tile__count t-mono">
                {{ c.imported_count.toLocaleString() }} items
              </span>
              <span v-if="c.last_sync_at" class="cm-tile__sync t-mono">
                Last sync {{ relativeTime(c.last_sync_at) }}
              </span>
            </template>

            <!-- Configured, not connected yet -->
            <template v-else>
              <span class="cm-chip cm-chip--idle">Not connected</span>
            </template>
          </div>

          <!-- Actions -->
          <div class="cm-tile__actions">
            <!-- Importing in progress -->
            <template v-if="isRunning(c)">
              <BrainPulse :size="20" aria-hidden="true" />
              <span class="cm-importing t-mono">Importing…</span>
            </template>

            <!-- Connected: sync + disconnect -->
            <template v-else-if="c.connected">
              <PiButton
                variant="ghost"
                size="compact"
                :loading="busy[c.id]"
                @click="handleSync(c)"
              >
                Sync now
              </PiButton>
              <PiButton
                variant="ghost"
                size="compact"
                :loading="busy[c.id]"
                @click="handleDisconnect(c)"
              >
                Disconnect
              </PiButton>
            </template>

            <!-- Configured + not connected: connect -->
            <template v-else-if="c.configured">
              <PiButton
                variant="secondary"
                size="compact"
                :loading="busy[c.id]"
                @click="handleConnect(c)"
              >
                Connect
              </PiButton>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── Overlay + panel ─────────────────────────────────────────────────────── */
.cm-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background: color-mix(in srgb, var(--background-page) 75%, transparent);
  animation: pi-fade-in 0.15s var(--ease);
}

.cm-panel {
  background: var(--background-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-menu);
  width: 100%;
  max-width: 720px;
  max-height: 86vh;
  overflow-y: auto;
  padding: var(--space-6);
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.cm-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.cm-title {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}

.cm-subtitle {
  font-size: var(--text-base);
  color: var(--text-secondary);
  line-height: 1.6;
  font-style: italic;
  max-width: 48ch;
}

.cm-close {
  flex-shrink: 0;
  margin-top: 2px;
}

/* ── Grid ────────────────────────────────────────────────────────────────── */
.cm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: var(--space-4);
}

/* ── Tile ────────────────────────────────────────────────────────────────── */
.cm-tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--background-raised);
  transition: border-color 0.15s var(--ease);
}

.cm-tile--connected {
  border-color: var(--accent-primary);
  background: var(--accent-surface);
}

.cm-tile--unavailable {
  opacity: 0.5;
}

.cm-tile--running {
  border-color: var(--brain-amber);
  background: var(--brain-amber-surface);
}

/* ── Brand icon ──────────────────────────────────────────────────────────── */
.cm-tile__icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  flex-shrink: 0;
  margin-bottom: var(--space-1);
}

.cm-tile--connected .cm-tile__icon {
  color: var(--accent-primary);
}

.cm-tile--running .cm-tile__icon {
  color: var(--brain-amber);
}

.brand-icon {
  width: 28px;
  height: 28px;
}

/* ── Text rows ───────────────────────────────────────────────────────────── */
.cm-tile__name {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-sm);
  color: var(--text-primary);
  line-height: 1.3;
}

.cm-tile__meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
}

.cm-tile__count,
.cm-tile__sync {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.4;
}

/* ── Chips ───────────────────────────────────────────────────────────────── */
.cm-chip {
  display: inline-block;
  font-size: var(--text-xs);
  font-family: var(--font-body);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  line-height: 1.6;
  font-weight: 500;
}

.cm-chip--unavail { background: var(--background-input); color: var(--text-tertiary); border: 1px solid var(--border-medium); }
.cm-chip--ok     { background: var(--accent-surface); color: var(--accent-primary); border: 1px solid var(--accent-primary); }
.cm-chip--idle   { background: var(--background-input); color: var(--text-secondary); border: 1px solid var(--border-subtle); }

/* ── Actions ─────────────────────────────────────────────────────────────── */
.cm-tile__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-top: auto;
}

.cm-importing {
  font-size: var(--text-xs);
  color: var(--brain-amber);
}

/* ── Skeleton ────────────────────────────────────────────────────────────── */
.cm-tile--skeleton {
  gap: var(--space-3);
  pointer-events: none;
}

.cm-tile__icon-skel  { width: 32px;  height: 32px;  border-radius: var(--radius-sm); }
.cm-tile__name-skel  { width: 80px;  height: 14px;  border-radius: var(--radius-sm); }
.cm-tile__status-skel { width: 60px; height: 12px;  border-radius: var(--radius-sm); }
</style>
