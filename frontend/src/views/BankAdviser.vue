<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import {
  Chart,
  ArcElement, DoughnutController,
  BarElement, BarController,
  LineElement, PointElement, LineController,
  CategoryScale, LinearScale,
  Tooltip,
  type ChartConfiguration,
} from 'chart.js'
import { useBankAdviser } from '../composables/useBankAdviser'
import type {
  BankAdviserResult,
  AnalysisPeriod,
  AnalysisParams,
  CategoryBreakdown,
  ProposedAllocation,
  SavingsOpportunity,
} from '../composables/useBankAdviser'

Chart.register(
  ArcElement, DoughnutController,
  BarElement, BarController,
  LineElement, PointElement, LineController,
  CategoryScale, LinearScale,
  Tooltip,
)

import { useInvesting, useDayTrading } from '../composables/useAdvisory'
import type { TradeMarket } from '../composables/useAdvisory'

// ── Composables ────────────────────────────────────────────────────────────

const { status, result, error, lastRun, cached, runAnalysis, loadLatest } = useBankAdviser()

const {
  status: invStatus, result: invResult, savedAt: invSavedAt, cached: invCached,
  error: invError, run: runInvesting, loadLatest: loadInvesting,
} = useInvesting()

const {
  status: dtStatus, result: dtResult, savedAt: dtSavedAt, cached: dtCached,
  error: dtError, snapshotMeta: dtMeta, run: runDayTrading, loadLatest: loadDayTrading,
} = useDayTrading()

// Load the cached analyses on page load — no recompute until explicitly run.
onMounted(() => {
  loadLatest()
  loadInvesting()
  loadDayTrading()
})

// ── Advisory helpers ────────────────────────────────────────────────────────

const MARKET_LABELS: Record<TradeMarket, string> = {
  us:             'US',
  europe:         'EUROPE',
  southeast_asia: 'SE ASIA',
}

function tradeActionBadge(action: string): { label: string; cls: string } {
  if (action === 'buy')  return { label: 'BUY',  cls: 'badge--active' }
  if (action === 'sell') return { label: 'SELL', cls: 'badge--error' }
  return                        { label: 'HOLD', cls: 'badge--standby' }
}

function allocActionBadge(action: string): { label: string; cls: string } {
  if (action === 'increase' || action === 'open')  return { label: action.toUpperCase(), cls: 'badge--active' }
  if (action === 'decrease' || action === 'close') return { label: action.toUpperCase(), cls: 'badge--error' }
  return                                                  { label: 'HOLD', cls: 'badge--standby' }
}

function pct(v: number | null | undefined): string {
  return Number.isFinite(v as number) ? `${(v as number).toFixed(1)}%` : '—'
}

function savedAtLabel(d: Date | null, isCached: boolean): string {
  if (!d) return ''
  return `${isCached ? 'CACHED' : 'UPDATED'} ${d.toISOString().slice(0, 16).replace('T', ' ')}Z`
}

// ── Period selector state ──────────────────────────────────────────────────

const CURRENT_YEAR = new Date().getFullYear()
const YEARS = Array.from({ length: CURRENT_YEAR - 2023 }, (_, i) => 2024 + i)
const MONTHS = [
  { label: 'JAN', value: 1 },  { label: 'FEB', value: 2 },  { label: 'MAR', value: 3 },
  { label: 'APR', value: 4 },  { label: 'MAY', value: 5 },  { label: 'JUN', value: 6 },
  { label: 'JUL', value: 7 },  { label: 'AUG', value: 8 },  { label: 'SEP', value: 9 },
  { label: 'OCT', value: 10 }, { label: 'NOV', value: 11 }, { label: 'DEC', value: 12 },
]

const mode      = ref<'ytd' | 'single' | 'range'>('ytd')
const fromYear  = ref(CURRENT_YEAR)
const fromMonth = ref(1)
const toYear    = ref(CURRENT_YEAR)
const toMonth   = ref(new Date().getMonth() + 1)
const context   = ref('')

const pad = (n: number) => String(n).padStart(2, '0')

const params = computed((): AnalysisParams => {
  if (mode.value === 'ytd') {
    return { mode: 'ytd', context: context.value }
  }
  if (mode.value === 'single') {
    return {
      mode:        'single',
      period_from: `${fromYear.value}-${pad(fromMonth.value)}`,
      context:     context.value,
    }
  }
  return {
    mode:        'range',
    period_from: `${fromYear.value}-${pad(fromMonth.value)}`,
    period_to:   `${toYear.value}-${pad(toMonth.value)}`,
    context:     context.value,
  }
})

const loadingMessage = computed(() => {
  if (params.value.mode === 'ytd')
    return `Fetching all ${CURRENT_YEAR} statements from MCP and running YTD analysis. This may take 30–90s depending on months available.`
  if (params.value.mode === 'single')
    return `Fetching ${params.value.period_from} from MCP memory...`
  return `Fetching ${params.value.period_from} – ${params.value.period_to} from MCP memory. One search per month.`
})

// ── Trigger ────────────────────────────────────────────────────────────────

function handleRun() {
  runAnalysis(params.value)
}

// ── Formatting helpers ─────────────────────────────────────────────────────

function eur(val: number, showSign = false): string {
  if (!Number.isFinite(val)) return '—'
  const formatted = new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Math.abs(val))
  const prefix = showSign ? (val >= 0 ? '+' : '−') : (val < 0 ? '−' : '')
  return `${prefix}€${formatted}`
}

/** Coerce an LLM-provided value to a finite number, or null. */
function num(val: unknown): number | null {
  const n = typeof val === 'string' ? parseFloat(val) : (val as number)
  return Number.isFinite(n) ? n : null
}

function fmtDate(iso: string): string {
  return iso
}

// ── Budget allocation helper ─────────────────────────────────────────────────

const getProposed = (entry: ProposedAllocation | number): number =>
  typeof entry === 'number' ? entry : entry?.proposed ?? 0

