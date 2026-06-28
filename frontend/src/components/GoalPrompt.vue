<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import PiButton from './ui/PiButton.vue'
import PIIcon from './ui/PIIcon.vue'
import { useFocusTrap } from '../composables/useFocusTrap'

// ── Props ─────────────────────────────────────────────────────────────────────
interface Props {
  open: boolean
  /** 'weight' → captures target weight in kg.
   *  'savings' → captures annual savings goal (amount + currency). */
  kind: 'weight' | 'savings'
  saving?: boolean
  error?: string
}

const props = withDefaults(defineProps<Props>(), {
  saving: false,
  error: '',
})

const emit = defineEmits<{
  close: []
  save: [payload: { kg?: number; amount?: number; currency?: string }]
}>()

// ── Weight state ──────────────────────────────────────────────────────────────
const weightInput = ref('')
const weightError = ref('')

// Accept both decimal separators: many locales (e.g. de-DE) type "70,5".
// Strip spaces and normalise comma → dot so a number input quirk can't blank it.
function cleanWeight(): string {
  return weightInput.value.replace(/\s/g, '').replace(',', '.')
}

function validateWeight(): boolean {
  const raw = cleanWeight()
  const v = parseFloat(raw)
  if (!raw || isNaN(v) || v <= 0 || v > 500) {
    weightError.value = 'Enter a weight between 1 and 500 kg.'
    return false
  }
  weightError.value = ''
  return true
}

// ── Savings state ─────────────────────────────────────────────────────────────
const COMMON_CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY', 'CAD', 'AUD', 'SEK', 'NOK', 'DKK']

function defaultCurrency(): string {
  try {
    const locale = Intl.NumberFormat().resolvedOptions().locale
    const region = locale.split('-')[1]?.toUpperCase()
    const map: Record<string, string> = {
      US: 'USD', GB: 'GBP', CH: 'CHF', JP: 'JPY', CA: 'CAD',
      AU: 'AUD', SE: 'SEK', NO: 'NOK', DK: 'DKK',
    }
    return (region && map[region]) || 'EUR'
  } catch {
    return 'EUR'
  }
}

const amountInput = ref('')
const currency = ref(defaultCurrency())
const savingsError = ref('')

function validateSavings(): boolean {
  const raw = amountInput.value.replace(/[,\s]/g, '')
  const v = parseFloat(raw)
  if (!raw || isNaN(v) || v <= 0) {
    savingsError.value = 'Enter a positive amount.'
    return false
  }
  savingsError.value = ''
  return true
}

// ── Reset on re-open ──────────────────────────────────────────────────────────
watch(() => props.open, (open) => {
  if (open) {
    weightInput.value = ''
    weightError.value = ''
    amountInput.value = ''
    savingsError.value = ''
    currency.value = defaultCurrency()
  }
})

// ── Keyboard close + focus trap ───────────────────────────────────────────────
const dialogEl = ref<HTMLElement | null>(null)
useFocusTrap(dialogEl, () => props.open, { onEscape: () => emit('close') })

// ── Submit ────────────────────────────────────────────────────────────────────
function submit() {
  if (props.kind === 'weight') {
    if (!validateWeight()) return
    const kg = parseFloat(parseFloat(cleanWeight()).toFixed(2))
    emit('save', { kg })
  } else {
    if (!validateSavings()) return
    const rawAmt = amountInput.value.replace(/[,\s]/g, '')
    // Preserve decimal-dot representation but no thousands separators
    const amount = parseFloat(parseFloat(rawAmt).toFixed(2))
    emit('save', { amount, currency: currency.value })
  }
}

