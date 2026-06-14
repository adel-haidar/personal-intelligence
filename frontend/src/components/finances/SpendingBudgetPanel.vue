<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import {
  Chart,
  ArcElement, DoughnutController,
  BarElement, BarController,
  LineElement, PointElement, LineController,
  CategoryScale, LinearScale, Tooltip,
  type ChartConfiguration,
} from 'chart.js'
import PiCard from '../ui/PiCard.vue'
import Badge from '../ui/Badge.vue'
import PIIcon from '../ui/PIIcon.vue'
import Collapse from '../ui/Collapse.vue'
import type {
  BankAdviserResult, AnalysisPeriod, CategoryBreakdown, ProposedAllocation,
  SavingsOpportunity,
} from '../../composables/useBankAdviser'

Chart.register(
  ArcElement, DoughnutController, BarElement, BarController,
  LineElement, PointElement, LineController, CategoryScale, LinearScale, Tooltip,
)

const props = defineProps<{ result: BankAdviserResult }>()

type BadgeVariant = 'success' | 'danger' | 'amber' | 'warning' | 'outlined' | 'filled'

// ── Formatting ────────────────────────────────────────────────────────────────
function eur(val: number, showSign = false): string {
  if (!Number.isFinite(val)) return '—'
  const formatted = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(Math.abs(val))
  const prefix = showSign ? (val >= 0 ? '+' : '−') : (val < 0 ? '−' : '')
  return `${prefix}€${formatted}`
}
function num(val: unknown): number | null {
  const n = typeof val === 'string' ? parseFloat(val) : (val as number)
  return Number.isFinite(n) ? n : null
}
const getProposed = (entry: ProposedAllocation | number): number =>
  typeof entry === 'number' ? entry : entry?.proposed ?? 0
function formatCategoryLabel(key: string): string { return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) }
function formatVariance(d: number | null): string {
  if (d === null || !Number.isFinite(d)) return '—'
  return `${d >= 0 ? '+' : '−'}€${Math.abs(d).toFixed(2)}`
}

const periodLabel = computed(() => {
  const p = props.result.meta.analysis_period
  if (!p) return ''
  return typeof p === 'string' ? p : `${(p as AnalysisPeriod).from} — ${(p as AnalysisPeriod).to}`
})

// ── Badges ────────────────────────────────────────────────────────────────────
function statusBadge(s: 'ok' | 'over' | 'under' | 'tracked'): { label: string; variant: BadgeVariant } {
  if (s === 'ok')      return { label: 'OK',      variant: 'success' }
  if (s === 'over')    return { label: 'Over',    variant: 'danger' }
  if (s === 'tracked') return { label: 'Tracked', variant: 'amber' }
  return                      { label: 'Under',   variant: 'outlined' }
}
function trajectoryBadge(t: string): { label: string; variant: BadgeVariant } {
  if (t === 'ahead')  return { label: 'Ahead',    variant: 'success' }
  if (t === 'behind') return { label: 'Behind',   variant: 'danger' }
  return                     { label: 'On track', variant: 'amber' }
}
function priorityBadge(p: string): { label: string; variant: BadgeVariant } {
  if (p === 'high')   return { label: 'High',   variant: 'danger' }
  if (p === 'medium') return { label: 'Medium', variant: 'amber' }
  return                     { label: 'Low',    variant: 'outlined' }
}
function fitBadge(score: string): { label: string; variant: BadgeVariant } {
  if (score === 'high')   return { label: 'High',   variant: 'success' }
  if (score === 'medium') return { label: 'Medium', variant: 'amber' }
  return                         { label: 'Low',    variant: 'outlined' }
}

// ── Spending table ──────────────────────────────────────────────────────────
interface SpendingRow { key: string; label: string; budget: number | null; actual: number; variance: number | null; status: 'ok' | 'over' | 'under' | 'tracked' }
const expandedRows = ref<Set<string>>(new Set())
function toggleRow(k: string) { expandedRows.value.has(k) ? expandedRows.value.delete(k) : expandedRows.value.add(k) }
function anomalyFor(k: string) { return (props.result.spending_analysis.anomalies ?? []).find(a => a.category === k) }
function hasAnomaly(k: string): boolean { return (props.result.spending_analysis.anomalies ?? []).some(a => a.category === k) }

