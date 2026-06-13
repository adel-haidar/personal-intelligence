<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { registerWithPassword } from '../composables/useAuth'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiInput from '../components/ui/PiInput.vue'
import PiButton from '../components/ui/PiButton.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'

const router = useRouter()
const route  = useRoute()

const email          = ref('')
const displayName    = ref('')
const password       = ref('')
const confirmPass    = ref('')
const selectedPlan   = ref<'free' | 'personal' | 'pro'>('free')

const loading        = ref(false)
const error          = ref('')
const fieldErrors    = ref<Record<string, string>>({})

/** After successful registration with email verification required */
const verificationPending = ref(false)
const submittedEmail      = ref('')

// Pre-select plan from ?plan= query param
onMounted(() => {
  const q = route.query.plan as string | undefined
  if (q === 'personal' || q === 'pro') {
    selectedPlan.value = q
  }
})

const PLANS = [
  { key: 'free',     label: 'Free',     desc: 'Start without a card', price: '€0' },
  { key: 'personal', label: 'Personal', desc: '€9 / month',           price: '€9' },
  { key: 'pro',      label: 'Pro',      desc: '€19 / month',          price: '€19' },
] as const

// Password strength: 0–3 dots
const strength = computed<number>(() => {
  const l = password.value.length
  if (l >= 16) return 3
  if (l >= 12) return 2
  if (l >= 6) return 1
  return 0
})

function dotColor(i: number): string {
  if (i < strength.value) {
    return strength.value === 3 ? 'var(--success)' : 'var(--brain-amber)'
  }
  return 'var(--border-medium)'
}

function strengthLabel(): string {
  if (strength.value === 0) return ''
  if (strength.value === 1) return 'Weak'
  if (strength.value === 2) return 'Good'
  return 'Strong'
}

// Inline confirm-mismatch error (shown without needing submit)
const confirmMismatch = computed(() =>
  confirmPass.value.length > 0 && confirmPass.value !== password.value
)

function validate(): boolean {
  const errs: Record<string, string> = {}

  if (!displayName.value.trim()) {
    errs.displayName = 'Display name is required.'
  } else if (displayName.value.trim().length < 2) {
    errs.displayName = 'Display name must be at least 2 characters.'
  }

  if (!email.value.trim()) {
    errs.email = 'Email is required.'
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) {
    errs.email = 'Enter a valid email address.'
  }

  if (!password.value) {
    errs.password = 'Password is required.'
  } else if (password.value.length < 12) {
    errs.password = 'Password must be at least 12 characters.'
  }

  if (!confirmPass.value) {
    errs.confirmPass = 'Please confirm your password.'
  } else if (password.value !== confirmPass.value) {
    errs.confirmPass = 'Passwords do not match.'
  }

  fieldErrors.value = errs
  return Object.keys(errs).length === 0
}

async function handleRegister() {
  error.value = ''
  if (!validate()) return

  loading.value = true
  try {
    const result = await registerWithPassword({
      email:        email.value.trim(),
      display_name: displayName.value.trim(),
      password:     password.value,
      plan:         selectedPlan.value,
    })

    if (result.email_verification_required) {
      // No token yet — show the inbox message on this same page.
      submittedEmail.value      = email.value.trim()
      verificationPending.value = true
    } else {
      // Token stored in useAuth; proceed to onboarding.
      router.replace('/onboarding')
    }
  } catch (e) {
    error.value   = (e as Error).message ?? 'Registration failed'
    loading.value = false
  }
}
</script>

