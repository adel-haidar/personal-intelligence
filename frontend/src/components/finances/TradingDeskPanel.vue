<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import PiCard from '../ui/PiCard.vue'
import PiButton from '../ui/PiButton.vue'
import PIIcon from '../ui/PIIcon.vue'
import Collapse from '../ui/Collapse.vue'
import { useTradingDesk, STRATEGY_META, STAGE_ORDER, STAGE_LABELS, STAGE_AGENTS, UNIVERSE_OPTIONS } from '../../composables/useTradingDesk'
import type { TradeStrategy, TradeMode, TradeAccount } from '../../composables/useTradingDesk'

const {
  configStatus, config, broker, portfolio, error, actionLoading, brokerLoading,
  currentRun, trades, events, atApprovalGate, isDone,
  workspace, runError, activeStage, stageStatus, keptNotional, keptCount,
  loadConfig, saveConfig, loadBroker, connectBroker, disconnectBroker,
  loadLatestRun, startRun, approveRun, denyRun, cancelRun,
  keepTrade, skipTrade, loadPortfolio, resetRun,
} = useTradingDesk()

// ── Setup panel: show/hide ────────────────────────────────────────────────────
const showSetup = ref(false)

// ── Broker connect form ───────────────────────────────────────────────────────
const brokerEnv = ref<'demo' | 'live'>('demo')
const brokerKey = ref('')
const brokerSecret = ref('')
const showBrokerForm = ref(false)

async function submitBroker() {
  await connectBroker(brokerEnv.value, brokerKey.value.trim(), brokerSecret.value.trim() || undefined)
  if (!error.value) {
    showBrokerForm.value = false
    brokerKey.value = ''
    brokerSecret.value = ''
  }
}

// ── On mount ─────────────────────────────────────────────────────────────────
onMounted(async () => {
  await loadConfig()
  await loadBroker()
  await loadLatestRun()
  if (isDone.value) loadPortfolio()
})

// ── Workspace logic ───────────────────────────────────────────────────────────
const activeWorkspace = computed(() => {
  if (showSetup.value) return 'setup'
  return workspace.value
})

