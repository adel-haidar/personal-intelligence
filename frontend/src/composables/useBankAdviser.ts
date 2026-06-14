import { ref } from 'vue'
import { requireAuth, refreshTokens, hasRefreshToken } from './useAuth'
import { API_BASE } from '../config/env'

// ── Request types ──────────────────────────────────────────────────────────

export interface AnalysisParams {
  context?:     string
  mode:         'ytd' | 'single' | 'range'
  period_from?: string  // "YYYY-MM"
  period_to?:   string  // "YYYY-MM"
}

// ── Type definitions ───────────────────────────────────────────────────────

export interface AnalysisPeriod {
  from: string
  to:   string
}

export interface BankAdviserMeta {
  analysis_date:              string
  analysis_period:            string | AnalysisPeriod
  currency:                   string
  data_sources:               string[]
  memory_context_available?:  boolean
}

export interface IncomeSource {
  label:  string
  amount: number
}

export interface IncomeSummary {
  total_income: number
  sources:      IncomeSource[]
}

export interface CategoryBreakdown {
  budget:  number | null
  actual:  number
  delta:   number | null
  status:  'ok' | 'over' | 'under' | 'tracked'
  items?:  { name: string; amount: number; recurring?: boolean }[]
}

export interface Anomaly {
  severity: string
  category: string
  message:  string
}

export interface MonthOverMonthEntry {
  delta_eur: number
  trend:     string
}

export interface SpendingAnalysis {
  total_expenses:          number
  net_savings_this_period: number
  categories:              Record<string, CategoryBreakdown>
  anomalies:               Anomaly[]
  month_over_month:        Record<string, MonthOverMonthEntry>
}

export interface YearlyProgress {
  target_savings_eur:         number
  savings_ytd:                number
  remaining_target:           number
  months_elapsed?:            number
  months_remaining?:          number
  expected_savings_to_date?:  number
  variance_from_expected?:    number
  required_monthly_savings:   number
  trajectory:                 'on_track' | 'ahead' | 'behind'
  on_track:                   boolean
}

export interface ProposedAllocation {
  proposed:           number
  note:               string
  known_upcoming?:    { item: string; est_cost: number; date: string }[]
  items_review_due?:  { name: string; last_used: string; flag: string }[]
}

export interface BudgetNextMonth {
  proposed_allocations: Record<string, ProposedAllocation>
  projected_net_savings: number
}

export interface InvestmentSignal {
  ready_to_invest:  boolean
  available_amount: number
  note:             string
}

export interface Recommendation {
  priority: 'high' | 'medium' | 'low'
  category: string
  action:   string
}

export interface SavingsOpportunity {
  current_item:       string
  category:           string
  monthly_cost_eur:   number
  alternative:        string
  monthly_saving_eur: number
  annual_saving_eur:  number
  effort:             string
  prerequisite:       string
  trade_off:          string
  adel_fit_score:     string
  note:               string
}

export interface PieSlice   { label: string; value:    number }
export interface BarEntry   { month: string; income: number; expenses: number; savings: number }
export interface LineEntry  { month: string; cumulative_savings: number; target_line: number }

export interface ChartData {
  spending_by_category_pie: PieSlice[]
  income_vs_expenses_bar:   BarEntry[]
  savings_progress_line:    LineEntry[]
}

export interface BankAdviserResult {
  meta:                BankAdviserMeta
  income_summary:      IncomeSummary
  spending_analysis:   SpendingAnalysis
  yearly_progress:     YearlyProgress
  budget_next_month:   BudgetNextMonth
  investment_signal:   InvestmentSignal
  recommendations:     Recommendation[]
  savings_opportunities: SavingsOpportunity[]
  chart_data:          ChartData
  reasoning?:          string
}

// ── Composable ─────────────────────────────────────────────────────────────

const BASE = API_BASE
const ANALYSE_URL = `${BASE}/api/banking/analyse`
const LATEST_URL  = `${BASE}/api/banking/analysis/latest`

interface CachedAnalysis {
  saved_at: string
  mode:     string
  months:   string[]
  result:   BankAdviserResult
}

export function useBankAdviser() {
  const status  = ref<'idle' | 'loading' | 'error' | 'success'>('idle')
  const result  = ref<BankAdviserResult | null>(null)
  const error   = ref<string | null>(null)
  const lastRun = ref<Date | null>(null)
  const cached  = ref(false)

  async function doPost(token: string, params: AnalysisParams): Promise<Response> {
    return fetch(ANALYSE_URL, {
      method:  'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type':  'application/json',
      },
      body: JSON.stringify({
        context:     params.context ?? '',
        mode:        params.mode,
        period_from: params.period_from,
        period_to:   params.period_to,
      }),
    })
  }

  async function runAnalysis(params: AnalysisParams): Promise<void> {
    status.value = 'loading'
    error.value  = null

    let token: string
    try {
      token = await requireAuth()
    } catch {
      status.value = 'error'
      error.value  = 'Session expired — please re-authenticate'
      return
    }

    let res = await doPost(token, params)

    if (res.status === 401 && hasRefreshToken()) {
      try {
        await refreshTokens()
        token = await requireAuth()
        res   = await doPost(token, params)
      } catch {
        status.value = 'error'
        error.value  = 'Session expired — please re-authenticate'
        return
      }
    }

    const body = await res.text()

    if (!res.ok) {
      let msg = `HTTP ${res.status}`
      if (!body.trimStart().startsWith('<')) {
        try { msg = (JSON.parse(body) as { detail?: string }).detail ?? msg } catch {}
      }
      status.value = 'error'
      error.value  = msg
      return
    }

    // CloudFront returns 200 + index.html when the origin errors — detect that.
    if (body.trimStart().startsWith('<')) {
      status.value = 'error'
      error.value  = 'Backend service unavailable (got HTML instead of JSON). Check EC2 logs.'
      return
    }

    try {
      result.value  = JSON.parse(body) as BankAdviserResult
      status.value  = 'success'
      lastRun.value = new Date()
      cached.value  = false
    } catch {
      status.value = 'error'
      error.value  = 'Failed to parse response'
    }
  }

  /** Load the latest cached analysis from MCP memory without re-running the
   *  pipeline. Silently stays idle when none exists yet. */
  async function loadLatest(): Promise<void> {
    if (status.value === 'loading') return
    status.value = 'loading'
    error.value  = null
    try {
      let token = await requireAuth()
      const doGet = (t: string) =>
        fetch(LATEST_URL, { headers: { Authorization: `Bearer ${t}` } })
      let res = await doGet(token)
      if (res.status === 401 && hasRefreshToken()) {
        await refreshTokens()
        token = await requireAuth()
        res = await doGet(token)
      }
      if (res.status === 404) {
        status.value = 'idle'
        return
      }
      const body = await res.text()
      if (!res.ok || body.trimStart().startsWith('<')) {
        status.value = 'idle'  // cache miss is not an error worth surfacing
        return
      }
      const payload = JSON.parse(body) as CachedAnalysis
      result.value  = payload.result
      lastRun.value = payload.saved_at ? new Date(payload.saved_at) : null
      cached.value  = true
      status.value  = 'success'
    } catch {
      status.value = 'idle'
    }
  }

  return { status, result, error, lastRun, cached, runAnalysis, loadLatest }
}