<template>
  <div class="pi-auth pi-auth--single">
    <div class="auth-mode-toggle">
      <ModeToggle :withLabel="false" />
    </div>

    <!-- ── Success / verification-pending state ─────────────────────────── -->
    <div v-if="verificationPending" class="reg-verify-wrap">
      <div class="reg-verify-pulse" aria-hidden="true">
        <BrainPulse :size="48" :slow="true" />
      </div>
      <h1 class="reg-verify-title">Check your inbox</h1>
      <p class="reg-verify-body t-secondary">
        We sent a verification link to<br />
        <strong class="reg-verify-email">{{ submittedEmail }}</strong>
      </p>
      <p class="reg-verify-hint t-tertiary">
        Click the link in that email to activate your account and continue to onboarding.
        The link expires in 24 hours.
      </p>
      <div class="reg-verify-actions">
        <router-link to="/login" class="auth-text-link">Back to sign in</router-link>
      </div>
    </div>

    <!-- ── Registration form ────────────────────────────────────────────── -->
    <form v-else style="width: 100%; max-width: 480px;" @submit.prevent="handleRegister" novalidate>
      <!-- Header -->
      <div class="reg-header">
        <div class="reg-logo-wrap">
          <BrainPulse :size="48" :slow="true" aria-hidden="true" />
        </div>
        <h1 class="reg-title">Create your account</h1>
      </div>

      <PiCard>
        <div class="reg-fields">
          <!-- Plan selection -->
          <fieldset class="reg-plan-fieldset">
            <legend class="pi-label">Plan</legend>
            <div class="reg-plan-options" role="radiogroup" aria-label="Select a plan">
              <label
                v-for="plan in PLANS"
                :key="plan.key"
                class="reg-plan-option"
                :class="{ 'reg-plan-option--selected': selectedPlan === plan.key }"
              >
                <input
                  type="radio"
                  name="plan"
                  :value="plan.key"
                  v-model="selectedPlan"
                  class="reg-plan-radio"
                />
                <span class="reg-plan-label">{{ plan.label }}</span>
                <span class="reg-plan-desc t-tertiary">{{ plan.desc }}</span>
              </label>
            </div>
          </fieldset>

          <!-- Display name -->
          <div class="pi-field">
            <label class="pi-label" for="reg-display-name">Display name</label>
            <PiInput
              id="reg-display-name"
              v-model="displayName"
              type="text"
              placeholder="Adel Haidar"
              autocomplete="nickname"
              :disabled="loading"
              :error="fieldErrors.displayName"
            />
            <p v-if="fieldErrors.displayName" class="pi-field__error" role="alert">
              {{ fieldErrors.displayName }}
            </p>
            <p v-else class="pi-field__hint">Shown throughout the app — not a username.</p>
          </div>

          <!-- Email -->
          <div class="pi-field">
            <label class="pi-label" for="reg-email">Email</label>
            <PiInput
              id="reg-email"
              v-model="email"
              type="email"
              placeholder="you@yourserver.com"
              autocomplete="email"
              :disabled="loading"
              :error="fieldErrors.email"
            />
            <p v-if="fieldErrors.email" class="pi-field__error" role="alert">
              {{ fieldErrors.email }}
            </p>
          </div>

          <!-- Password + strength meter -->
          <div class="pi-field">
            <label class="pi-label" for="reg-password">Password</label>
            <PiInput
              id="reg-password"
              v-model="password"
              type="password"
              placeholder="••••••••••••"
              autocomplete="new-password"
              :disabled="loading"
              :error="fieldErrors.password"
            />
            <!-- 3-dot strength meter -->
            <div class="reg-strength" aria-hidden="true">
              <span
                v-for="i in [0, 1, 2]"
                :key="i"
                class="reg-strength__dot"
                :style="{ background: dotColor(i) }"
              />
              <span v-if="strengthLabel()" class="reg-strength__label t-tertiary">
                {{ strengthLabel() }}
              </span>
            </div>
            <p v-if="fieldErrors.password" class="pi-field__error" role="alert">
              {{ fieldErrors.password }}
            </p>
            <p v-else class="pi-field__hint">At least 12 characters.</p>
          </div>

          <!-- Confirm password -->
          <div class="pi-field">
            <label class="pi-label" for="reg-confirm">Confirm password</label>
            <PiInput
              id="reg-confirm"
              v-model="confirmPass"
              type="password"
              placeholder="••••••••••••"
              autocomplete="new-password"
              :disabled="loading"
              :error="confirmMismatch || !!fieldErrors.confirmPass ? 'error' : ''"
            />
            <p
              v-if="confirmMismatch || fieldErrors.confirmPass"
              class="pi-field__error"
              role="alert"
            >
              {{ fieldErrors.confirmPass || 'Passwords do not match.' }}
            </p>
          </div>

          <!-- CTA -->
          <PiButton variant="cta" :block="true" :loading="loading" type="submit">
            Create my account →
          </PiButton>

          <!-- Server error -->
          <p v-if="error" class="pi-field__error reg-error-center" role="alert">
            {{ error }}
          </p>
        </div>
      </PiCard>

      <p class="reg-privacy t-secondary">
        By creating an account, your data stays on this server. We have no access to it.
      </p>

      <div class="reg-sign-in-link">
        <span class="t-secondary">Already have an account? </span>
        <router-link to="/login">Sign in →</router-link>
      </div>
    </form>
  </div>