// ── Period label ─────────────────────────────────────────────────────────────

const periodLabel = computed(() => {
  const p = result.value?.meta.analysis_period
  if (!p) return ''
  return typeof p === 'string' ? p : `${(p as AnalysisPeriod).from} — ${(p as AnalysisPeriod).to}`
})

// ── Variance formatter ───────────────────────────────────────────────────────

function formatVariance(delta: number | null): string {
  if (delta === null || !Number.isFinite(delta)) return '—'
  return `${delta >= 0 ? '+' : ''}€${Math.abs(delta).toFixed(2)}`
}

// ── KPI helpers ─────────────────────────────────────────────────────────────

function trajectoryBadge(t: string): { label: string; cls: string } {
  if (t === 'ahead')    return { label: 'AHEAD',    cls: 'badge--active' }
  if (t === 'behind')   return { label: 'BEHIND',   cls: 'badge--error' }
  return                       { label: 'ON TRACK', cls: 'badge--standby' }
}

// ── Spending table ──────────────────────────────────────────────────────────

interface SpendingRow {
  key:      string
  label:    string
  budget:   number | null
  actual:   number
  variance: number | null
  status:   'ok' | 'over' | 'under' | 'tracked'
}

const expandedRows = ref<Set<string>>(new Set())

function toggleRow(key: string) {
  if (expandedRows.value.has(key)) expandedRows.value.delete(key)
  else expandedRows.value.add(key)
}

function hasAnomaly(key: string): boolean {
  return (result.value?.spending_analysis.anomalies ?? [])
    .some(a => a.category === key)
}

function anomalyFor(key: string) {
  return (result.value?.spending_analysis.anomalies ?? [])
    .find(a => a.category === key)
}

function formatCategoryLabel(key: string): string {
  return key.replace(/_/g, ' ').toUpperCase()
}

function statusBadge(s: 'ok' | 'over' | 'under' | 'tracked'): { label: string; cls: string } {
  if (s === 'ok')      return { label: 'OK',      cls: 'badge--active' }
  if (s === 'over')    return { label: 'OVER',     cls: 'badge--error' }
  if (s === 'tracked') return { label: 'STANDBY',  cls: 'badge--standby' }
  return                      { label: 'UNDER',    cls: 'badge--standby' }
}

const spendingRows = computed((): SpendingRow[] => {
  const cats = result.value?.spending_analysis.categories ?? {}
  const rows: SpendingRow[] = Object.entries(cats).map(([k, raw]) => {
    // The LLM occasionally renames fields (budget_eur, spent, variance...).
    // Normalize defensively so a schema drift renders as '—', never €NaN.
    const v = (typeof raw === 'object' && raw !== null ? raw : { actual: raw }) as
      Partial<CategoryBreakdown> & Record<string, unknown>
    const budget = num(v.budget) ?? num(v.budget_eur) ?? num(v.budgeted) ?? null
    const actual = num(v.actual) ?? num(v.actual_eur) ?? num(v.spent) ?? num(v.amount) ?? 0
    const variance = num(v.delta) ?? num(v.variance) ?? num(v.delta_eur)
      ?? (budget !== null ? budget - actual : null)
    const status = (['ok', 'over', 'under', 'tracked'] as const).includes(
      v.status as 'ok' | 'over' | 'under' | 'tracked',
    )
      ? (v.status as 'ok' | 'over' | 'under' | 'tracked')
      : budget === null ? 'tracked' : actual > budget * 1.05 ? 'over' : 'ok'
    return { key: k, label: formatCategoryLabel(k), budget, actual, variance, status }
  })
  const order: Record<string, number> = { over: 0, ok: 1, under: 2, tracked: 3 }
  return rows.sort((a, b) => (order[a.status] ?? 99) - (order[b.status] ?? 99))
})

// ── Budget bars ─────────────────────────────────────────────────────────────

const budgetEntries = computed(() => {
  const allocs = result.value?.budget_next_month.proposed_allocations ?? {}
  const vals   = Object.values(allocs).map(v => getProposed(v))
  const max    = vals.length ? Math.max(...vals) : 1
  return Object.entries(allocs).map(([k, v]) => {
    const amount = getProposed(v)
    return {
      label:     formatCategoryLabel(k),
      key:       k,
      value:     amount,
      pct:       Math.round((amount / max) * 100),
      isSavings: k === 'savings_contribution',
    }
  })
})

// ── Savings opportunities ───────────────────────────────────────────────────

const expandedOpps = ref<Set<number>>(new Set())

function toggleOpp(i: number) {
  if (expandedOpps.value.has(i)) expandedOpps.value.delete(i)
  else expandedOpps.value.add(i)
}

const sortedOpps = computed((): SavingsOpportunity[] => {
  return [...(result.value?.savings_opportunities ?? [])]
    .sort((a, b) => b.annual_saving_eur - a.annual_saving_eur)
})

function fitBadge(score: string): { label: string; cls: string } {
  if (score === 'high')   return { label: 'HIGH',   cls: 'badge--active' }
  if (score === 'medium') return { label: 'MEDIUM', cls: 'badge--processing' }
  return                         { label: 'LOW',    cls: 'badge--standby' }
}

function priorityBadge(p: string): { label: string; cls: string } {
  if (p === 'high')   return { label: 'HIGH', cls: 'badge--error' }
  if (p === 'medium') return { label: 'MED',  cls: 'badge--processing' }
  return                     { label: 'LOW',  cls: 'badge--standby' }
}

// ── Chart.js ────────────────────────────────────────────────────────────────

const chartPieRef   = ref<HTMLCanvasElement | null>(null)
const chartBarRef   = ref<HTMLCanvasElement | null>(null)
const chartLineRef  = ref<HTMLCanvasElement | null>(null)

let chartPie:  Chart | null = null
let chartBar:  Chart | null = null
let chartLine: Chart | null = null

