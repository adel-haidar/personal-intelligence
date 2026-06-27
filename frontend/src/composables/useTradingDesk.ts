/**
 * useTradingDesk — Agent Trading Desk composable
 * Calls /api/trading/desk/* endpoints (same-origin, API_BASE='').
 * Auth: same Bearer token pattern as useAdvisory.ts.
 * Polls GET /runs/{id} ~1.5s while run.status is non-terminal.
 */

import { ref, computed, onUnmounted } from 'vue'
import { requireAuth, refreshTokens, hasRefreshToken } from './useAuth'
import { API_BASE } from '../config/env'

// ── Types ─────────────────────────────────────────────────────────────────────

export type RunStatus =
  | 'researching'
  | 'drafting'
  | 'evaluating'
  | 'awaiting_approval'
  | 'executing'
  | 'done'
  | 'denied'
  | 'cancelled'
  | 'failed'

export type RiskVerdict = 'cleared' | 'adjusted' | 'protected' | 'rejected'
export type TradeStatus = 'pending' | 'placed' | 'skipped' | 'rejected'
export type TradeSide = 'buy' | 'trim' | 'sell'
export type TradeStrategy = 'conservative' | 'moderate' | 'aggressive'
export type TradeMode = 'controlled' | 'auto'
export type TradeAccount = 'paper' | 'live'

export const TERMINAL_STATUSES: RunStatus[] = ['done', 'denied', 'cancelled', 'failed']

export interface DeskConfig {
  account: TradeAccount
  strategy: TradeStrategy
  mode: TradeMode
  allocation: number
  reserve_floor: number
  universe: {
    etf: boolean
    crypto: boolean
    forex: boolean
    commodities: boolean
    bonds: boolean
  }
  guardrails: {
    max_trade_pct: number
    day_loss_pct: number
    stop_pct: number
  }
}

export interface BrokerInfo {
  connected: boolean
  provider?: string
  environment?: string
  label?: string
  status?: string
  last_verified_at?: string | null
  available_cash?: number | null
  currency?: string | null
}