const spendingRows = computed<SpendingRow[]>(() => {
  const cats = props.result.spending_analysis.categories ?? {}
  const rows: SpendingRow[] = Object.entries(cats).map(([k, raw]) => {
    const v = (typeof raw === 'object' && raw !== null ? raw : { actual: raw }) as Partial<CategoryBreakdown> & Record<string, unknown>
    const budget = num(v.budget) ?? num(v.budget_eur) ?? num(v.budgeted) ?? null
    const actual = num(v.actual) ?? num(v.actual_eur) ?? num(v.spent) ?? num(v.amount) ?? 0
    const variance = num(v.delta) ?? num(v.variance) ?? num(v.delta_eur) ?? (budget !== null ? budget - actual : null)
    const status = (['ok', 'over', 'under', 'tracked'] as const).includes(v.status as 'ok' | 'over' | 'under' | 'tracked')
      ? (v.status as 'ok' | 'over' | 'under' | 'tracked')
      : budget === null ? 'tracked' : actual > budget * 1.05 ? 'over' : 'ok'
    return { key: k, label: formatCategoryLabel(k), budget, actual, variance, status }
  })
  const order: Record<string, number> = { over: 0, ok: 1, under: 2, tracked: 3 }
  return rows.sort((a, b) => (order[a.status] ?? 99) - (order[b.status] ?? 99))
})

// ── Budget bars ──────────────────────────────────────────────────────────────
const budgetEntries = computed(() => {
  const allocs = props.result.budget_next_month.proposed_allocations ?? {}
  const vals = Object.values(allocs).map(v => getProposed(v))
  const max = vals.length ? Math.max(...vals) : 1
  return Object.entries(allocs).map(([k, v]) => {
    const amount = getProposed(v)
    return { key: k, label: formatCategoryLabel(k), value: amount, pct: Math.round((amount / max) * 100), isSavings: k === 'savings_contribution' }
  })
})

// ── Savings opportunities ─────────────────────────────────────────────────────
const expandedOpps = ref<Set<number>>(new Set())
function toggleOpp(i: number) { expandedOpps.value.has(i) ? expandedOpps.value.delete(i) : expandedOpps.value.add(i) }
const sortedOpps = computed<SavingsOpportunity[]>(() =>
  [...(props.result.savings_opportunities ?? [])].sort((a, b) => b.annual_saving_eur - a.annual_saving_eur),
)

// ── Charts ────────────────────────────────────────────────────────────────────
const chartPieRef  = ref<HTMLCanvasElement | null>(null)
const chartBarRef  = ref<HTMLCanvasElement | null>(null)
const chartLineRef = ref<HTMLCanvasElement | null>(null)
let chartPie: Chart | null = null
let chartBar: Chart | null = null
let chartLine: Chart | null = null

function cssVar(name: string): string { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() }
function tooltipDefaults() {
  return {
    backgroundColor: cssVar('--background-raised'), titleColor: cssVar('--text-primary'),
    bodyColor: cssVar('--text-secondary'), borderColor: cssVar('--border-subtle'), borderWidth: 1,
    titleFont: { family: cssVar('--font-mono'), size: 11 }, bodyFont: { family: cssVar('--font-mono'), size: 11 },
  }
}
function makeScales() {
  const border = cssVar('--border-subtle'); const text2 = cssVar('--text-secondary')
  return {
    x: { grid: { color: `${border}80`, borderColor: 'transparent' }, ticks: { color: text2, font: { family: cssVar('--font-mono'), size: 10 } } },
    y: { grid: { color: `${border}80`, borderColor: 'transparent' }, ticks: { color: text2, font: { family: cssVar('--font-mono'), size: 10 } } },
  }
}
const BASE = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }

function destroyCharts() { chartPie?.destroy(); chartPie = null; chartBar?.destroy(); chartBar = null; chartLine?.destroy(); chartLine = null }