// ── Money formatting ─────────────────────────────────────────────────────────
function money(v: number, currency = '€'): string {
  return `${currency}${Math.round(v).toLocaleString('de-DE')}`
}
function pct(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

// ── Strategy change ───────────────────────────────────────────────────────────
async function setStrategy(s: TradeStrategy) {
  config.value.strategy = s
  const meta = STRATEGY_META[s]
  config.value.guardrails = {
    max_trade_pct: meta.maxTrade,
    day_loss_pct: meta.dayLoss,
    stop_pct: meta.defaultStop,
  }
  await saveConfig({ strategy: s, guardrails: config.value.guardrails })
}

async function setMode(m: TradeMode) {
  config.value.mode = m
  await saveConfig({ mode: m })
}

// Upper bound on what the user may hand the agents:
//  - paper: the €100k simulated balance
//  - live:  their REAL Trading 212 available cash, minus the reserve floor
//           (null while unknown — e.g. broker not connected yet)
const allocationCap = computed<number | null>(() => {
  if (config.value.account === 'paper') return 100000
  const cash = broker.value.available_cash
  if (cash == null) return null
  return Math.max(0, Math.floor(cash - config.value.reserve_floor))
})

const allocationCeilingLabel = computed(() => {
  if (config.value.account === 'paper') return `of ${money(100000)} simulated`
  if (!broker.value.connected) return ''
  const cash = broker.value.available_cash
  if (cash == null) return ''
  return `of ${money(cash)} available`
})

async function setAccount(a: TradeAccount) {
  config.value.account = a
  // Clamp the current allocation to the new account's ceiling before saving.
  const cap = allocationCap.value
  if (cap != null && config.value.allocation > cap) config.value.allocation = cap
  await saveConfig({ account: a, allocation: config.value.allocation, reserve_floor: config.value.reserve_floor })
}

async function setAllocation(val: number) {
  let v = Math.max(0, Math.round(val || 0))
  const cap = allocationCap.value
  if (cap != null) v = Math.min(v, cap)
  config.value.allocation = v
  // Reserve floor can never exceed the allocation.
  if (config.value.reserve_floor > v) {
    config.value.reserve_floor = v
    await saveConfig({ allocation: v, reserve_floor: v })
  } else {
    await saveConfig({ allocation: v })
  }
}

// When the real balance arrives (or the account switches), clamp a too-large
// allocation down to what the account can actually back, and persist it.
watch(allocationCap, (cap) => {
  if (cap != null && config.value.allocation > cap) setAllocation(cap)
})

async function toggleUniverse(key: keyof typeof config.value.universe) {
  config.value.universe[key] = !config.value.universe[key]
  await saveConfig({ universe: config.value.universe })
}

async function updateGuardrail(key: keyof typeof config.value.guardrails, val: number) {
  config.value.guardrails[key] = val
  await saveConfig({ guardrails: config.value.guardrails })
}

// ── Approve with disclaimer ───────────────────────────────────────────────────
const showLiveDisclaimer = ref(false)
function handleApprove() {
  if (config.value.account === 'live') {
    showLiveDisclaimer.value = true
  } else {
    approveRun()
  }
}
function confirmLiveApprove() {
  showLiveDisclaimer.value = false
  approveRun()
}

// ── Run / reset ───────────────────────────────────────────────────────────────
async function handleStart() {
  await startRun()
  showSetup.value = false
}

function handleReset() {
  resetRun()
  showSetup.value = false
}

// ── Trade side color ─────────────────────────────────────────────────────────
function sideBg(side: string) {
  if (side === 'buy')  return 'var(--success-surface)'
  if (side === 'trim') return 'var(--warning-surface)'
  return 'var(--danger-surface)'
}
function sideColor(side: string) {
  if (side === 'buy')  return 'var(--success)'
  if (side === 'trim') return 'var(--warning)'
  return 'var(--danger)'
}

// ── Risk verdict label ────────────────────────────────────────────────────────
function verdictLabel(v: string) {
  return v.charAt(0).toUpperCase() + v.slice(1)
}

// ── Asset class bar color ─────────────────────────────────────────────────────
function assetColor(cls: string) {
  if (cls === 'etf')    return 'var(--accent-primary)'
  if (cls === 'crypto') return 'var(--brain-amber)'
  if (cls === 'cash')   return 'var(--border-strong)'
  if (cls === 'bonds')  return 'var(--success)'
  return 'var(--text-tertiary)'
}

// ── Agent display name ────────────────────────────────────────────────────────
function agentLabel(agent: string) {
  const map: Record<string, string> = {
    coordinator: 'Coordinator',
    web_scout: 'Web scout',
    analyst: 'Analyst',
    strategist: 'Strategist',
    risk_officer: 'Risk officer',
    broker: 'Broker',
  }
  return map[agent] ?? agent
}

// ── Stage active agent color ──────────────────────────────────────────────────
function stageAgentColor(stageId: string) {
  const agentMap: Record<string, string> = {
    research: '#4FA8C7',
    coordinate: 'var(--accent-primary)',
    strategy: '#D4923A',
    evaluate: '#C97A86',
    execute: '#8B8FA8',
  }
  return agentMap[stageId] ?? 'var(--accent-primary)'
}

// ── Latest active agent from events ──────────────────────────────────────────
const latestEvent = computed(() => {
  const evts = events.value
  if (!evts.length) return null
  return evts[evts.length - 1]
})
</script>

<template>
  <div class="td-root">
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- Section header                                                      -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <div class="td-section-head">
      <div class="td-section-head__left">
        <span class="td-eyebrow">Agent trading desk</span>
        <p class="td-section-desc">
          Hand a team of AI agents an allocation and a strategy — they research, draft trades, and place orders through your brokerage.
        </p>
      </div>
      <span class="pi-badge pi-badge--amber" style="flex: 0 0 auto;">New</span>
    </div>

    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- Mode banner (always visible)                                        -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <div class="td-mode-banner" v-if="configStatus === 'success'">
      <!-- Mode pill -->
      <div class="td-mode-banner__left">
        <span
          class="td-mode-pill"
          :style="config.account === 'paper'
            ? 'background:var(--accent-surface);color:var(--accent-hover)'
            : 'background:var(--success-surface);color:var(--success)'"
        >
          <span
            v-if="config.account === 'live'"
            class="td-live-dot"
            aria-hidden="true"
          />
          {{ config.account === 'paper' ? 'Paper' : 'Live' }}
        </span>
        <span class="td-mode-banner__sub">
          {{ config.account === 'paper' ? 'Simulated funds' : (broker.connected ? broker.label ?? 'Trading 212' : 'No broker connected') }}
        </span>
        <!-- Strategy pill -->
        <span
          class="td-strat-pill"
          :style="`color: var(--${STRATEGY_META[config.strategy].tone});`"
        >
          <span class="td-strat-dot" :style="`background:var(--${STRATEGY_META[config.strategy].tone})`" />
          {{ STRATEGY_META[config.strategy].label }}
        </span>
        <!-- Mode description -->
        <span class="td-mode-banner__mode">
          {{ config.mode === 'auto' ? 'Auto · places without asking' : 'Controlled · you approve' }}
        </span>
      </div>

      <div class="td-mode-banner__right">
        <span class="td-mode-banner__alloc-label">Available to agents</span>
        <span class="t-mono td-mode-banner__alloc">{{ money(config.allocation) }}</span>
        <PiButton
          variant="ghost"
          size="compact"
          icon="settings"
          @click="showSetup = !showSetup"
        >Configure</PiButton>
      </div>
    </div>

    <!-- Loading skeleton for banner -->
    <div v-else-if="configStatus === 'loading'" class="td-mode-banner">
      <div class="pi-skeleton" style="width: 300px; height: 20px; border-radius: var(--radius-sm);" />
    </div>

    <!-- Error -->
    <div v-if="error" class="td-error-bar">
      <PIIcon name="shield" :size="14" style="color:var(--danger)" />
      <span>{{ error }}</span>
    </div>

    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- SETUP workspace                                                     -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <template v-if="activeWorkspace === 'setup'">
      <div class="td-stack">

        <!-- 1a. Allocation meter -->
        <PiCard>
          <div class="td-eyebrow" style="margin-bottom: var(--space-2);">Made available to the agents</div>
          <div class="td-alloc-big">
            {{ money(config.allocation) }}
            <span class="td-alloc-of">{{ allocationCeilingLabel }}</span>
          </div>

          <!-- Editable allocation -->
          <div class="td-alloc-edit">
            <input
              class="td-alloc-range"
              type="range"
              min="0"
              :max="allocationCap ?? (config.account === 'paper' ? 100000 : Math.max(config.allocation, 1000))"
              step="100"
              :value="config.allocation"
              :disabled="config.account === 'live' && !broker.connected"
              @input="config.allocation = +($event.target as HTMLInputElement).value"
              @change="setAllocation(+($event.target as HTMLInputElement).value)"
            />
            <div class="td-alloc-numwrap">
              <span class="t-mono td-alloc-cur">€</span>
              <input
                class="pi-input td-alloc-num t-mono"
                type="number"
                min="0"
                :max="allocationCap ?? undefined"
                step="100"
                :value="config.allocation"
                :disabled="config.account === 'live' && !broker.connected"
                @change="setAllocation(+($event.target as HTMLInputElement).value)"
              />
            </div>
          </div>
          <p v-if="config.account === 'live' && !broker.connected" class="td-alloc-hint">
            Connect Trading 212 below to set a live allocation from your real balance.
          </p>
          <p v-else-if="config.account === 'live' && broker.available_cash != null" class="td-alloc-hint">
            Capped at your available Trading 212 cash ({{ money(broker.available_cash) }}){{ config.reserve_floor ? ` minus the ${money(config.reserve_floor)} reserve` : '' }}.
          </p>

          <!-- Meter bar -->
          <div class="td-meter" role="presentation">
            <div
              class="td-meter__seg td-meter__seg--deployed"
              :style="`width:${config.account === 'live' ? 16 : 0}%`"
              title="Deployed"
            />
            <div
              class="td-meter__seg td-meter__seg--free"
              :style="`width:${config.account === 'paper' ? 25 : 24}%`"
              title="Free to trade"
            />
            <div
              class="td-meter__seg td-meter__seg--reserve"
              :style="`width:${Math.round((config.reserve_floor / (config.allocation + config.reserve_floor)) * 100)}%`"
              title="Reserve floor"
            />
          </div>

          <div class="td-meter-legend">
            <span v-if="config.account === 'live'" class="td-meter-leg">
              <i class="td-swatch" style="background:var(--accent-primary)" />
              Deployed
              <span class="t-mono">{{ money(0) }}</span>
            </span>
            <span class="td-meter-leg">
              <i class="td-swatch" style="background:color-mix(in oklab, var(--accent-primary) 30%, var(--background-input))" />
              Free to trade
              <span class="t-mono">{{ money(config.allocation) }}</span>
            </span>
            <span class="td-meter-leg">
              <i class="td-swatch td-swatch--hatch" />
              Reserve floor
              <span class="t-mono">{{ money(config.reserve_floor) }}</span>
            </span>
          </div>
          <p class="td-alloc-note">
            Agents may only trade within your allocation. The reserve floor is ring-fenced and can never be touched or exceeded.
          </p>
        </PiCard>

        <!-- 1b. Broker connection -->
        <PiCard>
          <div class="td-card-head">
            <span class="td-card-title">Where the money lives</span>
            <!-- Paper / Live toggle -->
            <div class="td-acct-pills">
              <button
                class="td-acct-pill"
                :class="{ 'td-acct-pill--on': config.account === 'paper' }"
                @click="setAccount('paper')"
              >Paper</button>
              <button
                class="td-acct-pill"
                :class="{ 'td-acct-pill--on': config.account === 'live' }"
                @click="setAccount('live')"
              >Live</button>
            </div>
          </div>

          <!-- Paper mode -->
          <div v-if="config.account === 'paper'" class="td-broker-row td-broker-row--active">
            <div class="td-broker-icon">
              <PIIcon name="finances" :size="18" />
            </div>
            <div class="td-broker-info">
              <div class="td-broker-name">Simulated account</div>
              <div class="td-broker-meta">{{ money(100000) }} of practice money · no real funds at risk</div>
            </div>
            <span class="pi-badge pi-badge--success">Active</span>
          </div>

          <!-- Live mode -->
          <template v-else>
            <div
              class="td-broker-row"
              :class="broker.connected ? 'td-broker-row--active' : ''"
            >
              <div class="td-broker-icon">
                <PIIcon name="key" :size="18" />
              </div>
              <div class="td-broker-info">
                <div class="td-broker-name">Trading 212</div>
                <div class="td-broker-meta">
                  {{ broker.connected ? broker.label ?? 'Connected' : 'Connect via API key' }}
                </div>
              </div>
              <div style="display:flex; gap:var(--space-2); align-items:center;">
                <span v-if="broker.connected" class="pi-badge pi-badge--success">Connected</span>
                <PiButton
                  v-if="broker.connected"
                  variant="ghost"
                  size="compact"
                  @click="disconnectBroker"
                  :loading="brokerLoading"
                >Disconnect</PiButton>
                <PiButton
                  v-else
                  variant="secondary"
                  size="compact"
                  @click="showBrokerForm = !showBrokerForm"
                >Connect</PiButton>
              </div>
            </div>

            <!-- Broker connect form -->
            <div v-if="showBrokerForm && !broker.connected" class="td-broker-form">
              <div class="td-broker-form__row">
                <label class="pi-label">Environment</label>
                <div class="td-acct-pills" style="width:fit-content">
                  <button class="td-acct-pill" :class="{ 'td-acct-pill--on': brokerEnv === 'demo' }" @click="brokerEnv = 'demo'">Demo</button>
                  <button class="td-acct-pill" :class="{ 'td-acct-pill--on': brokerEnv === 'live' }" @click="brokerEnv = 'live'">Live</button>
                </div>
              </div>
              <div class="pi-field">
                <label class="pi-label">API key</label>
                <input v-model="brokerKey" class="pi-input" placeholder="Paste your Trading 212 API key" />
              </div>
              <div class="pi-field">
                <label class="pi-label">API secret (optional)</label>
                <input v-model="brokerSecret" class="pi-input" type="password" placeholder="Optional — leave blank if not required" />
              </div>
              <PiButton
                variant="primary"
                :loading="brokerLoading"
                :disabled="!brokerKey.trim()"
                @click="submitBroker"
              >Connect Trading 212</PiButton>
            </div>

            <!-- Live disclaimer -->
            <div class="td-disclaimer">
              <PIIcon name="shield" :size="14" style="color:var(--warning);flex:0 0 auto" />
              <p>
                <strong>Live trading disclaimer.</strong> This tool executes real orders on your behalf using your brokerage API key. You are responsible for all trades placed. Private Internet is not a financial adviser and does not manage your assets on a discretionary basis. Markets can move against you; you may lose money. Guardrails reduce but do not eliminate risk. By continuing in Live mode you confirm you understand these risks.
              </p>
            </div>
          </template>
        </PiCard>

        <!-- 1c. Strategy -->
        <PiCard>
          <div class="td-card-title" style="margin-bottom: var(--space-4);">Strategy</div>
          <div class="td-strat-grid">
            <div
              v-for="(meta, key) in STRATEGY_META"
              :key="key"
              class="td-strat-card"
              :class="{ 'td-strat-card--on': config.strategy === key }"
              :style="config.strategy === key ? `border-color:var(--accent-primary);box-shadow:0 0 0 1px var(--accent-primary)` : ''"
              @click="setStrategy(key as TradeStrategy)"
            >
              <div class="td-strat-head">
                <span class="td-strat-name">{{ meta.label }}</span>
                <PIIcon v-if="config.strategy === key" name="check" :size="14" style="color:var(--accent-primary)" />
              </div>
              <p class="td-strat-line">{{ meta.line }}</p>
              <div class="td-strat-caps t-mono">
                Max trade {{ meta.maxTrade }}% · day-loss {{ meta.dayLoss }}% · crypto {{ meta.cryptoCap }}%
              </div>
            </div>
          </div>
        </PiCard>

        <!-- 1d. Mode -->
        <PiCard>
          <div class="td-card-title" style="margin-bottom: var(--space-4);">How trades get placed</div>
          <div class="td-mode-grid">
            <div
              class="td-mode-card"
              :class="{ 'td-mode-card--on': config.mode === 'controlled' }"
              @click="setMode('controlled')"
            >
              <div class="td-mode-head">
                <span class="td-mode-name">Controlled</span>
                <span class="pi-badge pi-badge--filled" style="font-size:10px">Default</span>
                <PIIcon v-if="config.mode === 'controlled'" name="check" :size="14" style="color:var(--accent-primary)" />
              </div>
              <p class="td-mode-desc">The Coordinator asks you to approve or deny every basket before any order is placed.</p>
            </div>
            <div
              class="td-mode-card"
              :class="{ 'td-mode-card--on': config.mode === 'auto' }"
              @click="setMode('auto')"
            >
              <div class="td-mode-head">
                <span class="td-mode-name">Auto</span>
                <PIIcon v-if="config.mode === 'auto'" name="check" :size="14" style="color:var(--accent-primary)" />
              </div>
              <p class="td-mode-desc">Agents place trades on their own. Close the window and come back — guardrails still apply.</p>
            </div>
          </div>
        </PiCard>

        <!-- 1e. Universe -->
        <PiCard>
          <div class="td-card-title" style="margin-bottom: var(--space-4);">What the agents may trade</div>
          <div class="td-universe">
            <button
              v-for="opt in UNIVERSE_OPTIONS"
              :key="opt.id"
              class="td-chip"
              :class="{ 'td-chip--on': config.universe[opt.id] }"
              @click="toggleUniverse(opt.id)"
            >
              <span v-if="config.universe[opt.id]" class="td-chip-check" aria-hidden="true">✓</span>
              {{ opt.label }}
            </button>
          </div>
        </PiCard>

        <!-- 1f. Guardrails -->
        <PiCard>
          <div class="td-card-title" style="margin-bottom: var(--space-4);">Money guardrails</div>
          <p class="td-guardrail-note">The Risk officer enforces these on every order. Hitting the daily loss limit pauses the whole desk.</p>
          <div class="td-guardrail-grid">
            <div class="td-guardrail">
              <div class="td-guardrail__head">
                <span>Max per single trade</span>
                <span class="t-mono td-guardrail__val">{{ config.guardrails.max_trade_pct }}%</span>
              </div>
              <input
                type="range" min="1" max="40" step="1"
                :value="config.guardrails.max_trade_pct"
                class="td-slider"
                @change="updateGuardrail('max_trade_pct', +($event.target as HTMLInputElement).value)"
              />
            </div>
            <div class="td-guardrail">
              <div class="td-guardrail__head">
                <span>Daily loss limit (auto-stop)</span>
                <span class="t-mono td-guardrail__val">{{ config.guardrails.day_loss_pct }}%</span>
              </div>
              <input
                type="range" min="0.5" max="12" step="0.5"
                :value="config.guardrails.day_loss_pct"
                class="td-slider"
                @change="updateGuardrail('day_loss_pct', +($event.target as HTMLInputElement).value)"
              />
            </div>
            <div class="td-guardrail">
              <div class="td-guardrail__head">
                <span>Reserve floor</span>
                <span class="t-mono td-guardrail__val">{{ money(config.reserve_floor) }}</span>
              </div>
              <input
                type="range" min="0" :max="Math.round(config.allocation * 0.5)" step="500"
                :value="config.reserve_floor"
                class="td-slider"
                @change="saveConfig({ reserve_floor: +($event.target as HTMLInputElement).value }); config.reserve_floor = +($event.target as HTMLInputElement).value"
              />
            </div>
            <div class="td-guardrail">
              <div class="td-guardrail__head">
                <span>Default stop-loss</span>
                <span class="t-mono td-guardrail__val">{{ config.guardrails.stop_pct }}%</span>
              </div>
              <input
                type="range" min="1" max="20" step="1"
                :value="config.guardrails.stop_pct"
                class="td-slider"
                @change="updateGuardrail('stop_pct', +($event.target as HTMLInputElement).value)"
              />
            </div>
          </div>
        </PiCard>

        <!-- Setup footer -->
        <div class="td-setup-footer">
          <p class="td-setup-reassure">Your guardrails are enforced on every order. You can reconfigure at any time between runs.</p>
          <PiButton variant="cta" icon="play" :loading="actionLoading" @click="handleStart">
            Start a run
          </PiButton>
        </div>

      </div>
    </template>

    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- WORKING workspace (team is busy)                                    -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <template v-else-if="activeWorkspace === 'working'">
      <PiCard class="td-working">
        <!-- Active agent avatar -->
        <div class="td-working__ava-wrap">
          <div
            class="td-ava td-ava--ring"
            :style="`background: ${stageAgentColor(activeStage)}; width:40px; height:40px;`"
            aria-hidden="true"
          >
            <PIIcon :name="activeStage === 'research' ? 'globe' : activeStage === 'strategy' ? 'spark' : activeStage === 'evaluate' ? 'shield' : activeStage === 'execute' ? 'key' : 'branch'" :size="20" style="color:#fff" />
          </div>
        </div>

        <h3 class="td-working__title">Your team is working on it</h3>
        <p class="td-working__sub t-secondary">
          <template v-if="latestEvent">{{ agentLabel(latestEvent.agent) }} — {{ latestEvent.message }}</template>
          <template v-else>Agents are getting started…</template>
        </p>

        <!-- Compact stepper -->
        <div class="td-steps">
          <div
            v-for="stageId in STAGE_ORDER"
            :key="stageId"
            class="td-step"
            :class="{
              'td-step--done': stageStatus(stageId) === 'done',
              'td-step--active': stageStatus(stageId) === 'active',
              'td-step--todo': stageStatus(stageId) === 'todo',
            }"
          >
            <div
              class="td-step__circle"
              :class="{ 'td-ava--ring': stageStatus(stageId) === 'active' }"
            >
              <PIIcon
                v-if="stageStatus(stageId) === 'done'"
                name="check"
                :size="12"
                style="color:var(--success)"
              />
              <span v-else class="td-step__num">{{ STAGE_ORDER.indexOf(stageId) + 1 }}</span>
            </div>
            <div class="td-step__body">
              <div class="td-step__label">{{ STAGE_LABELS[stageId] }}</div>
              <div class="td-step__agents t-tertiary">{{ STAGE_AGENTS[stageId].join(' + ') }}</div>
            </div>
          </div>
        </div>

        <!-- Controls -->
        <div class="td-working__controls">
          <PiButton variant="danger" size="compact" icon="close" :loading="actionLoading" @click="cancelRun">
            Cancel run
          </PiButton>
        </div>
      </PiCard>
    </template>

    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- CARDS + APPROVAL workspace (primary surface)                        -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <template v-else-if="activeWorkspace === 'cards'">
      <div class="td-stack">

        <!-- Summary header card -->
        <PiCard class="td-ask">
          <div class="td-ask__head">
            <!-- Coordinator avatar -->
            <div
              class="td-ava"
              :class="{ 'td-ava--ring': atApprovalGate }"
              style="background:var(--accent-primary); width:32px; height:32px; flex: 0 0 auto;"
            >
              <PIIcon name="branch" :size="16" style="color:#fff" />
            </div>

            <div class="td-ask__title-wrap">
              <h2 class="td-ask__title">
                <template v-if="atApprovalGate">
                  Your team has {{ keptCount }} {{ keptCount === 1 ? 'trade' : 'trades' }} ready for you
                </template>
                <template v-else>
                  Your team placed {{ trades.filter(t => t.status === 'placed').length }} {{ trades.filter(t => t.status === 'placed').length === 1 ? 'trade' : 'trades' }}
                </template>
              </h2>
              <span v-if="!atApprovalGate" class="pi-badge pi-badge--success" style="margin-left:var(--space-2);">Done</span>
            </div>
          </div>

          <!-- Market read (serif) -->
          <p v-if="currentRun?.market_read" class="td-market-read">
            {{ currentRun.market_read }}
          </p>

          <!-- Meta row -->
          <div class="td-ask__meta">
            <span class="t-mono">Putting <strong>{{ money(keptNotional) }}</strong> of your <strong>{{ money(currentRun?.allocation ?? config.allocation) }}</strong> to work</span>
            <span class="td-strat-pill" :style="`color:var(--${STRATEGY_META[config.strategy].tone})`">
              <span class="td-strat-dot" :style="`background:var(--${STRATEGY_META[config.strategy].tone})`" />
              {{ STRATEGY_META[config.strategy].label }}
            </span>
            <span class="t-secondary" style="font-size:var(--text-sm)">
              {{ config.account === 'paper' ? 'Paper trading' : 'Live · Trading 212' }}
            </span>
          </div>

          <!-- Action row — Controlled mode at gate -->
          <div v-if="atApprovalGate && config.mode === 'controlled'" class="td-ask__actions">
            <PiButton variant="cta" icon="check" :loading="actionLoading" @click="handleApprove">
              Place {{ keptCount }} {{ keptCount === 1 ? 'trade' : 'trades' }}
            </PiButton>
            <PiButton variant="secondary" icon="close" :loading="actionLoading" @click="denyRun">
              Not now
            </PiButton>
          </div>

          <!-- Auto mode badge -->
          <div v-else-if="atApprovalGate && config.mode === 'auto'" class="td-auto-badge">
            <span class="pi-badge pi-badge--filled">Auto mode</span>
            <span class="t-secondary" style="font-size:var(--text-sm)">The team will place these on its own — you don't need to do anything.</span>
          </div>

          <!-- Post-deny state -->
          <div v-else-if="currentRun?.status === 'denied'" class="td-denied">
            <span class="t-secondary">Nothing was placed.</span>
            <PiButton variant="ghost" icon="play" @click="handleReset">Ask the team to redraft</PiButton>
          </div>
        </PiCard>

        <!-- Trade cards grid -->
        <div class="td-cards-grid">
          <div
            v-for="trade in trades"
            :key="trade.id"
            class="td-tcard"
            :class="{
              'td-tcard--rejected': trade.risk_verdict === 'rejected',
              'td-tcard--kept': trade.kept && trade.risk_verdict !== 'rejected',
            }"
          >
            <!-- Head row -->
            <div class="td-tcard__head">
              <div class="td-tcard__left">
                <span
                  class="td-side"
                  :style="`background:${sideBg(trade.side)};color:${sideColor(trade.side)}`"
                >{{ trade.side.toUpperCase() }}</span>
                <div>
                  <div class="td-ticker">{{ trade.ticker }}</div>
                  <div class="td-tname">{{ trade.name }}</div>
                </div>
              </div>
              <div class="td-tcard__right">
                <div class="td-amount">{{ money(trade.amount) }}</div>
                <div class="td-alloc-pct">{{ trade.pct_of_allocation }}% of allocation</div>
              </div>
            </div>

            <!-- Headline -->
            <div class="td-tcard__headline">{{ trade.headline }}</div>

            <!-- Reasoning (serif) -->
            <p class="td-tcard__why">{{ trade.reasoning }}</p>

            <!-- Evidence -->
            <ul class="td-evidence">
              <li v-for="(ev, i) in trade.evidence" :key="i">{{ ev }}</li>
            </ul>

            <!-- Risk strip -->
            <div class="td-risk">
              <div
                class="td-ava"
                style="width:22px;height:22px;background:#C97A86;flex:0 0 auto;"
              >
                <PIIcon name="shield" :size="11" style="color:#fff" />
              </div>
              <span>
                <strong>Risk officer · {{ verdictLabel(trade.risk_verdict) }}.</strong>
                {{ trade.risk_note }}
              </span>
            </div>

            <!-- Footer -->
            <div class="td-tcard__foot">
              <template v-if="trade.risk_verdict === 'rejected'">
                <span class="td-foot-removed">Removed by your guardrails</span>
              </template>
              <template v-else-if="trade.status === 'placed'">
                <span class="td-foot-placed">
                  <PIIcon name="check" :size="13" />
                  Placed
                </span>
              </template>
              <template v-else-if="trade.status === 'skipped'">
                <div class="td-foot-actions">
                  <PiButton variant="ghost" size="compact" @click="keepTrade(trade.id)">Add back</PiButton>
                  <span class="td-foot-skipped">Skipped</span>
                </div>
              </template>
              <template v-else>
                <div class="td-foot-actions">
                  <PiButton variant="ghost" size="compact" @click="skipTrade(trade.id)">Skip this one</PiButton>
                  <span class="td-foot-will-place">Will place</span>
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- How your team decided (collapsed) -->
        <PiCard>
          <Collapse label="How your team decided">
            <p style="font-size:var(--text-sm);color:var(--text-secondary);line-height:1.65;margin-bottom:var(--space-4)">
              One Coordinator orchestrates five workers across five stages: two scouts read the market in parallel, the Coordinator synthesises their signals, the Strategist drafts a basket of orders, the Risk officer checks every order against your guardrails and resizes or rejects as needed, and finally the Broker places the approved orders with your brokerage.
            </p>
            <!-- Mini stepper -->
            <div class="td-steps">
              <div
                v-for="stageId in STAGE_ORDER"
                :key="stageId"
                class="td-step td-step--done"
              >
                <div class="td-step__circle">
                  <PIIcon name="check" :size="12" style="color:var(--success)" />
                </div>
                <div class="td-step__body">
                  <div class="td-step__label">{{ STAGE_LABELS[stageId] }}</div>
                  <div class="td-step__agents t-tertiary">{{ STAGE_AGENTS[stageId].join(' + ') }}</div>
                </div>
              </div>
            </div>
          </Collapse>
        </PiCard>

      </div>
    </template>

    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- MONITORING workspace (after orders fill)                            -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <template v-else-if="activeWorkspace === 'monitoring'">
      <div class="td-stack">

        <!-- Portfolio card -->
        <PiCard v-if="portfolio">
          <div class="td-eyebrow" style="margin-bottom:var(--space-3)">
            Managed by the agents · {{ portfolio.account === 'paper' ? 'Paper' : 'Live' }}
          </div>

          <div class="td-portfolio-head">
            <div class="td-alloc-big">{{ money(portfolio.value) }}</div>
            <div class="td-portfolio-stats">
              <div class="td-portfolio-stat">
                <span class="t-secondary" style="font-size:var(--text-sm)">Today</span>
                <span class="t-mono" :style="`color:${portfolio.day_change >= 0 ? 'var(--success)' : 'var(--danger)'}`">
                  {{ portfolio.day_change >= 0 ? '+' : '' }}{{ money(portfolio.day_change) }}
                </span>
              </div>
              <div class="td-portfolio-stat">
                <span class="t-secondary" style="font-size:var(--text-sm)">Since funded</span>
                <span class="t-mono" :style="`color:${portfolio.since_funded >= 0 ? 'var(--success)' : 'var(--danger)'}`">
                  {{ portfolio.since_funded >= 0 ? '+' : '' }}{{ money(portfolio.since_funded) }}
                </span>
              </div>
            </div>
          </div>

          <!-- Holdings -->
          <div class="td-holdings">
            <div
              v-for="h in portfolio.holdings"
              :key="h.ticker"
              class="td-holding-row"
            >
              <div class="td-holding-ticker">{{ h.ticker }}</div>
              <div class="td-holding-name t-secondary">{{ h.name }}</div>
              <div class="td-holding-mid">
                <span class="t-mono">{{ money(h.value) }}</span>
                <span class="t-tertiary" style="font-size:var(--text-xs)"> · {{ h.pct }}%</span>
              </div>
              <div
                class="t-mono"
                style="font-size:var(--text-sm)"
                :style="`color:${h.day_change > 0 ? 'var(--success)' : h.day_change < 0 ? 'var(--danger)' : 'var(--text-tertiary)'}`"
              >
                {{ h.day_change !== 0 ? pct(h.day_change) : '—' }}
              </div>
              <div class="td-alloc-bar-wrap">
                <div
                  class="td-alloc-bar"
                  :style="`width:${h.pct}%;background:${assetColor(h.asset_class)}`"
                />
              </div>
            </div>
          </div>
        </PiCard>

        <!-- This run orders card -->
        <PiCard>
          <div class="td-card-title" style="margin-bottom:var(--space-4)">This run · orders placed</div>
          <div class="td-fills">
            <div
              v-for="trade in trades.filter(t => t.status === 'placed')"
              :key="trade.id"
              class="td-fill-row"
            >
              <span
                class="td-side td-side--sm"
                :style="`background:${sideBg(trade.side)};color:${sideColor(trade.side)}`"
              >{{ trade.side.toUpperCase() }}</span>
              <span class="td-fill-ticker t-mono">{{ trade.ticker }}</span>
              <span class="t-secondary t-mono" style="font-size:var(--text-sm)">
                {{ trade.filled_qty ?? '—' }} @ {{ trade.filled_price ? money(trade.filled_price) : '—' }}
              </span>
              <span class="pi-badge pi-badge--success" style="margin-left:auto">Filled</span>
            </div>
            <p v-if="!trades.some(t => t.status === 'placed')" class="t-tertiary" style="font-size:var(--text-sm)">
              No orders filled yet.
            </p>
          </div>
        </PiCard>

        <div style="display:flex;justify-content:flex-end;">
          <PiButton variant="ghost" icon="play" @click="handleReset">Start a new run</PiButton>
        </div>

      </div>
    </template>

    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- ERROR — the run failed                                               -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <template v-if="activeWorkspace === 'error'">
      <PiCard>
        <div class="td-error-head">
          <PIIcon name="shield" :size="18" style="color:var(--danger);flex:0 0 auto" />
          <span class="td-card-title">The run couldn't finish</span>
        </div>
        <p class="td-error-msg">
          {{ runError || 'The trading team hit an unexpected problem and stopped. No orders were placed.' }}
        </p>
        <div v-if="events.length" class="td-error-log">
          <div v-for="ev in events" :key="ev.id" class="td-error-log__row">
            <span class="t-mono td-error-log__agent">{{ ev.agent }}</span>
            <span>{{ ev.message }}</span>
          </div>
        </div>
        <div style="display:flex;justify-content:flex-end;margin-top:var(--space-4);">
          <PiButton variant="cta" icon="play" @click="handleReset">Try again</PiButton>
        </div>
      </PiCard>
    </template>

    <!-- ─────────────────────────────────────────────────────────────────── -->
    <!-- Live trading disclaimer modal overlay                               -->
    <!-- ─────────────────────────────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showLiveDisclaimer" class="td-modal-overlay" @click.self="showLiveDisclaimer = false">
        <div class="td-modal">
          <h3 class="td-modal__title">Confirm live trading</h3>
          <p class="td-modal__body">
            You are about to place <strong>real orders</strong> through your brokerage. Once placed, orders execute immediately at market price and cannot be recalled. Private Internet is not a financial adviser. You bear full responsibility for all trades. Guardrails limit but do not eliminate risk.
          </p>
          <div class="td-modal__actions">
            <PiButton variant="secondary" @click="showLiveDisclaimer = false">Cancel</PiButton>
            <PiButton variant="cta" icon="check" :loading="actionLoading" @click="confirmLiveApprove">
              I understand — place the trades
            </PiButton>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<style scoped>