// Resolve a CSS variable value at runtime
function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const PIE_PALETTE = [
  'rgba(74,127,165,0.85)',
  'rgba(74,127,165,0.65)',
  'rgba(74,127,165,0.45)',
  'rgba(196,164,85,0.85)',
  'rgba(196,164,85,0.65)',
  'rgba(196,164,85,0.45)',
  'rgba(62,207,142,0.7)',
  'rgba(240,68,68,0.7)',
  'rgba(245,158,11,0.7)',
]

const CHART_BASE_OPTIONS = {
  responsive:          true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
  },
}

function makeScales() {
  const border     = cssVar('--border')
  const textSecond = cssVar('--text-secondary')
  return {
    x: {
      grid:  { color: `${border}80`, borderColor: 'transparent' },
      ticks: { color: textSecond, font: { family: cssVar('--font-mono'), size: 11 } },
    },
    y: {
      grid:  { color: `${border}80`, borderColor: 'transparent' },
      ticks: { color: textSecond, font: { family: cssVar('--font-mono'), size: 11 } },
    },
  }
}

function destroyCharts() {
  chartPie?.destroy();  chartPie  = null
  chartBar?.destroy();  chartBar  = null
  chartLine?.destroy(); chartLine = null
}

function buildCharts(data: BankAdviserResult) {
  destroyCharts()

  // Doughnut — spending by category
  if (chartPieRef.value) {
    const labels  = data.chart_data.spending_by_category_pie.map(d => d.label)
    const values  = data.chart_data.spending_by_category_pie.map(d => d.value)
    const colors  = values.map((_, i) => PIE_PALETTE[i % PIE_PALETTE.length])
    const cfg: ChartConfiguration<'doughnut'> = {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }],
      },
      options: {
        ...CHART_BASE_OPTIONS,
        plugins: {
          legend:  { display: false },
          tooltip: {
            backgroundColor: cssVar('--bg-elevated'),
            titleColor:      cssVar('--text-primary'),
            bodyColor:       cssVar('--text-secondary'),
            borderColor:     cssVar('--border'),
            borderWidth:     1,
            titleFont:       { family: cssVar('--font-mono'), size: 11 },
            bodyFont:        { family: cssVar('--font-mono'), size: 11 },
            callbacks: {
              label: (ctx) => ` ${ctx.label}: €${ctx.parsed}`,
            },
          },
        },
      },
    }
    chartPie = new Chart(chartPieRef.value, cfg)
  }

  // Bar — income vs expenses
  if (chartBarRef.value) {
    const labels   = data.chart_data.income_vs_expenses_bar.map(d => d.month)
    const incomes  = data.chart_data.income_vs_expenses_bar.map(d => d.income)
    const expenses = data.chart_data.income_vs_expenses_bar.map(d => d.expenses)
    const accent   = cssVar('--accent-primary')
    const muted    = cssVar('--text-secondary')
    const cfg: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Income',   data: incomes,  backgroundColor: accent },
          { label: 'Expenses', data: expenses, backgroundColor: muted  },
        ],
      },
      options: {
        ...CHART_BASE_OPTIONS,
        scales: makeScales(),
        plugins: {
          legend:  { display: false },
          tooltip: {
            backgroundColor: cssVar('--bg-elevated'),
            titleColor:      cssVar('--text-primary'),
            bodyColor:       cssVar('--text-secondary'),
            borderColor:     cssVar('--border'),
            borderWidth:     1,
            titleFont:       { family: cssVar('--font-mono'), size: 11 },
            bodyFont:        { family: cssVar('--font-mono'), size: 11 },
            callbacks: { label: (ctx) => ` €${ctx.parsed.y}` },
          },
        },
      },
    }
    chartBar = new Chart(chartBarRef.value, cfg)
  }

  // Line — savings progress with target annotation
  if (chartLineRef.value) {
    const labels   = data.chart_data.savings_progress_line.map(d => d.month)
    const savings  = data.chart_data.savings_progress_line.map(d => d.cumulative_savings)
    const target   = data.yearly_progress.target_savings_eur
    const accent   = cssVar('--accent-primary')
    const gold     = '#C4A455'

    // Build target as a dataset with a constant value
    const targetLine = labels.map(() => target)

    const cfg: ChartConfiguration<'line'> = {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label:       'Savings YTD',
            data:        savings,
            borderColor: accent,
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: accent,
            fill:        false,
            tension:     0.3,
          },
          {
            label:       'Target',
            data:        targetLine,
            borderColor: gold,
            borderDash:  [5, 5],
            borderWidth: 1.5,
            pointRadius: 0,
            fill:        false,
          },
        ],
      },
      options: {
        ...CHART_BASE_OPTIONS,
        scales: makeScales(),
        plugins: {
          legend:  { display: false },
          tooltip: {
            backgroundColor: cssVar('--bg-elevated'),
            titleColor:      cssVar('--text-primary'),
            bodyColor:       cssVar('--text-secondary'),
            borderColor:     cssVar('--border'),
            borderWidth:     1,
            titleFont:       { family: cssVar('--font-mono'), size: 11 },
            bodyFont:        { family: cssVar('--font-mono'), size: 11 },
            callbacks: { label: (ctx) => ` €${ctx.parsed.y}` },
          },
        },
      },
    }
    chartLine = new Chart(chartLineRef.value, cfg)
  }
}

// Build charts when result arrives (after DOM update)
watch(result, (r) => {
  if (!r) return
  nextTick(() => buildCharts(r))
})

onBeforeUnmount(destroyCharts)
</script>