function buildCharts() {
  destroyCharts()
  const data = props.result
  const accent = cssVar('--accent-primary'); const amber = cssVar('--brain-amber')
  const success = cssVar('--success'); const danger = cssVar('--danger')
  const info = cssVar('--info'); const tertiary = cssVar('--text-tertiary')
  const palette = [accent, amber, success, info, danger, cssVar('--accent-hover'), cssVar('--warning'), tertiary]

  if (chartPieRef.value) {
    const labels = data.chart_data.spending_by_category_pie.map(d => d.label)
    const values = data.chart_data.spending_by_category_pie.map(d => d.value)
    const cfg: ChartConfiguration<'doughnut'> = {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: values.map((_, i) => palette[i % palette.length]), borderWidth: 0 }] },
      options: { ...BASE, cutout: '62%', plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (ctx) => ` ${ctx.label}: €${ctx.parsed}` } } } },
    }
    chartPie = new Chart(chartPieRef.value, cfg)
  }
  if (chartBarRef.value) {
    const labels = data.chart_data.income_vs_expenses_bar.map(d => d.month)
    const cfg: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: { labels, datasets: [
        { label: 'Income', data: data.chart_data.income_vs_expenses_bar.map(d => d.income), backgroundColor: accent },
        { label: 'Expenses', data: data.chart_data.income_vs_expenses_bar.map(d => d.expenses), backgroundColor: tertiary },
      ] },
      options: { ...BASE, scales: makeScales(), plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (ctx) => ` €${ctx.parsed.y}` } } } },
    }
    chartBar = new Chart(chartBarRef.value, cfg)
  }
  if (chartLineRef.value) {
    const labels = data.chart_data.savings_progress_line.map(d => d.month)
    const savings = data.chart_data.savings_progress_line.map(d => d.cumulative_savings)
    const target = data.yearly_progress.target_savings_eur
    const cfg: ChartConfiguration<'line'> = {
      type: 'line',
      data: { labels, datasets: [
        { label: 'Savings YTD', data: savings, borderColor: accent, borderWidth: 2, pointRadius: 3, pointBackgroundColor: accent, fill: false, tension: 0.3 },
        { label: 'Target', data: labels.map(() => target), borderColor: amber, borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0, fill: false },
      ] },
      options: { ...BASE, scales: makeScales(), plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (ctx) => ` €${ctx.parsed.y}` } } } },
    }
    chartLine = new Chart(chartLineRef.value, cfg)
  }
}

watch(() => props.result, () => nextTick(buildCharts))
onMounted(() => nextTick(buildCharts))
onBeforeUnmount(destroyCharts)
</script>