/* ── Root & layout ─────────────────────────────────────────────────────── */
.td-root { display: flex; flex-direction: column; gap: var(--space-5); }
.td-stack { display: flex; flex-direction: column; gap: var(--space-5); }

/* ── Section header ────────────────────────────────────────────────────── */
.td-section-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--space-4); margin-bottom: var(--space-1);
}
.td-section-head__left { display: flex; flex-direction: column; gap: var(--space-1); }
.td-eyebrow {
  font-family: var(--font-display); font-weight: 600; font-size: var(--text-xs);
  text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-tertiary);
}
.td-section-desc { font-size: var(--text-sm); color: var(--text-secondary); max-width: 60ch; line-height: 1.6; }

/* ── Mode banner ───────────────────────────────────────────────────────── */
.td-mode-banner {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
  gap: var(--space-3); padding: 12px 16px;
  background: var(--background-surface); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
.td-mode-banner__left { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.td-mode-banner__right { display: flex; align-items: center; gap: var(--space-3); margin-left: auto; }
.td-mode-banner__sub { font-size: 13px; color: var(--text-secondary); }
.td-mode-banner__mode { font-size: 13px; color: var(--text-secondary); }
.td-mode-banner__alloc-label { font-size: 13px; color: var(--text-secondary); }
.td-mode-banner__alloc { font-size: 15px; font-weight: 600; }

.td-mode-pill {
  border-radius: var(--radius-pill); padding: 5px 12px;
  font-size: 13px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px;
}
.td-live-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--success); animation: pi-amber-pulse 1.6s ease-in-out infinite;
}
.td-strat-pill {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 13px; font-weight: 500;
}
.td-strat-dot { width: 5px; height: 5px; border-radius: 50%; display: inline-block; }

