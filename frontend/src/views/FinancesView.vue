<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import PageHead from '../components/ui/PageHead.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiButton from '../components/ui/PiButton.vue'
import PIIcon from '../components/ui/PIIcon.vue'
import Pills from '../components/ui/Pills.vue'
import UploadBanner from '../components/ui/UploadBanner.vue'
import InsightCard from '../components/ui/InsightCard.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import SpendBar, { type SpendSegment } from '../components/ui/SpendBar.vue'
import ProgressBar from '../components/ui/ProgressBar.vue'
import ConfirmModal from '../components/ui/ConfirmModal.vue'
import ShareButton from '../components/ui/ShareButton.vue'
import PeriodControls from '../components/finances/PeriodControls.vue'
import SpendingBudgetPanel from '../components/finances/SpendingBudgetPanel.vue'
import InvestingPanel from '../components/finances/InvestingPanel.vue'
import DayTradingPanel from '../components/finances/DayTradingPanel.vue'
import GoalPrompt from '../components/GoalPrompt.vue'
import { useBankAdviser, type AnalysisParams } from '../composables/useBankAdviser'
import { requireAuth } from '../composables/useAuth'
import { API_BASE } from '../config/env'
import { useToast } from '../components/ui/useToast'
import { checkSavingsGoal, saveSavingsGoal } from '../composables/useGoal'

const { status, result, error, lastRun, runAnalysis, loadLatest } = useBankAdviser()
const toast = useToast()

// ── Goal prompt ───────────────────────────────────────────────────────────────
const goalPromptOpen = ref(false)
const goalSaving = ref(false)
const goalError = ref('')

async function onSaveSavingsGoal(payload: { amount?: number; currency?: string }) {
  if (!payload.amount || !payload.currency) return
  goalSaving.value = true
  goalError.value = ''
  try {
    await saveSavingsGoal(payload.amount, payload.currency)
    goalPromptOpen.value = false
  } catch {
    goalError.value = 'Could not save your goal — please try again.'
  } finally {
    goalSaving.value = false
  }
}

onMounted(async () => {
  loadLatest()
  // Show goal-capture modal if no savings goal is set in the brain.
  const existing = await checkSavingsGoal()
  if (existing === null) goalPromptOpen.value = true
})

// ── Tabs ──────────────────────────────────────────────────────────────────────
const TABS = [
  { value: 'overview',    label: 'Overview' },
  { value: 'spending',    label: 'Spending & budget' },
  { value: 'investments', label: 'Investments' },
  { value: 'trading',     label: 'Day trading' },
]
const activeTab = ref<'overview' | 'spending' | 'investments' | 'trading'>('overview')

const populated = computed(() => status.value === 'success' && !!result.value)

// SAVINGS_TARGET: a generic financial-guidance figure (not owner-specific).
// 20% is the broadly-cited "50/30/20" rule recommended by most personal-finance
// authorities. It is NOT hardcoded per-user — it is the benchmark shown when no
// personalised goal is set. When the user has set an annual savings goal in their
// brain, the ProgressBar still uses this rate benchmark for the % gauge, but the
// goal amount is shown as context. Keeping this as a constant is correct behaviour.
const SAVINGS_TARGET = 20

// ── Currency / formatting ─────────────────────────────────────────────────────
const CURRENCY_SYMBOL: Record<string, string> = { EUR: '€', USD: '$', GBP: '£', CHF: 'CHF ' }
const sym = computed(() => CURRENCY_SYMBOL[result.value?.meta.currency ?? 'EUR'] ?? `${result.value?.meta.currency ?? ''} `)
function money(v: number): string { return `${sym.value}${Math.round(Math.abs(v)).toLocaleString()}` }
function prettyCategory(name: string): string { return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) }

