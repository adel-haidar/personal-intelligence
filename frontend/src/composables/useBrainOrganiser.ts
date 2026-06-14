/**
 * useBrainOrganiser — shared client state for the Brain Organiser.
 *
 * Polls GET /api/brain/organise/status on a single app-wide 10s interval (started
 * by the always-mounted sidebar), exposes the live status to the sidebar signal,
 * the brain "sleeping" banner and the Settings row, triggers POST /api/brain/organise,
 * and notifies listeners on a running → completed/failed transition (so a component
 * inside the ToastProvider can fire the result toast).
 */
import { ref, computed } from 'vue'
import { requireAuth } from './useAuth'
import { API_BASE } from '../config/env'

export interface OrganiseLastRun {
  memories_before: number
  memories_after: number
  duplicates_removed: number
  clusters_merged: number
  completed_at: string | null
}

export interface OrganiseStatus {
  status: 'idle' | 'running' | 'completed' | 'failed'
  run_id: string | null
  stage: number | null
  stage_label: string | null
  progress_pct: number
  started_at: string | null
  last_run: OrganiseLastRun | null
}

const status = ref<OrganiseStatus | null>(null)
const running = computed(() => status.value?.status === 'running')

let intervalId: number | null = null
let prevStatus: string | null = null
type TransitionCb = (to: string, s: OrganiseStatus) => void
const listeners = new Set<TransitionCb>()

async function fetchStatus(): Promise<OrganiseStatus | null> {
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/brain/organise/status`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return status.value
    const s = (await res.json()) as OrganiseStatus
    const prev = prevStatus
    status.value = s
    prevStatus = s.status
    if (prev === 'running' && s.status !== 'running') {
      listeners.forEach((cb) => cb(s.status, s))
    }
    return s
  } catch {
    return status.value
  }
}

async function organise(): Promise<{ ok: boolean; conflict?: boolean; error?: string }> {
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/brain/organise`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.status === 202) {
      await fetchStatus()
      return { ok: true }
    }
    if (res.status === 409) return { ok: false, conflict: true }
    const body = await res.json().catch(() => ({}))
    return { ok: false, error: body.error }
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
}

function ensurePolling(ms = 10000): void {
  fetchStatus()
  if (intervalId !== null) return
  intervalId = window.setInterval(() => {
    if (typeof document !== 'undefined' && document.hidden) return
    fetchStatus()
  }, ms)
}

function onTransition(cb: TransitionCb): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function useBrainOrganiser() {
  return { status, running, fetchStatus, organise, ensurePolling, onTransition }
}
