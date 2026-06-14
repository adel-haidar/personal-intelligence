import { ref } from 'vue'
import { requireAuth, refreshTokens, hasRefreshToken } from './useAuth'
import { API_BASE } from '../config/env'

// ── Types ──────────────────────────────────────────────────────────────────

export interface DailyHealthSummary {
  date: string
  weight_kg: number | null
  weight_7day_avg: number | null
  weight_trend_kg_per_week: number | null
  body_fat_percent: number | null
  resting_hr: number | null
  resting_hr_7day_avg: number | null
  hrv_ms: number | null
  sleep_duration_min: number | null
  sleep_score: number | null
  steps: number | null
  active_energy_kcal: number | null
  progress_to_goal_kg: number | null
  weeks_to_goal_at_current_rate: number | null
}

export interface SourceAvailability {
  source: 'beurer_scale' | 'apple_watch'
  available: boolean
  last_data_date: string | null
  next_expected_date: string | null
}

export interface HealthInsightResponse {
  date: string
  status?: 'ok' | 'not_run'
  summary: DailyHealthSummary
  flags: string[]
  coach_insight: string
  analysis?: string
  reasoning?: string
  documents?: string[]
  data_availability?: SourceAvailability[]
}

export interface TrendPoint { date: string; value: number }

export interface TrendsResponse {
  days: number
  series: Record<string, TrendPoint[]>
}

// ── Base URL ───────────────────────────────────────────────────────────────

const BASE = `${API_BASE}/api`

// ── Helpers ────────────────────────────────────────────────────────────────

async function authedGet(path: string): Promise<Response> {
  const token = await requireAuth()
  return fetch(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

async function authedPost(path: string): Promise<Response> {
  const token = await requireAuth()
  return fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

async function withTokenRefresh(fn: () => Promise<Response>): Promise<Response> {
  let res = await fn()
  // Only attempt a refresh when we actually have a refresh token (OAuth/legacy
  // sessions). Password-login sessions have none — calling refreshTokens() there
  // would clear the session and log the user out on any 401. # see bug: health/finances logout
  if (res.status === 401 && hasRefreshToken()) {
    await refreshTokens()
    res = await fn()
  }
  return res
}

async function parseJson<T>(res: Response): Promise<T> {
  const body = await res.text()
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    if (!body.trimStart().startsWith('<')) {
      try { msg = (JSON.parse(body) as { detail?: string }).detail ?? msg } catch {}
    }
    throw new Error(msg)
  }
  if (body.trimStart().startsWith('<')) throw new Error('Backend unavailable (got HTML)')
  return JSON.parse(body) as T
}

// ── Composable ─────────────────────────────────────────────────────────────

export function useHealthDaily() {
  const status  = ref<'idle' | 'loading' | 'error' | 'success'>('idle')
  const result  = ref<HealthInsightResponse | null>(null)
  const error   = ref<string | null>(null)

  async function fetchDaily(targetDate: string): Promise<void> {
    status.value = 'loading'
    error.value  = null
    try {
      const res = await withTokenRefresh(() => authedGet(`/health/daily/${targetDate}`))
      result.value = await parseJson<HealthInsightResponse>(res)
      status.value = 'success'
    } catch (e) {
      status.value = 'error'
      error.value  = (e as Error).message
    }
  }

  async function runDaily(targetDate: string): Promise<void> {
    status.value = 'loading'
    error.value  = null
    try {
      const res = await withTokenRefresh(() => authedPost(`/health/run-daily/${targetDate}`))
      result.value = await parseJson<HealthInsightResponse>(res)
      status.value = 'success'
    } catch (e) {
      status.value = 'error'
      error.value  = (e as Error).message
    }
  }

  return { status, result, error, fetchDaily, runDaily }
}

export function useHealthTrends() {
  const status = ref<'idle' | 'loading' | 'error' | 'success'>('idle')
  const trends = ref<TrendsResponse | null>(null)
  const error  = ref<string | null>(null)

  async function fetchTrends(days = 30): Promise<void> {
    status.value = 'loading'
    error.value  = null
    try {
      const res = await withTokenRefresh(() => authedGet(`/health/trends?days=${days}`))
      trends.value = await parseJson<TrendsResponse>(res)
      status.value = 'success'
    } catch (e) {
      status.value = 'error'
      error.value  = (e as Error).message
    }
  }

  return { status, trends, error, fetchTrends }
}

// ── Apple Health import ────────────────────────────────────────────────────

export interface AppleHealthImportResult {
  inserted: number
  date_range: [string, string]
}

export function useAppleHealthImport() {
  const status  = ref<'idle' | 'uploading' | 'error' | 'success'>('idle')
  const error   = ref<string | null>(null)
  const result  = ref<AppleHealthImportResult | null>(null)

  async function uploadFile(file: File): Promise<AppleHealthImportResult> {
    status.value = 'uploading'
    error.value  = null
    result.value = null

    const token = await requireAuth()
    const form  = new FormData()
    form.append('file', file)

    const res = await fetch(`${BASE}/health/import/apple-health`, {
      method:  'POST',
      headers: { Authorization: `Bearer ${token}` },
      body:    form,
    })

    const data = await parseJson<AppleHealthImportResult>(res)
    result.value = data
    status.value = 'success'
    return data
  }

  return { status, error, result, uploadFile }
}