/* ── Error bar ─────────────────────────────────────────────────────────── */
.td-error-bar {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-3) var(--space-4); background: var(--danger-surface);
  border: 1px solid var(--danger); border-radius: var(--radius-sm);
  font-size: var(--text-sm); color: var(--danger);
}

/* ── Allocation meter ──────────────────────────────────────────────────── */
.td-alloc-big {
  font-family: var(--font-display); font-weight: 700; font-size: 42px;
  letter-spacing: -0.02em; line-height: 1.1; margin-bottom: var(--space-4);
}
.td-alloc-of {
  font-size: 22px; font-weight: 400; color: var(--text-tertiary); margin-left: var(--space-2);
}
.td-meter {
  height: 30px; border-radius: var(--radius-sm); background: var(--background-input);
  border: 1px solid var(--border-subtle); display: flex; overflow: hidden;
  margin-bottom: var(--space-3);
}
.td-meter__seg { height: 100%; transition: width .4s var(--ease); }
.td-meter__seg--deployed { background: var(--accent-primary); }
.td-meter__seg--free { background: color-mix(in oklab, var(--accent-primary) 30%, var(--background-input)); }
.td-meter__seg--reserve {
  background: repeating-linear-gradient(
    45deg, var(--border-strong) 0 5px, var(--border-medium) 5px 10px
  );
}
.td-meter-legend { display: flex; gap: var(--space-4); flex-wrap: wrap; margin-bottom: var(--space-3); }
.td-meter-leg { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-xs); color: var(--text-secondary); }
.td-swatch { width: 11px; height: 11px; border-radius: 2px; flex: 0 0 auto; }
.td-swatch--hatch {
  background: repeating-linear-gradient(
    45deg, var(--border-strong) 0 3px, var(--border-medium) 3px 6px
  );
}
.td-alloc-note { font-size: var(--text-sm); color: var(--text-tertiary); line-height: 1.6; }
.td-alloc-edit {
  display: flex; align-items: center; gap: var(--space-4);
  margin: var(--space-3) 0 var(--space-2);
}
.td-alloc-range { flex: 1; accent-color: var(--accent-primary); cursor: pointer; }
.td-alloc-range:disabled { opacity: 0.5; cursor: not-allowed; }
.td-alloc-numwrap { display: flex; align-items: center; gap: var(--space-1); }
.td-alloc-cur { color: var(--text-tertiary); }
.td-alloc-num { width: 120px; text-align: right; }
.td-alloc-hint { font-size: var(--text-xs); color: var(--text-tertiary); margin: 0 0 var(--space-2); }
.td-error-head { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); }
.td-error-msg { font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.6; margin: 0 0 var(--space-3); }
.td-error-log {
  display: flex; flex-direction: column; gap: var(--space-1);
  background: var(--background-raised); border-radius: var(--radius-sm);
  padding: var(--space-3); max-height: 220px; overflow-y: auto;
}
.td-error-log__row { display: flex; gap: var(--space-2); font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.5; }
.td-error-log__agent { color: var(--text-tertiary); flex: 0 0 84px; }