<template>
  <div class="page">

    <!-- ── 1. Section header ───────────────────────────────────────────── -->
    <header class="page-header">
      <div class="header-left">
        <span class="page-tag">SECTION</span>
        <h1 class="page-title">BANK ADVISER</h1>
      </div>
      <div v-if="lastRun" class="header-meta">
        <span v-if="cached" class="badge badge--standby">CACHED</span>&nbsp;
        LAST ANALYSIS:&nbsp;
        <span class="mono">{{ result?.meta.analysis_date ?? fmtDate(lastRun.toISOString().slice(0,10)) }}</span>
      </div>
    </header>
    <div class="rule" />

    <div class="body">

      <!-- ── 2. Trigger panel ──────────────────────────────────────────── -->
      <div
        class="trigger-card"
        :class="{ 'trigger-card--error': status === 'error' }"
      >
        <div class="period-selector">
          <div class="period-title">ANALYSIS PERIOD</div>

          <div class="period-row">
            <span class="period-label">MODE</span>
            <select class="select-control" v-model="mode">
              <option value="ytd">YTD</option>
              <option value="single">SINGLE MONTH</option>
              <option value="range">RANGE</option>
            </select>
          </div>

          <template v-if="mode !== 'ytd'">
            <div class="period-row">
              <span class="period-label">FROM</span>
              <select class="select-control select-control--sm" v-model="fromYear">
                <option v-for="y in YEARS" :key="y" :value="y">{{ y }}</option>
              </select>
              <select class="select-control select-control--sm" v-model="fromMonth">
                <option v-for="m in MONTHS" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
            </div>

            <div v-if="mode === 'range'" class="period-row">
              <span class="period-label">TO</span>
              <select class="select-control select-control--sm" v-model="toYear">
                <option v-for="y in YEARS" :key="y" :value="y">{{ y }}</option>
              </select>
              <select class="select-control select-control--sm" v-model="toMonth">
                <option v-for="m in MONTHS" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
            </div>
          </template>

          <div class="period-row period-row--context">
            <span class="period-label">CONTEXT<br><span class="period-label--sub">optional</span></span>
            <textarea
              class="context-area"
              v-model="context"
              placeholder="Additional instructions for the agent..."
              rows="2"
            />
          </div>
        </div>

        <div class="trigger-actions">
          <button
            class="btn btn--primary"
            :disabled="status === 'loading'"
            @click="handleRun"
          >
            {{ status === 'loading' ? 'ANALYSING...' : 'RUN ANALYSIS' }}
          </button>
        </div>

        <div v-if="status === 'loading'" class="loading-state">
          <div class="progress-track">
            <div class="progress-fill" />
          </div>
          <p class="loading-hint">{{ loadingMessage }}</p>
        </div>

        <div v-if="status === 'error' && error" class="error-msg">
          {{ error }}
        </div>
      </div>

      <!-- ── 3. Results area ───────────────────────────────────────────── -->
      <template v-if="result">

        <!-- ROW A — KPI cards -->
        <div class="kpi-row">

          <!-- Net savings -->
          <div class="kpi-card">
            <div class="kpi-label">NET SAVINGS THIS PERIOD</div>
            <div
              class="kpi-value"
              :class="result.spending_analysis.net_savings_this_period >= 0
                ? 'kpi-value--positive' : 'kpi-value--negative'"
            >
              {{ eur(result.spending_analysis.net_savings_this_period) }}
            </div>
          </div>

          <!-- Savings YTD / Target -->
          <div class="kpi-card">
            <div class="kpi-label">SAVINGS YTD / TARGET</div>
            <div class="kpi-value kpi-value--neutral">
              {{ eur(result.yearly_progress.savings_ytd) }}
              <span class="kpi-sep">/</span>
              {{ eur(result.yearly_progress.target_savings_eur) }}
            </div>
            <span
              class="badge"
              :class="trajectoryBadge(result.yearly_progress.trajectory).cls"
            >
              {{ trajectoryBadge(result.yearly_progress.trajectory).label }}
            </span>
          </div>

          <!-- Investment signal -->
          <div class="kpi-card">
            <div class="kpi-label">INVESTMENT SIGNAL</div>
            <div class="kpi-value">
              <span
                class="badge badge--large"
                :class="result.investment_signal.ready_to_invest
                  ? 'badge--active' : 'badge--standby'"
              >
                {{ result.investment_signal.ready_to_invest ? 'READY' : 'HOLD' }}
              </span>
            </div>
            <div class="kpi-sublabel">{{ result.investment_signal.note }}</div>
          </div>
        </div>

        <!-- ROW B — Spending analysis table -->
        <div class="section-block">
          <div class="section-label">
            SPENDING ANALYSIS —
            <span class="mono">{{ periodLabel }}</span>
          </div>

          <table class="data-table">
            <thead>
              <tr>
                <th>CATEGORY</th>
                <th class="col-num">BUDGET</th>
                <th class="col-num">ACTUAL</th>
                <th class="col-num">VARIANCE</th>
                <th class="col-status">STATUS</th>
                <th class="col-toggle"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="row in spendingRows" :key="row.key">
                <tr :class="{ 'row--expanded': expandedRows.has(row.key) }">
                  <td class="cell-label">{{ row.label }}</td>
                  <td class="cell-num">
                    {{ row.budget !== null ? eur(row.budget) : '—' }}
                  </td>
                  <td class="cell-num">{{ eur(row.actual) }}</td>
                  <td
                    class="cell-num"
                    :class="row.variance !== null && row.variance > 0 ? 'cell--over' : row.variance !== null && row.variance < 0 ? 'cell--under' : ''"
                  >
                    {{ formatVariance(row.variance) }}
                  </td>
                  <td class="cell-status">
                    <span class="badge" :class="statusBadge(row.status).cls">
                      {{ statusBadge(row.status).label }}
                    </span>
                  </td>
                  <td class="cell-toggle">
                    <button
                      v-if="hasAnomaly(row.key)"
                      class="chevron-btn"
                      :class="{ 'chevron-btn--open': expandedRows.has(row.key) }"
                      @click="toggleRow(row.key)"
                      title="Toggle anomaly detail"
                    >›</button>
                  </td>
                </tr>
                <tr
                  v-if="expandedRows.has(row.key) && anomalyFor(row.key)"
                  class="anomaly-row"
                >
                  <td colspan="6" class="anomaly-cell">
                    <span class="anomaly-severity">
                      {{ anomalyFor(row.key)?.severity.toUpperCase() }}
                    </span>
                    {{ anomalyFor(row.key)?.message }}
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <!-- ROW C — Budget + Recommendations -->
        <div class="two-col">

          <!-- Left: Next month budget -->
          <div class="section-block">
            <div class="section-label">NEXT MONTH BUDGET</div>
            <div class="budget-bars">
              <div
                v-for="entry in budgetEntries"
                :key="entry.key"
                class="budget-row"
                :class="{ 'budget-row--savings': entry.isSavings }"
              >
                <div class="budget-row-label">{{ entry.label }}</div>
                <div class="budget-bar-track">
                  <div class="budget-bar-fill" :style="{ width: entry.pct + '%' }" />
                </div>
                <div class="budget-row-val mono">{{ eur(entry.value) }}</div>
              </div>
            </div>
            <div class="budget-footer">
              PROJECTED NET SAVINGS:
              <span class="mono accent">
                {{ eur(result.budget_next_month.projected_net_savings) }}
              </span>
            </div>
          </div>

          <!-- Right: Recommendations -->
          <div class="section-block">
            <div class="section-label">RECOMMENDATIONS</div>
            <ol class="rec-list">
              <li
                v-for="(rec, i) in result.recommendations"
                :key="i"
                class="rec-item"
              >
                <div class="rec-header">
                  <span class="badge" :class="priorityBadge(rec.priority).cls">
                    {{ priorityBadge(rec.priority).label }}
                  </span>
                  <span class="rec-category mono">{{ rec.category.toUpperCase() }}</span>
                </div>
                <div class="rec-action">{{ rec.action }}</div>
              </li>
            </ol>
          </div>
        </div>

        <!-- ROW D — Savings opportunities -->
        <div class="section-block">
          <div class="section-label">SAVINGS OPPORTUNITIES</div>

          <table class="data-table">
            <thead>
              <tr>
                <th>ITEM</th>
                <th>ALTERNATIVE</th>
                <th class="col-num">/MONTH</th>
                <th class="col-num">/YEAR</th>
                <th>EFFORT</th>
                <th>FIT</th>
                <th>NOTE</th>
                <th class="col-toggle"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="(opp, i) in sortedOpps" :key="i">
                <tr
                  class="opp-row"
                  :class="{ 'row--expanded': expandedOpps.has(i) }"
                  @click="toggleOpp(i)"
                  title="Click to expand trade-off / prerequisite"
                >
                  <td class="cell-label mono">{{ opp.current_item }}</td>
                  <td>{{ opp.alternative }}</td>
                  <td class="cell-num mono">{{ eur(opp.monthly_saving_eur) }}</td>
                  <td class="cell-num mono">{{ eur(opp.annual_saving_eur) }}</td>
                  <td class="cell-muted">{{ opp.effort }}</td>
                  <td>
                    <span class="badge" :class="fitBadge(opp.adel_fit_score).cls">
                      {{ fitBadge(opp.adel_fit_score).label }}
                    </span>
                  </td>
                  <td class="cell-note">{{ opp.note }}</td>
                  <td class="cell-toggle">
                    <span
                      class="chevron-btn"
                      :class="{ 'chevron-btn--open': expandedOpps.has(i) }"
                    >›</span>
                  </td>
                </tr>
                <tr v-if="expandedOpps.has(i)" class="anomaly-row">
                  <td colspan="8" class="anomaly-cell">
                    <div v-if="opp.prerequisite" class="opp-detail-line">
                      <span class="opp-detail-key">PREREQUISITE</span>
                      {{ opp.prerequisite }}
                    </div>
                    <div v-if="opp.trade_off" class="opp-detail-line">
                      <span class="opp-detail-key">TRADE-OFF</span>
                      {{ opp.trade_off }}
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <!-- ROW E — Agent reasoning -->
        <div v-if="result.reasoning" class="section-block">
          <div class="section-label">AGENT REASONING</div>
          <textarea
            class="reasoning-area"
            readonly
            :value="result.reasoning"
            rows="5"
          />
        </div>

        <!-- ROW F — Charts -->
        <div class="section-block">
          <div class="charts-grid">

            <div class="chart-block">
              <div class="chart-label">SPENDING BY CATEGORY</div>
              <div class="chart-wrap">
                <canvas ref="chartPieRef" />
              </div>
            </div>

            <div class="chart-block">
              <div class="chart-label">INCOME VS EXPENSES</div>
              <div class="chart-wrap">
                <canvas ref="chartBarRef" />
              </div>
            </div>

            <div class="chart-block">
              <div class="chart-label">SAVINGS PROGRESS</div>
              <div class="chart-wrap">
                <canvas ref="chartLineRef" />
              </div>
            </div>

          </div>
        </div>

      </template>

      <!-- ── 4. Investment recommendations ─────────────────────────────── -->
      <div class="rule rule--gap" />
      <div class="adv-header">
        <div class="header-left">
          <span class="page-tag">SECTION</span>
          <h2 class="page-title">INVESTMENT RECOMMENDATIONS</h2>
        </div>
        <div class="adv-header-actions">
          <span v-if="invSavedAt" class="header-meta mono">{{ savedAtLabel(invSavedAt, invCached) }}</span>
          <button
            class="btn btn--primary"
            :disabled="invStatus === 'loading'"
            @click="runInvesting"
          >
            {{ invStatus === 'loading' ? 'ANALYSING...' : invResult ? 'REFRESH' : 'RUN ANALYSIS' }}
          </button>
        </div>
      </div>

      <div v-if="invStatus === 'loading' && !invResult" class="loading-state">
        <div class="progress-track"><div class="progress-fill" /></div>
        <p class="loading-hint">Reading Trading 212 strategy from MCP memory and building allocation recommendation...</p>
      </div>
      <div v-if="invStatus === 'error' && invError" class="error-msg">{{ invError }}</div>
      <p v-if="invStatus === 'idle' && !invResult" class="adv-empty">
        No investment analysis yet. Upload your Trading 212 strategy to MCP memory, then run the analysis.
      </p>

      <template v-if="invResult">
        <div class="kpi-row">
          <div class="kpi-card kpi-card--wide">
            <div class="kpi-label">STRATEGY</div>
            <div class="kpi-sublabel">{{ invResult.current_status.strategy_summary }}</div>
            <div class="kpi-sublabel kpi-sublabel--muted">{{ invResult.current_status.data_freshness }}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">PORTFOLIO VALUE</div>
            <div class="kpi-value kpi-value--neutral">
              {{ invResult.current_status.portfolio_value_eur != null ? eur(invResult.current_status.portfolio_value_eur) : '—' }}
            </div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">SUGGESTED MONTHLY CONTRIBUTION</div>
            <div class="kpi-value kpi-value--neutral">
              {{ invResult.monthly_contribution_eur != null ? eur(invResult.monthly_contribution_eur) : '—' }}
            </div>
          </div>
        </div>

        <div v-if="invResult.current_status.holdings.length" class="section-block">
          <div class="section-label">CURRENT HOLDINGS</div>
          <table class="data-table">
            <thead>
              <tr>
                <th>NAME</th><th>TICKER</th><th>TYPE</th>
                <th class="col-num">ALLOCATION</th><th class="col-num">VALUE</th><th>NOTE</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(h, i) in invResult.current_status.holdings" :key="i">
                <td class="cell-label">{{ h.name }}</td>
                <td class="mono">{{ h.ticker ?? '—' }}</td>
                <td class="cell-muted">{{ h.type ?? '—' }}</td>
                <td class="cell-num mono">{{ pct(h.allocation_pct) }}</td>
                <td class="cell-num mono">{{ h.value_eur != null ? eur(h.value_eur) : '—' }}</td>
                <td class="cell-note">{{ h.note ?? '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="section-block">
          <div class="section-label">ALLOCATION RECOMMENDATION</div>
          <table class="data-table">
            <thead>
              <tr>
                <th>ASSET</th><th>TICKER</th>
                <th class="col-num">CURRENT</th><th class="col-num">TARGET</th>
                <th>ACTION</th><th>RATIONALE</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(a, i) in invResult.allocation_recommendation" :key="i">
                <td class="cell-label">{{ a.asset }}</td>
                <td class="mono">{{ a.ticker ?? '—' }}</td>
                <td class="cell-num mono">{{ pct(a.current_pct) }}</td>
                <td class="cell-num mono">{{ pct(a.target_pct) }}</td>
                <td>
                  <span class="badge" :class="allocActionBadge(a.action).cls">
                    {{ allocActionBadge(a.action).label }}
                  </span>
                </td>
                <td class="cell-note">{{ a.rationale }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="invResult.notes.length" class="section-block">
          <div class="section-label">NOTES</div>
          <ul class="adv-notes">
            <li v-for="(n, i) in invResult.notes" :key="i">{{ n }}</li>
          </ul>
        </div>

        <div v-if="invResult.reasoning" class="section-block">
          <div class="section-label">AGENT REASONING</div>
          <textarea class="reasoning-area" readonly :value="invResult.reasoning" rows="4" />
        </div>
      </template>

      <!-- ── 5. Day trading desk ───────────────────────────────────────── -->
      <div class="rule rule--gap" />
      <div class="adv-header">
        <div class="header-left">
          <span class="page-tag">SECTION</span>
          <h2 class="page-title">DAY TRADING DESK</h2>
        </div>
        <div class="adv-header-actions">
          <span v-if="dtSavedAt" class="header-meta mono">{{ savedAtLabel(dtSavedAt, dtCached) }}</span>
          <button
            class="btn btn--primary"
            :disabled="dtStatus === 'loading'"
            @click="runDayTrading"
          >
            {{ dtStatus === 'loading' ? 'ANALYSING...' : dtResult ? 'REFRESH' : 'RUN ANALYSIS' }}
          </button>
        </div>
      </div>

      <div v-if="dtStatus === 'loading' && !dtResult" class="loading-state">
        <div class="progress-track"><div class="progress-fill" /></div>
        <p class="loading-hint">Fetching live quotes and headlines (Yahoo Finance, Bloomberg, The Economist, Google Finance) and analysing US / EU / SE-Asian markets...</p>
      </div>
      <div v-if="dtStatus === 'error' && dtError" class="error-msg">{{ dtError }}</div>
      <p v-if="dtStatus === 'idle' && !dtResult" class="adv-empty">
        No day trading analysis yet. Run one to fetch a live market snapshot and get buy/hold/sell calls.
      </p>

      <template v-if="dtResult">
        <div class="region-grid">
          <div
            v-for="(regionKey, ) in (['us', 'europe', 'southeast_asia'] as TradeMarket[])"
            :key="regionKey"
            class="region-card"
          >
            <div class="section-label">{{ MARKET_LABELS[regionKey] }}</div>
            <div
              v-for="idx in dtResult.market_overview[regionKey]?.indices ?? []"
              :key="idx.symbol"
              class="idx-row"
            >
              <span class="idx-name">{{ idx.name }}</span>
              <span class="mono">{{ idx.price != null ? idx.price.toLocaleString('de-DE') : '—' }}</span>
              <span
                class="mono idx-change"
                :class="(idx.change_pct ?? 0) >= 0 ? 'idx-change--up' : 'idx-change--down'"
              >
                {{ idx.change_pct != null ? `${idx.change_pct >= 0 ? '+' : ''}${idx.change_pct.toFixed(2)}%` : '—' }}
              </span>
            </div>
            <p class="region-summary">{{ dtResult.market_overview[regionKey]?.summary }}</p>
          </div>
        </div>

        <div class="section-block">
          <div class="section-label">RECOMMENDATIONS — {{ dtResult.analysis_date }}</div>
          <table class="data-table">
            <thead>
              <tr>
                <th>TICKER</th><th>NAME</th><th>MARKET</th>
                <th>ACTION</th><th>CONFIDENCE</th><th>HELD SINCE</th><th>RATIONALE</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in dtResult.recommendations" :key="i">
                <td class="cell-label mono">{{ r.ticker }}</td>
                <td>{{ r.name }}</td>
                <td class="cell-muted">{{ MARKET_LABELS[r.market] ?? r.market }}</td>
                <td>
                  <span class="badge" :class="tradeActionBadge(r.action).cls">
                    {{ tradeActionBadge(r.action).label }}
                  </span>
                </td>
                <td>
                  <span class="badge" :class="fitBadge(r.confidence).cls">
                    {{ fitBadge(r.confidence).label }}
                  </span>
                </td>
                <td class="mono cell-muted">{{ r.held_since ?? '—' }}</td>
                <td class="cell-note">{{ r.rationale }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="dtResult.changes_since_last" class="section-block">
          <div class="section-label">CHANGES SINCE LAST ANALYSIS</div>
          <p class="adv-text">{{ dtResult.changes_since_last }}</p>
        </div>

        <div class="section-block">
          <div class="adv-meta-line">
            <span class="adv-meta-key">SOURCES</span>
            {{ dtResult.sources_used.join(' · ') }}
            <template v-if="dtMeta?.sources_failed?.length">
              <span class="adv-meta-key adv-meta-key--failed">UNAVAILABLE</span>
              {{ dtMeta.sources_failed.join(' · ') }}
            </template>
          </div>
          <div class="adv-meta-line adv-meta-line--risk">
            <span class="adv-meta-key">RISK</span>{{ dtResult.risk_note }}
          </div>
        </div>

        <div v-if="dtResult.reasoning" class="section-block">
          <div class="section-label">AGENT REASONING</div>
          <textarea class="reasoning-area" readonly :value="dtResult.reasoning" rows="4" />
        </div>
      </template>

    </div><!-- /body -->
  </div><!-- /page -->
</template>

<style scoped>
/* ── Page shell ─────────────────────────────────────────────────────── */
.page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* ── Header ─────────────────────────────────────────────────────────── */
.page-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 28px 32px 24px;
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 16px;
}

.page-tag {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.14em;
  color: var(--text-muted);
  border: 1px solid var(--border);
  padding: 2px 6px;
}

.page-title {
  font-family: var(--font-mono);
  font-size: 18px;
  letter-spacing: 0.07em;
  color: var(--text-primary);
}

.header-meta {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.09em;
  color: var(--text-muted);
}

/* ── Dividers ───────────────────────────────────────────────────────── */
.rule {
  height: 1px;
  background: var(--border);
}

/* ── Body ───────────────────────────────────────────────────────────── */
.body {
  padding: 28px 32px 48px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

/* ── Trigger card ───────────────────────────────────────────────────── */
.trigger-card {
  border: 1px solid var(--border);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--bg-surface);
  transition: border-color 0.15s, max-height 0.3s, opacity 0.3s, padding 0.3s;
  overflow: hidden;
}

.trigger-card--error {
  border-color: var(--status-error);
}

.trigger-card--hidden {
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
  opacity: 0;
  border-color: transparent;
  pointer-events: none;
}

/* ── Period selector ────────────────────────────────────────────────── */
.period-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 4px;
}

.period-title {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.14em;
  color: var(--text-muted);
  margin-bottom: 2px;
}

.period-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.period-row--context {
  align-items: flex-start;
}

.period-label {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  width: 68px;
  flex-shrink: 0;
  line-height: 1.4;
}

.period-label--sub {
  font-size: 8px;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  opacity: 0.7;
}

.select-control {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--text-primary);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 0;
  padding: 5px 8px;
  cursor: pointer;
  appearance: auto;
}

.select-control--sm {
  padding: 5px 6px;
}

.select-control:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.context-area {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--text-primary);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 0;
  padding: 7px 10px;
  resize: vertical;
  min-height: 44px;
}