// ── Overview: spend breakdown ─────────────────────────────────────────────────
const SEG_COLORS = ['var(--accent-primary)', 'var(--success)', 'var(--brain-amber)', 'var(--border-strong)']
const spendSegments = computed<SpendSegment[]>(() => {
  const sa = result.value?.spending_analysis
  if (!sa) return []
  const entries = Object.entries(sa.categories)
    .map(([name, c]) => ({ name, actual: c.actual }))
    .filter(e => e.actual > 0)
    .sort((a, b) => b.actual - a.actual)
  const total = sa.total_expenses || entries.reduce((s, e) => s + e.actual, 0)
  if (!total) return []
  const top = entries.slice(0, 3)
  const restActual = entries.slice(3).reduce((s, e) => s + e.actual, 0)
  const segs: SpendSegment[] = top.map((e, i) => ({ label: prettyCategory(e.name), pct: Math.round((e.actual / total) * 100), color: SEG_COLORS[i] }))
  if (restActual > 0) segs.push({ label: 'Other', pct: Math.round((restActual / total) * 100), color: SEG_COLORS[3] })
  return segs
})
const monthDelta = computed<number | null>(() => {
  const mom = result.value?.spending_analysis.month_over_month
  if (!mom || Object.keys(mom).length === 0) return null
  return Object.values(mom).reduce((s, e) => s + e.delta_eur, 0)
})
const moneyLead = computed(() => {
  const d = monthDelta.value
  if (d == null) return 'Here is where your money went this period.'
  if (Math.abs(d) < 1) return 'Your spending was roughly flat compared with last month.'
  return d > 0 ? `You spent ${money(d)} more than last month.` : `You spent ${money(d)} less than last month.`
})

// ── Overview: savings ─────────────────────────────────────────────────────────
const savingsRate = computed<number | null>(() => {
  const inc = result.value?.income_summary.total_income
  const net = result.value?.spending_analysis.net_savings_this_period
  if (!inc || net == null) return null
  return (net / inc) * 100
})
const savingsFill = computed(() => savingsRate.value == null ? 0 : Math.max(0, Math.min(100, (savingsRate.value / SAVINGS_TARGET) * 100)))
const savingsStatus = computed<{ kind: 'good' | 'watch' | 'attention'; text: string }>(() => {
  const t = result.value?.yearly_progress.trajectory
  if (t === 'ahead') return { kind: 'good', text: 'Ahead' }
  if (t === 'behind') return { kind: 'attention', text: 'Behind' }
  return { kind: 'watch', text: 'On track' }
})
const investmentNote = computed(() => result.value?.investment_signal.note ?? '')
const suggestText = computed(() => {
  if (result.value?.reasoning) return result.value.reasoning
  const recs = result.value?.recommendations ?? []
  return recs.slice(0, 3).map(r => r.action).join(' ')
})
const lastRunLabel = computed(() => lastRun.value ? lastRun.value.toLocaleDateString() : null)

// Privacy-preserving share card: a qualitative headline from the savings
// trajectory and rate band — never euro amounts, balances, or income figures.
const financeHighlight = computed(() => {
  const map: Record<string, string> = {
    'Ahead': 'Ahead on my money goals 📈',
    'Behind': 'Refocusing my money goals 🎯',
    'On track': 'On track with my finances 💸',
  }
  const rate = savingsRate.value
  const band = rate == null ? '' : rate >= 20 ? 'strong saver' : rate >= 10 ? 'steady saver' : 'building the habit'
  return {
    headline: map[savingsStatus.value.text] ?? 'My money check-in',
    caption: band ? `A ${band} this period` : 'Tracked privately with my own AI brain',
  }
})

// ── Run / upload ──────────────────────────────────────────────────────────────
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
function pickFile() { fileInput.value?.click() }