<template>
  <div>
    <!-- KPI row -->
    <div class="fin-kpi-grid">
      <PiCard>
        <div class="fin-kpi__label">Net savings this period</div>
        <div class="fin-kpi__value" :class="result.spending_analysis.net_savings_this_period >= 0 ? 'fin-kpi__value--pos' : 'fin-kpi__value--neg'">
          {{ eur(result.spending_analysis.net_savings_this_period) }}
        </div>
      </PiCard>
      <PiCard>
        <div class="fin-kpi__label">Savings YTD / target</div>
        <div class="fin-kpi__value">
          <span class="t-mono">{{ eur(result.yearly_progress.savings_ytd) }}</span>
          <span class="fin-kpi__sep">/</span>
          <span class="t-mono">{{ eur(result.yearly_progress.target_savings_eur) }}</span>
        </div>
        <div style="margin-top: var(--space-2);">
          <Badge :variant="trajectoryBadge(result.yearly_progress.trajectory).variant">{{ trajectoryBadge(result.yearly_progress.trajectory).label }}</Badge>
        </div>
      </PiCard>
      <PiCard>
        <div class="fin-kpi__label">Investment signal</div>
        <div style="margin-top: var(--space-2);">
          <Badge :variant="result.investment_signal.ready_to_invest ? 'success' : 'amber'">{{ result.investment_signal.ready_to_invest ? 'Ready' : 'Hold' }}</Badge>
        </div>
        <div class="fin-kpi__sub">{{ result.investment_signal.note }}</div>
      </PiCard>
    </div>

    <!-- Spending analysis table -->
    <div class="fin-section">
      <div class="fin-section__title">Spending analysis <span class="t-mono t-tertiary" style="font-weight: 400; font-size: var(--text-sm);">· {{ periodLabel }}</span></div>
      <div class="fin-table-wrap">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Category</th>
              <th class="fin-th-num">Budget</th>
              <th class="fin-th-num">Actual</th>
              <th class="fin-th-num">Variance</th>
              <th>Status</th>
              <th style="width: 28px;" />
            </tr>
          </thead>
          <tbody>
            <template v-for="row in spendingRows" :key="row.key">
              <tr>
                <td class="fin-cell-strong">{{ row.label }}</td>
                <td class="fin-num">{{ row.budget !== null ? eur(row.budget) : '—' }}</td>
                <td class="fin-num">{{ eur(row.actual) }}</td>
                <td class="fin-num" :class="row.variance !== null && row.variance > 0 ? 'fin-neg' : row.variance !== null && row.variance < 0 ? 'fin-pos' : ''">{{ formatVariance(row.variance) }}</td>
                <td><Badge :variant="statusBadge(row.status).variant">{{ statusBadge(row.status).label }}</Badge></td>
                <td style="text-align: center;">
                  <button v-if="hasAnomaly(row.key)" class="pi-collapse__toggle" style="padding: 0;" :class="expandedRows.has(row.key) ? 'pi-collapse--open' : ''" @click="toggleRow(row.key)" title="Toggle anomaly detail">
                    <span :style="{ display: 'inline-flex', transition: 'transform .15s', transform: expandedRows.has(row.key) ? 'rotate(90deg)' : 'none' }"><PIIcon name="chevronRight" :size="14" /></span>
                  </button>
                </td>
              </tr>
              <tr v-if="expandedRows.has(row.key) && anomalyFor(row.key)" class="fin-anomaly">
                <td colspan="6">
                  <span class="fin-detail-key">{{ anomalyFor(row.key)?.severity }}</span>
                  <span class="fin-note">{{ anomalyFor(row.key)?.message }}</span>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Budget + recommendations -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-6); margin-bottom: var(--space-6);" class="pi-insight-grid">
      <div>
        <div class="fin-section__title">Next month budget</div>
        <div v-for="entry in budgetEntries" :key="entry.key" class="fin-budget-row" :class="{ 'fin-budget-row--savings': entry.isSavings }">
          <div class="fin-budget-label">{{ entry.label }}</div>
          <div class="fin-budget-track"><div class="fin-budget-fill" :style="{ width: entry.pct + '%' }" /></div>
          <div class="fin-budget-val">{{ eur(entry.value) }}</div>
        </div>
        <div class="fin-budget-footer">Projected net savings: <span class="t-mono" style="color: var(--success);">{{ eur(result.budget_next_month.projected_net_savings) }}</span></div>
      </div>
      <div>
        <div class="fin-section__title">Recommendations</div>
        <div style="display: flex; flex-direction: column; gap: var(--space-3);">
          <div v-for="(rec, i) in result.recommendations" :key="i" class="fin-rec">
            <div class="fin-rec__head">
              <Badge :variant="priorityBadge(rec.priority).variant">{{ priorityBadge(rec.priority).label }}</Badge>
              <span class="fin-rec__cat">{{ rec.category }}</span>
            </div>
            <div class="fin-rec__action">{{ rec.action }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Savings opportunities -->
    <div v-if="sortedOpps.length" class="fin-section">
      <div class="fin-section__title">Savings opportunities</div>
      <div class="fin-table-wrap">
        <table class="fin-table">
          <thead>
            <tr>
              <th>Item</th><th>Alternative</th>
              <th class="fin-th-num">/ month</th><th class="fin-th-num">/ year</th>
              <th>Effort</th><th>Fit</th><th style="width: 28px;" />
            </tr>
          </thead>
          <tbody>
            <template v-for="(opp, i) in sortedOpps" :key="i">
              <tr class="fin-row-click" @click="toggleOpp(i)">
                <td class="fin-cell-strong">{{ opp.current_item }}</td>
                <td class="fin-note">{{ opp.alternative }}</td>
                <td class="fin-num">{{ eur(opp.monthly_saving_eur) }}</td>
                <td class="fin-num">{{ eur(opp.annual_saving_eur) }}</td>
                <td class="fin-muted">{{ opp.effort }}</td>
                <td><Badge :variant="fitBadge(opp.adel_fit_score).variant">{{ fitBadge(opp.adel_fit_score).label }}</Badge></td>
                <td style="text-align: center;">
                  <span :style="{ display: 'inline-flex', color: 'var(--text-tertiary)', transition: 'transform .15s', transform: expandedOpps.has(i) ? 'rotate(90deg)' : 'none' }"><PIIcon name="chevronRight" :size="14" /></span>
                </td>
              </tr>
              <tr v-if="expandedOpps.has(i)" class="fin-detail">
                <td colspan="7">
                  <div v-if="opp.prerequisite" class="fin-detail-line"><span class="fin-detail-key">Prerequisite</span>{{ opp.prerequisite }}</div>
                  <div v-if="opp.trade_off" class="fin-detail-line"><span class="fin-detail-key">Trade-off</span>{{ opp.trade_off }}</div>
                  <div v-if="opp.note" class="fin-detail-line"><span class="fin-detail-key">Note</span>{{ opp.note }}</div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Charts -->
    <div class="fin-section">
      <div class="fin-charts">
        <div>
          <div class="fin-chart__label">Spending by category</div>
          <div class="fin-chart__wrap"><canvas ref="chartPieRef" /></div>
        </div>
        <div>
          <div class="fin-chart__label">Income vs expenses</div>
          <div class="fin-chart__wrap"><canvas ref="chartBarRef" /></div>
        </div>
        <div>
          <div class="fin-chart__label">Savings progress</div>
          <div class="fin-chart__wrap"><canvas ref="chartLineRef" /></div>
        </div>
      </div>
    </div>

    <!-- Reasoning -->
    <PiCard v-if="result.reasoning">
      <Collapse label="Agent reasoning">
        <p class="fin-reasoning">{{ result.reasoning }}</p>
      </Collapse>
    </PiCard>
  </div>
</template>
