import { ref, type Ref } from 'vue'
import { requireAuth, refreshTokens, hasRefreshToken } from './useAuth'
import { API_BASE } from '../config/env'

// ── Investment recommendation types ─────────────────────────────────────────

export interface Holding {
  name:            string
  ticker?:         string
  type?:           string
  allocation_pct?: number | null
  value_eur?:      number | null
  note?:           string
}

export interface InvestmentStatus {
  strategy_summary:     string
  portfolio_value_eur?: number | null
  holdings:             Holding[]
  data_freshness:       string
}

export interface AllocationRec {
  asset:        string
  ticker?:      string
  current_pct?: number | null
  target_pct:   number
  action:       'increase' | 'decrease' | 'hold' | 'open' | 'close'
  rationale:    string
}

export interface InvestmentResult {
  analysis_date:             string
  current_status:            InvestmentStatus
  allocation_recommendation: AllocationRec[]
  monthly_contribution_eur?: number | null
  notes:                     string[]
  reasoning:                 string
}

// ── Day trading types ────────────────────────────────────────────────────────

export interface IndexQuote {
  symbol:      string
  name:        string
  price?:      number | null
  change_pct?: number | null
}

export interface RegionOverview {
  summary: string
  indices: IndexQuote[]
}

export type TradeMarket = 'us' | 'europe' | 'southeast_asia'

export interface TradeRec {
  ticker:      string
  name:        string
  market:      TradeMarket
  action:      'buy' | 'hold' | 'sell'
  rationale:   string
  confidence:  'high' | 'medium' | 'low'
  held_since?: string | null
}

export interface DayTradingResult {
  analysis_date:      string
  market_overview:    Record<TradeMarket, RegionOverview>
  recommendations:    TradeRec[]
  changes_since_last: string
  sources_used:       string[]
  risk_note:          string
  reasoning:          string
}

export interface SnapshotMeta {
  fetched_at?:     string
  sources_ok?:     string[]
  sources_failed?: string[]
}

export interface AnalysisPayload<T> {
  saved_at:       string
  result:         T
  snapshot_meta?: SnapshotMeta
}

// ── Generic run/load-latest client ───────────────────────────────────────────

const BASE = API_BASE

export interface AdvisoryClient<T> {
  status:       Ref<'idle' | 'loading' | 'error' | 'success'>
  result:       Ref<T | null>
  savedAt:      Ref<Date | null>
  cached:       Ref<boolean>
  error:        Ref<string | null>
  snapshotMeta: Ref<SnapshotMeta | null>
  run:          () => Promise<void>
  loadLatest:   () => Promise<void>
}

/** Shared run/load-latest state machine for analysis endpoints that return
 *  {saved_at, result} and cache their latest run in MCP memory. */
export function useAdvisory<T>(runPath: string, latestPath: string): AdvisoryClient<T> {
  const status       = ref<'idle' | 'loading' | 'error' | 'success'>('idle')
  const result       = ref<T | null>(null) as Ref<T | null>
  const savedAt      = ref<Date | null>(null)
  const cached       = ref(false)
  const error        = ref<string | null>(null)
  const snapshotMeta = ref<SnapshotMeta | null>(null)

  async function authedFetch(path: string, method: 'GET' | 'POST'): Promise<Response> {
    let token = await requireAuth()
    const doFetch = (t: string) =>
      fetch(`${BASE}${path}`, { method, headers: { Authorization: `Bearer ${t}` } })
    let res = await doFetch(token)
    if (res.status === 401 && hasRefreshToken()) {
      await refreshTokens()
      token = await requireAuth()
      res = await doFetch(token)
    }
    return res
  }

  function applyPayload(payload: AnalysisPayload<T>, fromCache: boolean) {
    result.value       = payload.result
    savedAt.value      = payload.saved_at ? new Date(payload.saved_at) : new Date()
    snapshotMeta.value = payload.snapshot_meta ?? null
    cached.value       = fromCache
    status.value       = 'success'
  }

  async function request(path: string, method: 'GET' | 'POST', fromCache: boolean, silent404: boolean) {
    status.value = fromCache && result.value === null ? 'loading' : status.value
    if (!fromCache) status.value = 'loading'
    error.value = null
    try {
      const res = await authedFetch(path, method)
      const body = await res.text()
      if (res.status === 404 && silent404) {
        if (result.value === null) status.value = 'idle'
        return
      }
      if (!res.ok) {
        let msg = `HTTP ${res.status}`
        if (!body.trimStart().startsWith('<')) {
          try { msg = (JSON.parse(body) as { detail?: string }).detail ?? msg } catch {}
        }
        throw new Error(msg)
      }
      if (body.trimStart().startsWith('<')) {
        throw new Error('Backend service unavailable (got HTML instead of JSON).')
      }
      applyPayload(JSON.parse(body) as AnalysisPayload<T>, fromCache)
    } catch (e) {
      status.value = 'error'
      error.value  = e instanceof Error ? e.message : 'Request failed'
    }
  }

  const run        = () => request(runPath, 'POST', false, false)
  const loadLatest = () => request(latestPath, 'GET', true, true)

  return { status, result, savedAt, cached, error, snapshotMeta, run, loadLatest }
}

export const useInvesting = () =>
  useAdvisory<InvestmentResult>('/api/investing/analyse', '/api/investing/latest')

export const useDayTrading = () =>
  useAdvisory<DayTradingResult>('/api/trading/analyse', '/api/trading/latest')