/* ── Card header ───────────────────────────────────────────────────────── */
.td-card-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-4); flex-wrap: wrap; }
.td-card-title { font-family: var(--font-display); font-weight: 600; font-size: var(--text-md); }

/* ── Account pills ─────────────────────────────────────────────────────── */
.td-acct-pills {
  display: inline-flex; background: var(--background-input); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm); padding: 3px; gap: 2px;
}
.td-acct-pill {
  padding: 4px 14px; border-radius: 6px; font-size: var(--text-sm); font-weight: 500;
  color: var(--text-secondary); cursor: pointer; transition: background .1s, color .1s;
}
.td-acct-pill--on { background: var(--background-surface); color: var(--text-primary); }

/* ── Broker rows ───────────────────────────────────────────────────────── */
.td-broker-row {
  display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
}
.td-broker-row--active {
  border-color: var(--accent-primary);
  background: var(--accent-surface);
}
.td-broker-icon {
  width: 34px; height: 34px; border-radius: var(--radius-sm);
  background: var(--background-raised); display: grid; place-items: center;
  color: var(--text-secondary); flex: 0 0 auto;
}
.td-broker-name { font-weight: 500; font-size: var(--text-sm); }
.td-broker-meta { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 2px; }
.td-broker-form { display: flex; flex-direction: column; gap: var(--space-3); padding-top: var(--space-3); }
.td-broker-form__row { display: flex; align-items: center; gap: var(--space-3); }

