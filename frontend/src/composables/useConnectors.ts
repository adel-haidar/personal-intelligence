/**
 * useConnectors — composable for managing external platform connectors.
 *
 * API:
 *   GET    /api/connectors           → list of connectors
 *   GET    /api/connectors/{id}/authorize  → { authorize_url }
 *   POST   /api/connectors/{id}/sync       → { started: true }
 *   GET    /api/connectors/{id}/status     → { connected, running, status, imported_count, last_sync_at }
 *   DELETE /api/connectors/{id}            → { disconnected: true }
 *
 * OAuth flow:
 *   connect(id) → opens authorize_url in a centered 600×720 popup.
 *   The popup lands at /memory?connected={id} or /memory?connect_error={id},
 *   which postMessages back to this opener via the message event registered here.
 */
import { ref } from 'vue'
import { requireAuth } from './useAuth'
import { API_BASE } from '../config/env'
import type { Connector, ConnectorStatus } from '../types/connector'

const connectors = ref<Connector[]>([])
const loading = ref(false)

// Per-connector status polling: map of connector id → interval id
const _pollers = new Map<string, number>()

// Message listener reference (so we can remove it on cleanup)
let _messageHandler: ((e: MessageEvent) => void) | null = null
// Popup reference
let _popup: Window | null = null

// ── Callbacks ────────────────────────────────────────────────────────────────
type ConnectSuccessCb = (id: string) => void
type ConnectErrorCb   = (id: string) => void

const _successCbs = new Set<ConnectSuccessCb>()
const _errorCbs   = new Set<ConnectErrorCb>()

export function onConnectSuccess(cb: ConnectSuccessCb): () => void {
  _successCbs.add(cb)
  return () => _successCbs.delete(cb)
}

export function onConnectError(cb: ConnectErrorCb): () => void {
  _errorCbs.add(cb)
  return () => _errorCbs.delete(cb)
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function openCenteredPopup(url: string, name: string, w = 600, h = 720): Window | null {
  const left = Math.round(window.screenX + (window.outerWidth  - w) / 2)
  const top  = Math.round(window.screenY + (window.outerHeight - h) / 2)
  return window.open(
    url,
    name,
    `width=${w},height=${h},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=yes,resizable=yes`,
  )
}

function patchConnector(id: string, patch: Partial<Connector>): void {
  const idx = connectors.value.findIndex(c => c.id === id)
  if (idx !== -1) {
    connectors.value[idx] = { ...connectors.value[idx], ...patch }
  }
}

// ── Status polling ────────────────────────────────────────────────────────────
type PollerDoneCb = (id: string, status: ConnectorStatus) => void

function startPolling(id: string, onDone?: PollerDoneCb): void {
  if (_pollers.has(id)) return
  const intervalId = window.setInterval(async () => {
    try {
      const s = await fetchStatus(id)
      patchConnector(id, {
        connected:      s.connected,
        status:         s.status,
        imported_count: s.imported_count,
        last_sync_at:   s.last_sync_at,
      })
      if (!s.running) {
        stopPolling(id)
        onDone?.(id, s)
      }
    } catch {
      // polling is best-effort
    }
  }, 4000)
  _pollers.set(id, intervalId)
}

function stopPolling(id: string): void {
  const tid = _pollers.get(id)
  if (tid !== undefined) {
    window.clearInterval(tid)
    _pollers.delete(id)
  }
}

// ── Message handler (popup completion) ───────────────────────────────────────
export function ensureMessageListener(): void {
  if (_messageHandler) return
  _messageHandler = (e: MessageEvent) => {
    if (e.origin !== window.location.origin) return
    const data = e.data as { type?: string; id?: string; ok?: boolean }
    if (data?.type !== 'pi-connector' || !data.id) return
    if (data.ok) {
      _successCbs.forEach(cb => cb(data.id!))
    } else {
      _errorCbs.forEach(cb => cb(data.id!))
    }
  }
  window.addEventListener('message', _messageHandler)
}

export function removeMessageListener(): void {
  if (_messageHandler) {
    window.removeEventListener('message', _messageHandler)
    _messageHandler = null
  }
}

// ── Public API ────────────────────────────────────────────────────────────────
export async function fetchConnectors(): Promise<Connector[]> {
  loading.value = true
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/connectors`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(`Connectors fetch failed: ${res.status}`)
    const data = await res.json() as { connectors: Connector[] }
    connectors.value = data.connectors
    return data.connectors
  } finally {
    loading.value = false
  }
}

export async function connect(id: string, onDone?: PollerDoneCb): Promise<void> {
  const token = await requireAuth()
  const res = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(id)}/authorize`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? `Authorize failed: ${res.status}`)
  }
  const { authorize_url } = await res.json() as { authorize_url: string }

  ensureMessageListener()

  // Register a one-time success callback to start polling once connected
  const unsub = onConnectSuccess((connectedId) => {
    if (connectedId !== id) return
    unsub()
    // Patch the connector to show connected immediately
    patchConnector(id, { connected: true })
    startPolling(id, onDone)
  })

  _popup = openCenteredPopup(authorize_url, 'pi_connect')
  if (!_popup) {
    // Popup was blocked — let the caller know so they can show a message
    throw new Error('Popup blocked. Please allow popups for this site and try again.')
  }
}

export async function sync(id: string, onDone?: PollerDoneCb): Promise<void> {
  const token = await requireAuth()
  const res = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(id)}/sync`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.status === 409) throw new Error('Sync already running.')
  if (res.status === 400) throw new Error('Connector is not connected.')
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? `Sync failed: ${res.status}`)
  }
  // Optimistically mark as running
  patchConnector(id, { status: 'running' })
  startPolling(id, onDone)
}

export async function fetchStatus(id: string): Promise<ConnectorStatus> {
  const token = await requireAuth()
  const res = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(id)}/status`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Status fetch failed: ${res.status}`)
  return res.json() as Promise<ConnectorStatus>
}

export async function disconnect(id: string): Promise<void> {
  const token = await requireAuth()
  const res = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? `Disconnect failed: ${res.status}`)
  }
  stopPolling(id)
  patchConnector(id, { connected: false, status: null, imported_count: 0, last_sync_at: null })
}

export function useConnectors() {
  return {
    connectors,
    loading,
    fetchConnectors,
    connect,
    sync,
    disconnect,
    fetchStatus,
    startPolling,
    stopPolling,
    ensureMessageListener,
    removeMessageListener,
    onConnectSuccess,
    onConnectError,
  }
}