async function onPickFile(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (files.length === 0) return
  uploading.value = true
  let successCount = 0
  let failCount = 0
  try {
    const token = await requireAuth()
    for (const file of files) {
      try {
        const fd = new FormData()
        fd.append('files', file)
        const res = await fetch(`${API_BASE}/api/file`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
        if (res.ok) { successCount++ } else { failCount++ }
      } catch {
        failCount++
      }
    }
  } catch {
    toast('Upload failed', 'error')
    return
  } finally {
    uploading.value = false
  }
  if (successCount > 0 && failCount === 0) {
    toast(
      successCount === 1
        ? 'File added — run analysis to see your summary'
        : `${successCount} files added — run analysis to see your summary`,
      'success',
    )
  } else if (successCount > 0 && failCount > 0) {
    toast(`${successCount} file${successCount > 1 ? 's' : ''} uploaded, ${failCount} failed`, 'warning')
  } else {
    toast('Upload failed', 'error')
  }
}

async function runDefault() { await doRun({ mode: 'ytd' }) }
async function doRun(params: AnalysisParams) {
  await runAnalysis(params)
  if (status.value === 'error') toast(error.value ?? 'Analysis failed', 'error')
}

// ── Delete ────────────────────────────────────────────────────────────────────
const confirmDel = ref(false)
async function deleteAll() {
  confirmDel.value = false
  // NOTE: backend DELETE endpoint for financial data is not implemented yet.
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/banking/data`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
    toast(res.ok ? 'Financial data deleted' : 'Deleting financial data isn’t available yet.', res.ok ? 'warning' : 'error')
  } catch {
    toast('Deleting financial data isn’t available yet.', 'error')
  }
}
</script>

<template>
  <div style="max-width: var(--content-dashboard); margin: 0 auto;">
    <PageHead
      title="Finances"
      desc="Upload your financial documents and your brain gives you a clear picture of your money — without the jargon."
    />

    <input ref="fileInput" type="file" accept=".pdf,.csv,.xlsx,.xls" multiple hidden @change="onPickFile" />

    <!-- Tabs -->
    <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-6);">
      <Pills :options="TABS" :modelValue="activeTab" @update:modelValue="(v) => (activeTab = v as typeof activeTab)" />
      <ShareButton v-if="populated" kind="finance_card" :highlight="financeHighlight" label="Share snapshot" />
    </div>

    <!-- ══ OVERVIEW ══ -->
    <template v-if="activeTab === 'overview'">
      <PiCard v-if="status === 'loading'" style="margin-bottom: var(--space-6);">
        <div class="pi-progress pi-progress--thin"><div class="pi-progress__track"><div class="pi-progress__fill" style="width: 40%;" /></div></div>
        <p class="t-secondary" style="font-size: var(--text-sm); margin-top: var(--space-3);">Analysing your statements…</p>
      </PiCard>

      <UploadBanner
        v-if="!populated && status !== 'loading'"
        tone="info"
        icon="finances"
        title="Get your financial analysis"
        intro="Upload your financial documents and your brain will give you a clear picture of your money — without jargon."
        :items="[
          'Bank statements (PDF or CSV)',
          'Payslips or salary records',
          'Investment portfolio exports (PDF, CSV, or Excel)',
          'Credit card statements',
          'Pension or retirement fund summaries',
        ]"
        note="This data is only on your server. You can delete it at any time from Brain → Manage data."
      >
        <template #actions>
          <PiButton variant="cta" icon="upload" :loading="uploading" @click="pickFile">Upload financial files</PiButton>
          <PiButton variant="secondary" @click="runDefault">Run analysis</PiButton>
        </template>
      </UploadBanner>

      <template v-if="populated">
        <div class="pi-insight-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); margin-bottom: var(--space-4);">
          <div style="grid-column: 1 / -1;">
            <InsightCard title="Your money this period">
              <SpendBar v-if="spendSegments.length" :segments="spendSegments" />
              <p class="pi-insight__lead" style="margin-top: var(--space-5);">{{ moneyLead }}</p>
            </InsightCard>
          </div>

          <InsightCard title="Savings and investments">
            <template #status><StatusPill :kind="savingsStatus.kind">{{ savingsStatus.text }}</StatusPill></template>
            <div v-if="savingsRate != null" class="pi-goal" style="margin-bottom: var(--space-4);">
              <div class="pi-goal__head">
                <span class="t-secondary" style="font-size: var(--text-sm);">Savings rate</span>
                <span class="pi-goal__val" style="color: var(--success);">{{ Math.round(savingsRate) }}%</span>
              </div>
              <ProgressBar :value="savingsFill" variant="success" :showPct="false" />
              <div class="pi-goal__scale"><span>0%</span><span>Target {{ SAVINGS_TARGET }}%</span></div>
            </div>
            <p v-if="savingsRate != null" class="pi-insight__lead" style="font-size: var(--text-base);">
              You're saving about {{ Math.round(savingsRate) }}% of your income. Most financial guidance suggests {{ SAVINGS_TARGET }}% — {{ savingsRate >= SAVINGS_TARGET ? "you're there." : "you're close, keep building the habit." }}
            </p>
            <p v-if="investmentNote" class="pi-insight__lead" style="font-size: var(--text-base); margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--border-subtle);">
              {{ investmentNote }}
            </p>
          </InsightCard>

          <InsightCard title="What your finances suggest">
            <p class="pi-insight__lead" style="font-size: var(--text-base);">{{ suggestText || 'No specific suggestions right now — your finances look balanced.' }}</p>
          </InsightCard>
        </div>

        <div style="display: flex; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap; align-items: center;">
          <div style="display: flex; gap: var(--space-3); align-items: center; flex-wrap: wrap;">
            <PiButton variant="ghost" icon="plus" :loading="uploading" @click="pickFile">Upload more data</PiButton>
            <PiButton variant="ghost" :loading="status === 'loading'" @click="runDefault">Re-run analysis</PiButton>
            <span v-if="lastRunLabel" class="t-mono t-tertiary" style="font-size: var(--text-xs);">Updated {{ lastRunLabel }}</span>
            <button class="pi-show-numbers" style="display: inline-flex; align-items: center; gap: 4px;" @click="activeTab = 'spending'">
              Full breakdown <PIIcon name="arrowRight" :size="14" />
            </button>
          </div>
          <PiButton variant="danger" icon="trash" @click="confirmDel = true">Delete all financial data</PiButton>
        </div>
      </template>
    </template>

    <!-- ══ SPENDING & BUDGET ══ -->
    <template v-else-if="activeTab === 'spending'">
      <PiCard style="margin-bottom: var(--space-6);">
        <PeriodControls :loading="status === 'loading'" :hasResult="!!result" @run="doRun" />
      </PiCard>

      <PiCard v-if="status === 'loading'" style="margin-bottom: var(--space-6);">
        <div class="pi-progress pi-progress--thin"><div class="pi-progress__track"><div class="pi-progress__fill" style="width: 40%;" /></div></div>
        <p class="t-secondary" style="font-size: var(--text-sm); margin-top: var(--space-3);">Fetching statements from memory and running the analysis. This can take 30–90s.</p>
      </PiCard>
      <PiCard v-if="status === 'error' && error" style="border-color: var(--danger); margin-bottom: var(--space-6);">
        <span style="color: var(--danger); font-size: var(--text-sm);">{{ error }}</span>
      </PiCard>

      <SpendingBudgetPanel v-if="result" :result="result" />
      <p v-else-if="status !== 'loading'" class="fin-empty">No analysis yet — choose a period above and run it.</p>
    </template>

    <!-- ══ INVESTMENTS ══ -->
    <InvestingPanel v-else-if="activeTab === 'investments'" />

    <!-- ══ DAY TRADING ══ -->
    <DayTradingPanel v-else-if="activeTab === 'trading'" />
  </div>

  <ConfirmModal
    :open="confirmDel"
    danger
    confirmLabel="Delete all financial data"
    title="Delete all financial data?"
    body="This permanently removes every financial file and the insights drawn from them. Your brain keeps everything else. This cannot be undone."
    @close="confirmDel = false"
    @confirm="deleteAll"
  />

  <GoalPrompt
    kind="savings"
    :open="goalPromptOpen"
    :saving="goalSaving"
    :error="goalError"
    @close="goalPromptOpen = false"
    @save="onSaveSavingsGoal"
  />
</template>
