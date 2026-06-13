<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { registerWithPassword } from '../composables/useAuth'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiInput from '../components/ui/PiInput.vue'
import PiButton from '../components/ui/PiButton.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'

const router = useRouter()

const email          = ref('')
const displayName    = ref('')
const password       = ref('')
const confirmPass    = ref('')
const referralSource = ref('')

const loading        = ref(false)
const error          = ref('')
const fieldErrors    = ref<Record<string, string>>({})

// Password strength: 3 dots — amber at ≥6/≥12, all green at ≥16
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

// Inline confirm-mismatch error (shown without needing submit)
const confirmMismatch = computed(() =>
  confirmPass.value.length > 0 && confirmPass.value !== password.value
)

function validate(): boolean {
  const errs: Record<string, string> = {}

  if (!email.value.trim()) {
    errs.email = 'Email is required.'
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) {
    errs.email = 'Enter a valid email address.'
  }

  if (!displayName.value.trim()) {
    errs.displayName = 'Display name is required.'
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
    await registerWithPassword({
      email:         email.value.trim(),
      display_name:  displayName.value.trim(),
      password:      password.value,
      ...(referralSource.value.trim()
        ? { referral_source: referralSource.value.trim() }
        : {}),
    })
    // TODO: redirect to /onboarding once Section 3 lands
    router.replace('/')
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

    <form style="width: 100%; max-width: 480px;" @submit.prevent="handleRegister" novalidate>
      <!-- Header -->
      <div class="reg-header">
        <div class="reg-logo-wrap">
          <BrainPulse :size="48" :slow="true" aria-hidden="true" />
        </div>
        <h1 class="reg-title">Create your account</h1>
      </div>

      <PiCard>
        <div class="reg-fields">
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
            <p v-if="!fieldErrors.displayName" class="pi-field__hint">
              Shown throughout the app — not a username.
            </p>
            <p v-if="fieldErrors.displayName" class="pi-field__error" role="alert">
              {{ fieldErrors.displayName }}
            </p>
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

          <!-- CTA — spinner in place of label while loading -->
          <PiButton variant="cta" :block="true" :loading="loading" type="submit">
            Create account
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

/* Header above the card */
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

/* Fields inside card */
.reg-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* 3-dot strength meter */
.reg-strength {
  display: flex;
  gap: 6px;
  margin-top: var(--space-2);
}

.reg-strength__dot {
  width: 28px;
  height: 6px;
  border-radius: var(--radius-pill);
  transition: background 0.2s var(--ease);
}

/* Server-level error */
.reg-error-center {
  text-align: center;
}

/* Privacy note */
.reg-privacy {
  font-size: var(--text-sm);
  text-align: center;
  margin-top: var(--space-4);
  line-height: 1.6;
}

/* Sign in link */
.reg-sign-in-link {
  text-align: center;
  margin-top: var(--space-3);
  font-size: var(--text-sm);
}
</style>