.context-area:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.context-area::placeholder {
  color: var(--text-muted);
  opacity: 0.7;
}

/* ── Trigger button ─────────────────────────────────────────────────── */
.trigger-actions {
  display: flex;
  align-items: center;
}

.btn {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 8px 20px;
  cursor: pointer;
  border: 1px solid transparent;
  border-radius: 0;
  transition: background 0.12s, opacity 0.12s;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn--primary {
  background: var(--accent-primary);
  color: var(--bg-base);
  border-color: var(--accent-primary);
}

.btn--primary:hover:not(:disabled) {
  background: #588fb6;
  border-color: #588fb6;
}

/* ── Progress bar ───────────────────────────────────────────────────── */
.loading-state {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-track {
  height: 2px;
  background: var(--bg-elevated);
  position: relative;
  overflow: hidden;
}

.progress-fill {
  position: absolute;
  top: 0;
  height: 100%;
  background: var(--accent-primary);
  animation: sweep 1.8s ease-in-out infinite;
}

@keyframes sweep {
  0%   { left: 0%;   width: 0%   }
  50%  { left: 0%;   width: 100% }
  100% { left: 100%; width: 0%   }
}

.loading-hint {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

/* ── Error message ──────────────────────────────────────────────────── */
.error-msg {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--status-error);
  letter-spacing: 0.04em;
}

/* ── Badges ─────────────────────────────────────────────────────────── */
.badge {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  padding: 2px 5px;
  border: 1px solid;
  white-space: nowrap;
}

.badge--large {
  font-size: 14px;
  padding: 4px 10px;
}

.badge--active     { color: var(--status-active);     border-color: var(--status-active);     }
.badge--error      { color: var(--status-error);      border-color: var(--status-error);      }
.badge--standby    { color: var(--status-standby);    border-color: var(--status-standby);    }
.badge--processing { color: var(--status-processing); border-color: var(--status-processing); }

/* ── KPI row ────────────────────────────────────────────────────────── */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.kpi-card {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.kpi-label {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--text-muted);
}

.kpi-value {
  font-family: var(--font-mono);
  font-size: 26px;
  font-weight: 500;
  letter-spacing: -0.01em;
  line-height: 1;
}

.kpi-value--positive { color: var(--status-active); }
.kpi-value--negative { color: var(--status-error);  }
.kpi-value--neutral  { color: var(--text-primary);  }

.kpi-sep {
  color: var(--text-muted);
  font-size: 18px;
  margin: 0 4px;
}

.kpi-sublabel {
  font-family: var(--font-sans);
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* ── Section blocks ─────────────────────────────────────────────────── */
.section-block {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.section-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--text-secondary);
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

/* ── Data table ─────────────────────────────────────────────────────── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: 11px;
}

.data-table th {
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  font-weight: 400;
}

.data-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
  vertical-align: middle;
}

.data-table tbody tr:last-child td {
  border-bottom: none;
}

.data-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.02);
}

.row--expanded td {
  background: rgba(74, 127, 165, 0.04);
}

.col-num     { text-align: right; }
.col-status  { text-align: center; }
.col-toggle  { width: 28px; text-align: center; }

.cell-label  { color: var(--text-primary); }
.cell-num    { text-align: right; font-family: var(--font-mono); }
.cell-status { text-align: center; }
.cell-toggle { text-align: center; }
.cell-muted  { color: var(--text-muted); }
.cell-note   { color: var(--text-secondary); font-style: italic; font-size: 10px; }

.cell--over  { color: var(--status-error); }
.cell--under { color: var(--status-active); }

/* ── Anomaly / expand rows ──────────────────────────────────────────── */
.anomaly-row td {
  border-bottom: 1px solid var(--border);
}

.anomaly-cell {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 8px 16px 10px 24px !important;
  color: var(--text-secondary);
  background: rgba(240, 68, 68, 0.04);
}

.anomaly-severity {
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--status-processing);
  margin-right: 8px;
}

/* ── Chevron button ─────────────────────────────────────────────────── */
.chevron-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  padding: 0 4px;
  display: inline-block;
  transition: transform 0.15s, color 0.12s;
  transform: rotate(0deg);
  line-height: 1;
}

.chevron-btn--open {
  transform: rotate(90deg);
  color: var(--accent-primary);
}

/* ── Two-column layout ──────────────────────────────────────────────── */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

/* ── Budget bars ────────────────────────────────────────────────────── */
.budget-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.budget-row {
  display: grid;
  grid-template-columns: 180px 1fr 80px;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}

.budget-row--savings {
  border: 1px solid var(--accent-primary);
  padding: 4px 8px;
  margin: 2px 0;
}

.budget-row-label {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.budget-bar-track {
  height: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  position: relative;
}

.budget-bar-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--accent-primary);
}