// ── Derived texts ─────────────────────────────────────────────────────────────
const title = computed(() =>
  props.kind === 'weight' ? 'Set your target weight' : 'Set your annual savings goal',
)
const subtitle = computed(() =>
  props.kind === 'weight'
    ? 'Your brain will use this to track your progress and tailor its health insights to your goal.'
    : 'Your brain will use this to evaluate your savings trajectory and give personalised financial guidance.',
)
const currentError = computed(() =>
  props.error || (props.kind === 'weight' ? weightError.value : savingsError.value),
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      ref="dialogEl"
      class="gp-overlay"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      @click="emit('close')"
    >
      <div class="gp-modal" @click.stop>
        <!-- Header -->
        <div class="gp-modal__head">
          <div class="gp-modal__title">{{ title }}</div>
          <button class="pi-btn pi-btn--icon" aria-label="Dismiss" @click="emit('close')">
            <PIIcon name="close" :size="18" />
          </button>
        </div>

        <!-- Body -->
        <div class="gp-modal__body">
          <p class="gp-subtitle">{{ subtitle }}</p>

          <!-- Weight input -->
          <template v-if="kind === 'weight'">
            <label class="gp-label" for="gp-weight">Target weight</label>
            <div class="gp-input-row">
              <input
                id="gp-weight"
                v-model="weightInput"
                class="gp-input"
                type="text"
                placeholder="e.g. 70"
                inputmode="decimal"
                :disabled="saving"
                @keydown.enter="submit"
              />
              <span class="gp-unit">kg</span>
            </div>
          </template>

          <!-- Savings inputs -->
          <template v-else>
            <label class="gp-label" for="gp-amount">Annual savings target</label>
            <div class="gp-input-row">
              <input
                id="gp-amount"
                v-model="amountInput"
                class="gp-input"
                type="text"
                inputmode="decimal"
                placeholder="e.g. 12000"
                :disabled="saving"
                @keydown.enter="submit"
              />
              <select
                v-model="currency"
                class="gp-select"
                :disabled="saving"
              >
                <option v-for="c in COMMON_CURRENCIES" :key="c" :value="c">{{ c }}</option>
              </select>
            </div>
          </template>

          <!-- Validation / API error -->
          <p v-if="currentError" class="gp-error" role="alert">{{ currentError }}</p>
        </div>

        <!-- Actions -->
        <div class="gp-modal__foot">
          <PiButton variant="ghost" size="compact" :disabled="saving" @click="emit('close')">
            Skip for now
          </PiButton>
          <PiButton variant="cta" size="compact" :loading="saving" :disabled="saving" @click="submit">
            Save goal
          </PiButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.gp-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
  padding: var(--space-4);
}

.gp-modal {
  background: var(--background-surface);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-menu);
  width: min(420px, 100%);
  display: flex;
  flex-direction: column;
  gap: 0;
}

.gp-modal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-5) var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}

.gp-modal__title {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-md);
  color: var(--text-primary);
}

.gp-modal__body {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.gp-subtitle {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
}

.gp-label {
  display: block;
  font-family: var(--font-display);
  font-weight: 500;
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.gp-input-row {
  display: flex;
  gap: var(--space-2);
  align-items: stretch;
}

.gp-input {
  flex: 1;
  background: var(--background-input);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: var(--text-base);
  padding: 10px var(--space-3);
  outline: none;
  transition: border-color 0.15s;
  min-width: 0;
}

.gp-input:focus {
  border-color: var(--accent-primary);
}

.gp-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Remove browser spinners on number input */
.gp-input[type=number]::-webkit-inner-spin-button,
.gp-input[type=number]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.gp-input[type=number] { -moz-appearance: textfield; }

.gp-unit {
  display: flex;
  align-items: center;
  padding: 0 var(--space-3);
  background: var(--background-raised);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

.gp-select {
  background: var(--background-raised);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  padding: 0 var(--space-3);
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
}

.gp-select:focus {
  border-color: var(--accent-primary);
}

.gp-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.gp-error {
  font-size: var(--text-sm);
  color: var(--danger);
  margin: 0;
}

.gp-modal__foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border-subtle);
}
</style>
