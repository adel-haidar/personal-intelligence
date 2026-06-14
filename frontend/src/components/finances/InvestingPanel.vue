<script setup lang="ts">
import { onMounted } from 'vue'
import PiCard from '../ui/PiCard.vue'
import PiButton from '../ui/PiButton.vue'
import Badge from '../ui/Badge.vue'
import Collapse from '../ui/Collapse.vue'
import { useInvesting } from '../../composables/useAdvisory'

const { status, result, savedAt, cached, error, run, loadLatest } = useInvesting()
onMounted(loadLatest)

type BadgeVariant = 'success' | 'danger' | 'amber' | 'outlined'

function eur(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `€${new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 }).format(v)}`
}
function pct(v: number | null | undefined): string { return Number.isFinite(v as number) ? `${(v as number).toFixed(1)}%` : '—' }
function savedLabel(d: Date | null, isCached: boolean): string {
  if (!d) return ''
  return `${isCached ? 'Cached' : 'Updated'} ${d.toLocaleDateString()}`
}
function allocBadge(action: string): { label: string; variant: BadgeVariant } {
  if (action === 'increase' || action === 'open') return { label: action.toUpperCase(), variant: 'success' }
  if (action === 'decrease' || action === 'close') return { label: action.toUpperCase(), variant: 'danger' }
  return { label: 'HOLD', variant: 'amber' }
}
</script>

<template>
  <div>
    <div class="fin-runbar">
      <div style="display: flex; align-items: center; gap: var(--space-3);">
        <span class="fin-runbar__meta" v-if="savedAt">{{ savedLabel(savedAt, cached) }}</span>
      </div>
      <PiButton variant="primary" :loading="status === 'loading'" @click="run">{{ result ? 'Refresh' : 'Run analysis' }}</PiButton>
    </div>

    <PiCard v-if="status === 'loading' && !result" style="margin-bottom: var(--space-5);">
      <div class="pi-progress pi-progress--thin"><div class="pi-progress__track"><div class="pi-progress__fill" style="width: 40%;" /></div></div>
      <p class="t-secondary" style="font-size: var(--text-sm); margin-top: var(--space-3);">Reading your investing strategy from memory and building an allocation recommendation…</p>
    </PiCard>
    <PiCard v-if="status === 'error' && error" style="border-color: var(--danger); margin-bottom: var(--space-5);">
      <span style="color: var(--danger); font-size: var(--text-sm);">{{ error }}</span>
    </PiCard>
    <p v-if="status === 'idle' && !result" class="fin-empty">
      No investment analysis yet. Upload your portfolio / strategy to your brain, then run the analysis.
    </p>

    <template v-if="result">
      <div class="fin-kpi-grid">
        <PiCard>
          <div class="fin-kpi__label">Strategy</div>
          <div class="fin-kpi__sub">{{ result.current_status.strategy_summary }}</div>
          <div class="fin-kpi__sub fin-muted" style="margin-top: 4px;">{{ result.current_status.data_freshness }}</div>
        </PiCard>
        <PiCard>
          <div class="fin-kpi__label">Portfolio value</div>
          <div class="fin-kpi__value"><span class="t-mono">{{ eur(result.current_status.portfolio_value_eur) }}</span></div>
        </PiCard>
        <PiCard>
          <div class="fin-kpi__label">Suggested monthly contribution</div>
          <div class="fin-kpi__value"><span class="t-mono">{{ eur(result.monthly_contribution_eur) }}</span></div>
        </PiCard>
      </div>

      <div v-if="result.current_status.holdings.length" class="fin-section">
        <div class="fin-section__title">Current holdings</div>
        <div class="fin-table-wrap">
          <table class="fin-table">
            <thead>
              <tr><th>Name</th><th>Ticker</th><th>Type</th><th class="fin-th-num">Allocation</th><th class="fin-th-num">Value</th><th>Note</th></tr>
            </thead>
            <tbody>
              <tr v-for="(h, i) in result.current_status.holdings" :key="i">
                <td class="fin-cell-strong">{{ h.name }}</td>
                <td class="t-mono">{{ h.ticker ?? '—' }}</td>
                <td class="fin-muted">{{ h.type ?? '—' }}</td>
                <td class="fin-num">{{ pct(h.allocation_pct) }}</td>
                <td class="fin-num">{{ eur(h.value_eur) }}</td>
                <td class="fin-note">{{ h.note ?? '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="fin-section">
        <div class="fin-section__title">Allocation recommendation</div>
        <div class="fin-table-wrap">
          <table class="fin-table">
            <thead>
              <tr><th>Asset</th><th>Ticker</th><th class="fin-th-num">Current</th><th class="fin-th-num">Target</th><th>Action</th><th>Rationale</th></tr>
            </thead>
            <tbody>
              <tr v-for="(a, i) in result.allocation_recommendation" :key="i">
                <td class="fin-cell-strong">{{ a.asset }}</td>
                <td class="t-mono">{{ a.ticker ?? '—' }}</td>
                <td class="fin-num">{{ pct(a.current_pct) }}</td>
                <td class="fin-num">{{ pct(a.target_pct) }}</td>
                <td><Badge :variant="allocBadge(a.action).variant">{{ allocBadge(a.action).label }}</Badge></td>
                <td class="fin-note">{{ a.rationale }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="result.notes.length" class="fin-section">
        <div class="fin-section__title">Notes</div>
        <ul class="fin-notes"><li v-for="(n, i) in result.notes" :key="i">{{ n }}</li></ul>
      </div>

      <PiCard v-if="result.reasoning">
        <Collapse label="Agent reasoning">
          <p class="fin-reasoning">{{ result.reasoning }}</p>
        </Collapse>
      </PiCard>
    </template>
  </div>
</template>
