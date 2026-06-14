<script setup lang="ts">
import { onMounted } from 'vue'
import PiCard from '../ui/PiCard.vue'
import PiButton from '../ui/PiButton.vue'
import Badge from '../ui/Badge.vue'
import Collapse from '../ui/Collapse.vue'
import { useDayTrading } from '../../composables/useAdvisory'
import type { TradeMarket } from '../../composables/useAdvisory'

const { status, result, savedAt, cached, error, snapshotMeta, run, loadLatest } = useDayTrading()
onMounted(loadLatest)

type BadgeVariant = 'success' | 'danger' | 'amber' | 'outlined'

const MARKET_LABELS: Record<TradeMarket, string> = { us: 'US', europe: 'Europe', southeast_asia: 'SE Asia' }
const REGIONS: TradeMarket[] = ['us', 'europe', 'southeast_asia']

function savedLabel(d: Date | null, isCached: boolean): string {
  if (!d) return ''
  return `${isCached ? 'Cached' : 'Updated'} ${d.toLocaleDateString()}`
}
function actionBadge(a: string): { label: string; variant: BadgeVariant } {
  if (a === 'buy')  return { label: 'BUY',  variant: 'success' }
  if (a === 'sell') return { label: 'SELL', variant: 'danger' }
  return { label: 'HOLD', variant: 'amber' }
}
function confBadge(c: string): { label: string; variant: BadgeVariant } {
  if (c === 'high')   return { label: 'High',   variant: 'success' }
  if (c === 'medium') return { label: 'Medium', variant: 'amber' }
  return { label: 'Low', variant: 'outlined' }
}
function fmtChange(v: number | null | undefined): string {
  return v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '—'
}
function fmtPrice(v: number | null | undefined): string {
  return v != null ? v.toLocaleString('de-DE') : '—'
}
</script>

<template>
  <div>
    <div class="fin-runbar">
      <span class="fin-runbar__meta" v-if="savedAt">{{ savedLabel(savedAt, cached) }}</span>
      <PiButton variant="primary" :loading="status === 'loading'" @click="run">{{ result ? 'Refresh' : 'Run analysis' }}</PiButton>
    </div>

    <PiCard v-if="status === 'loading' && !result" style="margin-bottom: var(--space-5);">
      <div class="pi-progress pi-progress--thin"><div class="pi-progress__track"><div class="pi-progress__fill" style="width: 40%;" /></div></div>
      <p class="t-secondary" style="font-size: var(--text-sm); margin-top: var(--space-3);">Fetching live quotes and headlines, then analysing US / EU / SE-Asian markets…</p>
    </PiCard>
    <PiCard v-if="status === 'error' && error" style="border-color: var(--danger); margin-bottom: var(--space-5);">
      <span style="color: var(--danger); font-size: var(--text-sm);">{{ error }}</span>
    </PiCard>
    <p v-if="status === 'idle' && !result" class="fin-empty">
      No day-trading analysis yet. Run one to fetch a live market snapshot and get buy / hold / sell calls.
    </p>

    <template v-if="result">
      <div class="fin-region-grid">
        <PiCard v-for="region in REGIONS" :key="region">
          <div class="fin-section__title" style="font-size: var(--text-sm); margin-bottom: var(--space-3);">{{ MARKET_LABELS[region] }}</div>
          <div v-for="idx in result.market_overview[region]?.indices ?? []" :key="idx.symbol" class="fin-idx-row">
            <span class="fin-idx-name">{{ idx.name }}</span>
            <span class="t-mono">{{ fmtPrice(idx.price) }}</span>
            <span class="t-mono" :class="(idx.change_pct ?? 0) >= 0 ? 'fin-pos' : 'fin-neg'">{{ fmtChange(idx.change_pct) }}</span>
          </div>
          <p class="fin-region-summary">{{ result.market_overview[region]?.summary }}</p>
        </PiCard>
      </div>

      <div class="fin-section">
        <div class="fin-section__title">Recommendations <span class="t-mono t-tertiary" style="font-weight: 400; font-size: var(--text-sm);">· {{ result.analysis_date }}</span></div>
        <div class="fin-table-wrap">
          <table class="fin-table">
            <thead>
              <tr><th>Ticker</th><th>Name</th><th>Market</th><th>Action</th><th>Confidence</th><th>Held since</th><th>Rationale</th></tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in result.recommendations" :key="i">
                <td class="fin-cell-strong t-mono">{{ r.ticker }}</td>
                <td>{{ r.name }}</td>
                <td class="fin-muted">{{ MARKET_LABELS[r.market] ?? r.market }}</td>
                <td><Badge :variant="actionBadge(r.action).variant">{{ actionBadge(r.action).label }}</Badge></td>
                <td><Badge :variant="confBadge(r.confidence).variant">{{ confBadge(r.confidence).label }}</Badge></td>
                <td class="t-mono fin-muted">{{ r.held_since ?? '—' }}</td>
                <td class="fin-note">{{ r.rationale }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="result.changes_since_last" class="fin-section">
        <div class="fin-section__title">Changes since last analysis</div>
        <p class="fin-note">{{ result.changes_since_last }}</p>
      </div>

      <div class="fin-section">
        <div class="fin-meta">
          <span class="fin-meta-key">Sources</span>{{ result.sources_used.join(' · ') }}
          <template v-if="snapshotMeta?.sources_failed?.length">
            <span class="fin-meta-key fin-meta-key--failed">Unavailable</span>{{ snapshotMeta.sources_failed.join(' · ') }}
          </template>
        </div>
        <div class="fin-meta" style="margin-top: var(--space-2); opacity: 0.8;"><span class="fin-meta-key">Risk</span>{{ result.risk_note }}</div>
      </div>

      <PiCard v-if="result.reasoning">
        <Collapse label="Agent reasoning">
          <p class="fin-reasoning">{{ result.reasoning }}</p>
        </Collapse>
      </PiCard>
    </template>
  </div>
</template>