/* ── Disclaimer ────────────────────────────────────────────────────────── */
.td-disclaimer {
  display: flex; gap: var(--space-3); padding: var(--space-3) var(--space-4);
  background: var(--warning-surface); border: 1px solid var(--warning);
  border-radius: var(--radius-sm); font-size: var(--text-sm); color: var(--text-secondary);
  line-height: 1.6; margin-top: var(--space-3);
}

/* ── Strategy cards ────────────────────────────────────────────────────── */
.td-strat-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3);
}
@media (max-width: 900px) { .td-strat-grid { grid-template-columns: 1fr; } }
.td-strat-card {
  padding: var(--space-4); border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle); cursor: pointer;
  transition: border-color .12s var(--ease), background .12s var(--ease);
}
.td-strat-card:hover { border-color: var(--border-medium); background: var(--background-raised); }
.td-strat-card--on { border-color: var(--accent-primary); background: var(--accent-surface); }
.td-strat-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-bottom: var(--space-2); }
.td-strat-name { font-family: var(--font-display); font-weight: 600; font-size: var(--text-sm); }
.td-strat-line { font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.55; margin-bottom: var(--space-2); }
.td-strat-caps { font-size: var(--text-xs); color: var(--text-tertiary); }

/* ── Mode cards ────────────────────────────────────────────────────────── */
.td-mode-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
@media (max-width: 640px) { .td-mode-grid { grid-template-columns: 1fr; } }
.td-mode-card {
  padding: var(--space-4); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md); cursor: pointer;
  transition: border-color .12s var(--ease), background .12s var(--ease);
}
.td-mode-card:hover { border-color: var(--border-medium); }
.td-mode-card--on { border-color: var(--accent-primary); background: var(--accent-surface); box-shadow: 0 0 0 1px var(--accent-primary); }
.td-mode-head { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); flex-wrap: wrap; }
.td-mode-name { font-family: var(--font-display); font-weight: 600; font-size: var(--text-sm); }
.td-mode-desc { font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.55; }