export interface DeskRun {
  id: string
  user_id?: string
  account: TradeAccount
  strategy: TradeStrategy
  mode: TradeMode
  allocation: number
  reserve: number
  status: RunStatus
  market_read?: string | null
  notional?: number | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface RunEvent {
  id: string
  run_id: string
  stage: 'research' | 'coordinate' | 'strategy' | 'evaluate' | 'execute'
  agent: 'coordinator' | 'web_scout' | 'analyst' | 'strategist' | 'risk_officer' | 'broker'
  type: 'work' | 'report' | 'think' | 'spawn' | 'gate' | 'done'
  message: string
  created_at: string
}

export interface DeskTrade {
  id: string
  run_id: string
  ticker: string
  name: string
  side: TradeSide
  amount: number
  pct_of_allocation: number
  headline: string
  reasoning: string
  evidence: string[]
  risk_verdict: RiskVerdict
  risk_note: string
  kept: boolean
  status: TradeStatus
  order_type?: string
  limit_price?: number | null
  broker_order_id?: string | null
  filled_qty?: number | null
  filled_price?: number | null
  created_at: string
}

export interface PortfolioHolding {
  ticker: string
  name: string
  value: number
  pct: number
  day_change: number
  asset_class: string
}

export interface PortfolioData {
  account: TradeAccount
  value: number
  cash: number
  day_change: number
  since_funded: number
  holdings: PortfolioHolding[]
}

export interface RunBundle {
  run: DeskRun | null
  events: RunEvent[]
  trades: DeskTrade[]
}

// ── Strategy metadata (from handoff) ────────────────────────────────────────

export const STRATEGY_META: Record<TradeStrategy, {
  label: string
  tone: 'success' | 'info' | 'warning'
  line: string
  maxTrade: number
  dayLoss: number
  cryptoCap: number
  defaultStop: number
}> = {
  conservative: {
    label: 'Conservative', tone: 'success',
    line: 'Capital preservation first. Small, low-volatility positions; almost no drawdown tolerated.',
    maxTrade: 8, dayLoss: 1.5, cryptoCap: 0, defaultStop: 6,
  },
  moderate: {
    label: 'Moderate', tone: 'info',
    line: 'Balanced. Measured risk, diversified, no single bet large enough to hurt.',
    maxTrade: 18, dayLoss: 4, cryptoCap: 10, defaultStop: 6,
  },
  aggressive: {
    label: 'Aggressive', tone: 'warning',
    line: 'Profit-seeking. Higher risk tolerance and larger positions for bigger upside.',
    maxTrade: 35, dayLoss: 9, cryptoCap: 25, defaultStop: 6,
  },
}

export const UNIVERSE_OPTIONS = [
  { id: 'etf' as const,          label: 'Stocks & ETFs' },
  { id: 'crypto' as const,       label: 'Crypto' },
  { id: 'forex' as const,        label: 'Forex' },
  { id: 'commodities' as const,  label: 'Commodities' },
  { id: 'bonds' as const,        label: 'Bonds & index funds' },
]

export const STAGE_LABELS: Record<string, string> = {
  research:   'Read the market',
  coordinate: 'Combine findings',
  strategy:   'Draft the trades',
  evaluate:   'Check the risk',
  execute:    'Place the orders',
}

export const STAGE_AGENTS: Record<string, string[]> = {
  research:   ['Web scout', 'Analyst'],
  coordinate: ['Coordinator'],
  strategy:   ['Strategist'],
  evaluate:   ['Risk officer'],
  execute:    ['Broker'],
}

export const STAGE_ORDER = ['research', 'coordinate', 'strategy', 'evaluate', 'execute']

// Map run status → current stage
export function runStatusToStage(status: RunStatus | undefined): string {
  switch (status) {
    case 'researching':        return 'research'
    case 'drafting':           return 'strategy'
    case 'evaluating':         return 'evaluate'
    case 'awaiting_approval':  return 'execute'
    case 'executing':          return 'execute'
    case 'done':               return 'execute'
    default:                   return 'research'
  }
}

// ── Default config ────────────────────────────────────────────────────────────

function defaultConfig(): DeskConfig {
  return {
    account: 'paper',
    strategy: 'moderate',
    mode: 'controlled',
    allocation: 25000,
    reserve_floor: 5000,
    universe: { etf: true, crypto: true, forex: false, commodities: false, bonds: true },
    guardrails: { max_trade_pct: 18, day_loss_pct: 4, stop_pct: 6 },
  }
}

// ── Composable ────────────────────────────────────────────────────────────────

export function useTradingDesk() {
  const BASE = API_BASE

  // State
  const configStatus = ref<'idle' | 'loading' | 'error' | 'success'>('idle')
  const config = ref<DeskConfig>(defaultConfig())
  const broker = ref<BrokerInfo>({ connected: false })
  const runBundle = ref<RunBundle>({ run: null, events: [], trades: [] })
  const portfolio = ref<PortfolioData | null>(null)
  const error = ref<string | null>(null)
  const actionLoading = ref(false)
  const brokerLoading = ref(false)

  // Polling
  let pollTimer: ReturnType<typeof setTimeout> | null = null

  // ── Auth fetch helper ─────────────────────────────────────────────────────

  async function authedFetch(
    path: string,
    options: RequestInit = {},
  ): Promise<Response> {
    let token = await requireAuth()
    const doFetch = (t: string) =>
      fetch(`${BASE}${path}`, {
        ...options,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}`, ...(options.headers ?? {}) },
      })
    let res = await doFetch(token)
    if (res.status === 401 && hasRefreshToken()) {
      await refreshTokens()
      token = await requireAuth()
      res = await doFetch(token)
    }
    return res
  }

  async function apiGet<T>(path: string): Promise<T> {
    const res = await authedFetch(path, { method: 'GET' })
    if (!res.ok) {
      const body = await res.text()
      let msg = `HTTP ${res.status}`
      if (!body.trimStart().startsWith('<')) {
        try { msg = (JSON.parse(body) as { detail?: string }).detail ?? msg } catch {}
      }
      throw new Error(msg)
    }
    return res.json() as Promise<T>
  }

  async function apiPost<T>(path: string, body?: unknown): Promise<T> {
    const res = await authedFetch(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) {
      const text = await res.text()
      let msg = `HTTP ${res.status}`
      if (!text.trimStart().startsWith('<')) {
        try { msg = (JSON.parse(text) as { detail?: string }).detail ?? msg } catch {}
      }
      throw new Error(msg)
    }
    return res.json() as Promise<T>
  }

  async function apiPut<T>(path: string, body?: unknown): Promise<T> {
    const res = await authedFetch(path, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) {
      const text = await res.text()
      let msg = `HTTP ${res.status}`
      if (!text.trimStart().startsWith('<')) {
        try { msg = (JSON.parse(text) as { detail?: string }).detail ?? msg } catch {}
      }
      throw new Error(msg)
    }
    return res.json() as Promise<T>
  }

  async function apiDelete<T>(path: string): Promise<T> {
    const res = await authedFetch(path, { method: 'DELETE' })
    if (!res.ok) {
      const text = await res.text()
      let msg = `HTTP ${res.status}`
      try { msg = (JSON.parse(text) as { detail?: string }).detail ?? msg } catch {}
      throw new Error(msg)
    }
    return res.json() as Promise<T>
  }

  // ── Polling ───────────────────────────────────────────────────────────────

  function stopPoll() {
    if (pollTimer !== null) { clearTimeout(pollTimer); pollTimer = null }
  }

  async function pollRun(runId: string) {
    stopPoll()
    try {
      const bundle = await apiGet<RunBundle>(`/api/trading/desk/runs/${runId}`)
      runBundle.value = bundle
      const status = bundle.run?.status
      if (status && !TERMINAL_STATUSES.includes(status)) {
        pollTimer = setTimeout(() => pollRun(runId), 1500)
      }
    } catch {
      // silently retry on transient errors
      pollTimer = setTimeout(() => pollRun(runId), 3000)
    }
  }

  // ── Public API ────────────────────────────────────────────────────────────

  async function loadConfig() {
    configStatus.value = 'loading'
    error.value = null
    try {
      const cfg = await apiGet<DeskConfig>('/api/trading/desk/config')
      config.value = cfg
      configStatus.value = 'success'
    } catch (e) {
      configStatus.value = 'error'
      error.value = e instanceof Error ? e.message : 'Failed to load config'
    }
  }

  async function saveConfig(patch: Partial<DeskConfig>) {
    error.value = null
    try {
      const cfg = await apiPut<DeskConfig>('/api/trading/desk/config', patch)
      config.value = cfg
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to save config'
    }
  }

  async function loadBroker() {
    try {
      const b = await apiGet<BrokerInfo>('/api/trading/desk/broker')
      broker.value = b
    } catch {
      broker.value = { connected: false }
    }
  }

  async function connectBroker(environment: 'demo' | 'live', api_key: string, api_secret?: string) {
    brokerLoading.value = true
    error.value = null
    try {
      const b = await apiPut<BrokerInfo>('/api/trading/desk/broker', { environment, api_key, api_secret })
      broker.value = b
      // Refresh via GET so we pick up the account's real available_cash.
      await loadBroker()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to connect broker'
    } finally {
      brokerLoading.value = false
    }
  }

  async function disconnectBroker() {
    brokerLoading.value = true
    try {
      const b = await apiDelete<BrokerInfo>('/api/trading/desk/broker')
      broker.value = b
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to disconnect broker'
    } finally {
      brokerLoading.value = false
    }
  }

  async function loadLatestRun() {
    try {
      const bundle = await apiGet<RunBundle>('/api/trading/desk/runs/latest')
      runBundle.value = bundle
      const runId = bundle.run?.id
      const status = bundle.run?.status
      if (runId && status && !TERMINAL_STATUSES.includes(status)) {
        pollRun(runId)
      }
    } catch {
      // no existing run — that's fine
    }
  }

  async function startRun() {
    actionLoading.value = true
    error.value = null
    try {
      const bundle = await apiPost<RunBundle>('/api/trading/desk/runs')
      runBundle.value = bundle
      const runId = bundle.run?.id
      if (runId) pollRun(runId)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to start run'
    } finally {
      actionLoading.value = false
    }
  }

  async function approveRun() {
    const runId = runBundle.value.run?.id
    if (!runId) return
    actionLoading.value = true
    error.value = null
    try {
      const bundle = await apiPost<RunBundle>(`/api/trading/desk/runs/${runId}/approve`)
      runBundle.value = bundle
      const status = bundle.run?.status
      if (status && !TERMINAL_STATUSES.includes(status)) {
        pollRun(runId)
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to approve run'
    } finally {
      actionLoading.value = false
    }
  }

  async function denyRun() {
    const runId = runBundle.value.run?.id
    if (!runId) return
    actionLoading.value = true
    try {
      const bundle = await apiPost<RunBundle>(`/api/trading/desk/runs/${runId}/deny`)
      runBundle.value = bundle
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to deny run'
    } finally {
      actionLoading.value = false
    }
  }

  async function cancelRun() {
    const runId = runBundle.value.run?.id
    if (!runId) return
    stopPoll()
    actionLoading.value = true
    try {
      const bundle = await apiPost<RunBundle>(`/api/trading/desk/runs/${runId}/cancel`)
      runBundle.value = bundle
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to cancel run'
    } finally {
      actionLoading.value = false
    }
  }

  async function keepTrade(tradeId: string) {
    try {
      const trade = await apiPost<DeskTrade>(`/api/trading/desk/trades/${tradeId}/keep`)
      _patchTrade(trade)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to update trade'
    }
  }

  async function skipTrade(tradeId: string) {
    try {
      const trade = await apiPost<DeskTrade>(`/api/trading/desk/trades/${tradeId}/skip`)
      _patchTrade(trade)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to update trade'
    }
  }

  function _patchTrade(updated: DeskTrade) {
    const idx = runBundle.value.trades.findIndex(t => t.id === updated.id)
    if (idx !== -1) {
      runBundle.value = {
        ...runBundle.value,
        trades: runBundle.value.trades.map((t, i) => (i === idx ? updated : t)),
      }
    }
  }

  async function loadPortfolio() {
    try {
      portfolio.value = await apiGet<PortfolioData>('/api/trading/desk/portfolio')
    } catch {
      portfolio.value = null
    }
  }

  function resetRun() {
    stopPoll()
    runBundle.value = { run: null, events: [], trades: [] }
  }

  // ── Derived / computed ────────────────────────────────────────────────────

  const currentRun = computed(() => runBundle.value.run)
  const trades = computed(() => runBundle.value.trades)
  const events = computed(() => runBundle.value.events)

  const runStatus = computed<RunStatus | null>(() => currentRun.value?.status ?? null)

  const isRunning = computed(() =>
    runStatus.value !== null && !TERMINAL_STATUSES.includes(runStatus.value),
  )

  const atApprovalGate = computed(() => runStatus.value === 'awaiting_approval')

  const isDone = computed(() => runStatus.value === 'done')

  // workspace: which panel to show
  const workspace = computed<'setup' | 'working' | 'cards' | 'monitoring' | 'error'>(() => {
    const s = runStatus.value
    if (!s) return 'setup'
    if (s === 'done') return 'monitoring'
    if (s === 'awaiting_approval') return 'cards'
    if (s === 'failed') return 'error'
    // denied | cancelled → back to setup (user-initiated)
    if (s === 'denied' || s === 'cancelled') return 'setup'
    // researching | drafting | evaluating | executing
    return 'working'
  })

  // The failure reason from a failed run (shown in the error workspace).
  const runError = computed<string | null>(() => currentRun.value?.error ?? null)

  // which stage is active based on run events + status
  const activeStage = computed<string>(() => {
    const s = runStatus.value
    if (!s) return ''
    return runStatusToStage(s)
  })

  function stageStatus(stageId: string): 'todo' | 'active' | 'done' {
    const s = runStatus.value
    if (!s) return 'todo'
    const active = activeStage.value
    const activeIdx = STAGE_ORDER.indexOf(active)
    const stageIdx = STAGE_ORDER.indexOf(stageId)
    if (stageIdx < activeIdx) return 'done'
    if (stageIdx === activeIdx) return 'active'
    return 'todo'
  }

  // notional of kept+non-rejected trades
  const keptNotional = computed(() =>
    trades.value
      .filter(t => t.kept && t.risk_verdict !== 'rejected' && t.status !== 'rejected')
      .reduce((sum, t) => sum + t.amount, 0),
  )

  const keptCount = computed(() =>
    trades.value.filter(t => t.kept && t.risk_verdict !== 'rejected' && t.status !== 'rejected').length,
  )

  // Cleanup on unmount
  onUnmounted(() => stopPoll())

  return {
    // state
    configStatus,
    config,
    broker,
    runBundle,
    portfolio,
    error,
    actionLoading,
    brokerLoading,
    // derived
    currentRun,
    trades,
    events,
    runStatus,
    isRunning,
    atApprovalGate,
    isDone,
    workspace,
    runError,
    activeStage,
    stageStatus,
    keptNotional,
    keptCount,
    // actions
    loadConfig,
    saveConfig,
    loadBroker,
    connectBroker,
    disconnectBroker,
    loadLatestRun,
    startRun,
    approveRun,
    denyRun,
    cancelRun,
    keepTrade,
    skipTrade,
    loadPortfolio,
    resetRun,
  }
}