</template>

<style scoped>
/* Mode toggle — absolute top-right */
.auth-mode-toggle {
  position: absolute;
  top: var(--space-6);
  right: var(--space-6);
}

.auth-text-link {
  color: var(--accent-primary);
  text-decoration: none;
  font-size: var(--text-sm);
}
.auth-text-link:hover { color: var(--accent-hover); }

/* ── Verification pending state ─────────────────────────────────────────── */
.reg-verify-wrap {
  width: 100%;
  max-width: 440px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  text-align: center;
  padding: var(--space-10) 0;
}

.reg-verify-pulse {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-2);
}

.reg-verify-title {
  font-size: var(--text-xl);
  font-family: var(--font-display);
  font-weight: 700;
}

.reg-verify-body {
  font-size: var(--text-base);
  line-height: 1.65;
}

.reg-verify-email {
  color: var(--text-primary);
  font-weight: 600;
}

.reg-verify-hint {
  font-size: var(--text-sm);
  line-height: 1.6;
  max-width: 340px;
}

.reg-verify-actions {
  margin-top: var(--space-4);
}

/* ── Form ────────────────────────────────────────────────────────────────── */
.reg-header {
  text-align: center;
  margin-bottom: var(--space-6);
}

.reg-logo-wrap {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-4);
}

.reg-title {
  font-size: var(--text-xl);
}

.reg-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── Plan selector ───────────────────────────────────────────────────────── */
.reg-plan-fieldset {
  border: none;
  padding: 0;
}

.reg-plan-options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.reg-plan-option {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s var(--ease), background 0.15s var(--ease);
}
.reg-plan-option:hover {
  border-color: var(--border-medium);
}
.reg-plan-option--selected {
  border-color: var(--accent-primary);
  background: var(--accent-surface);
}

.reg-plan-radio {
  accent-color: var(--accent-primary);
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.reg-plan-label {
  font-weight: 500;
  font-size: var(--text-sm);
  flex: 1;
}

.reg-plan-desc {
  font-size: var(--text-xs);
}

/* ── Strength meter ──────────────────────────────────────────────────────── */
.reg-strength {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--space-2);
}

.reg-strength__dot {
  width: 28px;
  height: 6px;
  border-radius: var(--radius-pill);
  transition: background 0.2s var(--ease);
}

.reg-strength__label {
  font-size: var(--text-xs);
  margin-left: var(--space-1);
}

/* ── Misc ────────────────────────────────────────────────────────────────── */
.reg-error-center {
  text-align: center;
}

.reg-privacy {
  font-size: var(--text-sm);
  text-align: center;
  margin-top: var(--space-4);
  line-height: 1.6;
}

.reg-sign-in-link {
  text-align: center;
  margin-top: var(--space-3);
  font-size: var(--text-sm);
}
</style>