/* ── Universe chips ────────────────────────────────────────────────────── */
.td-universe { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.td-chip {
  padding: 6px 12px; border-radius: var(--radius-pill); border: 1px solid var(--border-subtle);
  font-size: var(--text-sm); color: var(--text-secondary); cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px;
  transition: background .1s, border-color .1s, color .1s;
}
.td-chip:hover { border-color: var(--border-medium); color: var(--text-primary); }
.td-chip--on { background: var(--accent-surface); border-color: var(--accent-primary); color: var(--accent-hover); }
.td-chip-check { font-size: 10px; }

/* ── Guardrails ────────────────────────────────────────────────────────── */
.td-guardrail-note { font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.55; margin-bottom: var(--space-4); }
.td-guardrail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-5); }
@media (max-width: 640px) { .td-guardrail-grid { grid-template-columns: 1fr; } }
.td-guardrail { display: flex; flex-direction: column; gap: var(--space-2); }
.td-guardrail__head { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); color: var(--text-secondary); }
.td-guardrail__val { font-size: var(--text-sm); font-weight: 600; color: var(--text-primary); }
.td-slider {
  width: 100%; height: 4px; border-radius: var(--radius-pill);
  background: var(--background-raised); outline: none; cursor: pointer;
  accent-color: var(--accent-primary);
}

/* ── Setup footer ──────────────────────────────────────────────────────── */
.td-setup-footer {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-4); flex-wrap: wrap; padding: var(--space-4) 0;
}
.td-setup-reassure { font-size: var(--text-sm); color: var(--text-secondary); max-width: 45ch; line-height: 1.55; }

/* ── Working ───────────────────────────────────────────────────────────── */
.td-working { text-align: center; padding: var(--space-8) var(--space-6); display: flex; flex-direction: column; align-items: center; gap: var(--space-4); }
.td-working__ava-wrap { margin-bottom: var(--space-2); }
.td-working__title { font-family: var(--font-display); font-weight: 600; font-size: var(--text-md); }
.td-working__sub { font-size: var(--text-sm); max-width: 50ch; line-height: 1.6; }
.td-working__controls { display: flex; gap: var(--space-3); margin-top: var(--space-2); }