.budget-row--savings .budget-bar-fill {
  background: var(--accent-primary);
}

.budget-row-val {
  font-size: 10px;
  color: var(--text-primary);
  text-align: right;
}

.budget-footer {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.accent { color: var(--accent-primary); }

/* ── Recommendations ────────────────────────────────────────────────── */
.rec-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rec-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  background: var(--bg-surface);
}

.rec-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rec-category {
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
}

.rec-action {
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.5;
}

/* ── Savings opp table ──────────────────────────────────────────────── */
.opp-row {
  cursor: pointer;
}

.opp-row:hover {
  background: rgba(255, 255, 255, 0.025);
}

.opp-detail-line {
  margin-bottom: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
}

.opp-detail-key {
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  margin-right: 8px;
}

/* ── Charts grid ────────────────────────────────────────────────────── */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.chart-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chart-label {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--text-muted);
}

.chart-wrap {
  height: 220px;
  background: transparent;
  position: relative;
}

.chart-wrap canvas {
  width: 100% !important;
  height: 100% !important;
}

/* ── Agent reasoning ────────────────────────────────────────────────── */
.reasoning-area {
  width: 100%;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.7;
  letter-spacing: 0.03em;
  color: var(--text-secondary);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 0;
  padding: 14px 16px;
  resize: vertical;
  box-sizing: border-box;
}

