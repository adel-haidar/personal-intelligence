import { ref } from 'vue'
import { requireAuth, refreshTokens } from './useAuth'

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

const ANALYSE_URL = import.meta.env.DEV
  ? '/api/banking/analyse'
  : 'https://adel-intelligence.com/api/banking/analyse'

export function useBankAdviser() {
  const status  = ref<'idle' | 'loading' | 'error' | 'success'>('idle')
  const result  = ref<BankAdviserResult | null>(null)
  const error   = ref<string | null>(null)
  const lastRun = ref<Date | null>(null)

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

    if (res.status === 401) {
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

    if (!res.ok) {
      let msg = `HTTP ${res.status}`
      try {
        const body = await res.json() as { detail?: string }
        msg = body.detail ?? msg
      } catch {}
      status.value = 'error'
      error.value  = msg
      return
    }

    try {
      result.value  = await res.json() as BankAdviserResult
      status.value  = 'success'
      lastRun.value = new Date()
    } catch {
      status.value = 'error'
      error.value  = 'Failed to parse response'
    }
  }

  return { status, result, error, lastRun, runAnalysis }
}