/* ── Agent avatar ──────────────────────────────────────────────────────── */
.td-ava {
  border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
  flex: 0 0 auto;
}
.td-ava--ring { position: relative; }
.td-ava--ring::before {
  content: ''; position: absolute; inset: -3px; border-radius: 50%;
  border: 2px solid currentColor; opacity: 0.5;
  animation: td-pulse-ring 1.4s ease-out infinite;
}
@keyframes td-pulse-ring {
  0%   { transform: scale(0.85); opacity: 0.6; }
  100% { transform: scale(1.25); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .td-ava--ring::before { animation: none; opacity: 0.3; transform: scale(1); }
}

/* ── Stepper ───────────────────────────────────────────────────────────── */
.td-steps { display: flex; gap: var(--space-2); flex-wrap: wrap; justify-content: center; }
.td-step {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); border-radius: var(--radius-pill);
  background: var(--background-raised);
}
.td-step__circle {
  width: 26px; height: 26px; border-radius: 50%; border: 1px solid var(--border-medium);
  display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
  font-size: var(--text-xs); font-weight: 600; background: var(--background-surface);
}
.td-step--done .td-step__circle { background: var(--success-surface); border-color: var(--success); }
.td-step--active .td-step__circle { background: var(--accent-surface); border-color: var(--accent-primary); color: var(--accent-primary); }
.td-step__body { display: flex; flex-direction: column; gap: 1px; }
.td-step__label { font-size: var(--text-xs); font-weight: 600; color: var(--text-primary); }
.td-step__agents { font-size: 10px; }
.td-step__num { color: var(--text-tertiary); }

/* ── Summary card ──────────────────────────────────────────────────────── */
.td-ask { display: flex; flex-direction: column; gap: var(--space-4); }
.td-ask__head { display: flex; align-items: center; gap: var(--space-3); }
.td-ask__title-wrap { display: flex; align-items: center; flex: 1; }
.td-ask__title { font-family: var(--font-display); font-weight: 600; font-size: 22px; line-height: 1.2; }
.td-market-read {
  font-family: var(--font-serif); font-size: var(--text-md); line-height: 1.6;
  color: var(--text-secondary);
}
.td-ask__meta {
  display: flex; align-items: center; gap: var(--space-4); flex-wrap: wrap;
  font-size: var(--text-sm); padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}
.td-ask__actions { display: flex; gap: var(--space-3); flex-wrap: wrap; }
.td-auto-badge { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.td-denied { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }

/* ── Trade cards grid ──────────────────────────────────────────────────── */
.td-cards-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4);
}
@media (max-width: 980px) { .td-cards-grid { grid-template-columns: 1fr; } }

.td-tcard {
  padding: var(--space-5); border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle); background: var(--background-surface);
  display: flex; flex-direction: column; gap: var(--space-3);
  animation: pi-slide-up 0.2s var(--ease) both;
  transition: border-color .2s var(--ease);
}
.td-tcard--rejected { opacity: 0.5; }
.td-tcard--kept {
  border-color: color-mix(in oklab, var(--success) 40%, var(--border-subtle));
}

.td-tcard__head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.td-tcard__left { display: flex; align-items: flex-start; gap: var(--space-2); }
.td-tcard__right { text-align: right; flex: 0 0 auto; }

.td-side {
  font-family: var(--font-mono); font-size: var(--text-xs); font-weight: 600;
  border-radius: var(--radius-sm); padding: 3px 8px; flex: 0 0 auto;
}
.td-side--sm { font-size: 10px; padding: 2px 6px; }
.td-ticker { font-family: var(--font-display); font-weight: 700; font-size: var(--text-md); }
.td-tname { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 1px; }
.td-amount { font-family: var(--font-mono); font-weight: 600; font-size: var(--text-md); }
.td-alloc-pct { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 1px; }

.td-tcard__headline { font-family: var(--font-display); font-weight: 600; font-size: var(--text-base); }
.td-tcard__why { font-family: var(--font-serif); font-size: var(--text-base); line-height: 1.62; color: var(--text-secondary); }

.td-evidence { list-style: none; display: flex; flex-direction: column; gap: 4px; }
.td-evidence li {
  font-size: var(--text-sm); color: var(--text-secondary); padding-left: var(--space-3);
  position: relative;
}
.td-evidence li::before {
  content: ''; position: absolute; left: 0; top: 8px;
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--border-strong);
}

.td-risk {
  display: flex; gap: var(--space-2); align-items: flex-start;
  background: var(--background-raised); border-radius: var(--radius-sm);
  padding: var(--space-3); font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.55;
}

.td-tcard__foot {
  border-top: 1px solid var(--border-subtle); padding-top: var(--space-3);
  font-size: var(--text-sm);
}
.td-foot-actions { display: flex; align-items: center; gap: var(--space-3); }
.td-foot-removed { color: var(--text-tertiary); font-style: italic; }
.td-foot-will-place { color: var(--success); font-weight: 500; }
.td-foot-skipped { color: var(--text-tertiary); }
.td-foot-placed { display: flex; align-items: center; gap: 5px; color: var(--success); font-weight: 500; }

/* ── Portfolio ─────────────────────────────────────────────────────────── */
.td-portfolio-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; margin-bottom: var(--space-4); }
.td-portfolio-stats { display: flex; gap: var(--space-6); }
.td-portfolio-stat { display: flex; flex-direction: column; gap: 2px; text-align: right; }
.td-holdings { display: flex; flex-direction: column; gap: 0; }
.td-holding-row {
  display: grid; grid-template-columns: 60px 1fr auto auto 80px;
  align-items: center; gap: var(--space-3);
  padding: var(--space-2) 0; border-bottom: 1px solid var(--border-subtle);
  font-size: var(--text-sm);
}
.td-holding-row:last-child { border-bottom: none; }
.td-holding-ticker { font-family: var(--font-mono); font-weight: 600; font-size: var(--text-sm); }
.td-holding-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.td-holding-mid { white-space: nowrap; }
.td-alloc-bar-wrap { background: var(--background-raised); border-radius: var(--radius-pill); height: 4px; }
.td-alloc-bar { height: 100%; border-radius: var(--radius-pill); }

/* ── Fills (orders) ────────────────────────────────────────────────────── */
.td-fills { display: flex; flex-direction: column; gap: var(--space-2); }
.td-fill-row {
  display: flex; align-items: center; gap: var(--space-3); font-family: var(--font-mono);
  font-size: var(--text-sm); padding: var(--space-2) 0;
  border-bottom: 1px solid var(--border-subtle);
}
.td-fill-row:last-child { border-bottom: none; }
.td-fill-ticker { font-weight: 600; }

/* ── Modal overlay ─────────────────────────────────────────────────────── */
.td-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 200;
  display: flex; align-items: center; justify-content: center; padding: var(--space-4);
}
.td-modal {
  background: var(--background-surface); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg); padding: var(--space-8); max-width: 480px; width: 100%;
  display: flex; flex-direction: column; gap: var(--space-4);
  box-shadow: var(--shadow-menu);
}
.td-modal__title { font-family: var(--font-display); font-weight: 600; font-size: var(--text-md); }
.td-modal__body { font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.65; }
.td-modal__actions { display: flex; gap: var(--space-3); justify-content: flex-end; flex-wrap: wrap; }
</style>