.reasoning-area:focus {
  outline: none;
}

/* ── Advisory sections (investments / day trading) ──────────────────── */
.rule--gap {
  margin-top: 32px;
}

.adv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 0 14px;
}

.adv-header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.adv-empty {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.05em;
  color: var(--text-muted, var(--text-secondary));
  padding: 6px 0 18px;
}

.kpi-card--wide {
  grid-column: span 1;
}

.kpi-sublabel--muted {
  opacity: 0.6;
  margin-top: 6px;
}

.adv-notes {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-secondary);
}

.adv-text {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0;
}

.region-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

@media (max-width: 1100px) {
  .region-grid { grid-template-columns: 1fr; }
}

.region-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  padding: 14px 16px;
}

.idx-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 12px;
  font-size: 11px;
  padding: 4px 0;
  color: var(--text-secondary);
}

.idx-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.idx-change--up   { color: var(--status-active); }
.idx-change--down { color: var(--status-error); }

.region-summary {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin: 10px 0 0;
  opacity: 0.85;
}

.adv-meta-line {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.05em;
  line-height: 1.8;
  color: var(--text-secondary);
}

.adv-meta-line--risk {
  margin-top: 8px;
  opacity: 0.75;
}

.adv-meta-key {
  display: inline-block;
  margin-right: 10px;
  padding: 1px 6px;
  border: 1px solid var(--border);
  color: var(--text-muted, var(--text-secondary));
}

.adv-meta-key--failed {
  margin-left: 14px;
  color: var(--status-error);
}

/* ── Utilities ──────────────────────────────────────────────────────── */
.mono { font-family: var(--font-mono); }
</style>
