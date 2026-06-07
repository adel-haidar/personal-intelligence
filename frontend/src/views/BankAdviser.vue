<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
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

// ── Composable ─────────────────────────────────────────────────────────────

const { status, result, error, lastRun, runAnalysis } = useBankAdviser()

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
  const formatted = new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Math.abs(val))
  const prefix = showSign ? (val >= 0 ? '+' : '−') : (val < 0 ? '−' : '')
  return `${prefix}€${formatted}`
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
  if (delta === null) return '—'
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
  const rows: SpendingRow[] = Object.entries(cats).map(([k, v]: [string, CategoryBreakdown]) => ({
    key:      k,
    label:    formatCategoryLabel(k),
    budget:   v.budget,
    actual:   v.actual,
    variance: v.delta,
    status:   v.status,
  }))
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

/* ── Utilities ──────────────────────────────────────────────────────── */
.mono { font-family: var(--font-mono); }
</style>
