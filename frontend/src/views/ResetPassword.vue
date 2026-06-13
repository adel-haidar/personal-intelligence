<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { resetPassword } from '../composables/useAuth'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiInput from '../components/ui/PiInput.vue'
import PiButton from '../components/ui/PiButton.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'
import PIIcon from '../components/ui/PIIcon.vue'

const route = useRoute()

const token       = ref('')
const newPassword = ref('')
const confirmPass = ref('')
const loading     = ref(false)
const error       = ref('')
const success     = ref(false)
const tokenMissing = ref(false)

onMounted(() => {
  const t = route.query.token as string | undefined
  if (t) {
    token.value = t
  } else {
    tokenMissing.value = true
  }
})

// Password strength: 0–3
const strength = computed<number>(() => {
  const l = newPassword.value.length
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

const confirmMismatch = computed(() =>
  confirmPass.value.length > 0 && confirmPass.value !== newPassword.value
)

async function handleSubmit() {
  error.value = ''

  if (!newPassword.value) {
    error.value = 'New password is required.'
    return
  }
  if (newPassword.value.length < 12) {
    error.value = 'Password must be at least 12 characters.'
    return
  }
  if (newPassword.value !== confirmPass.value) {
    error.value = 'Passwords do not match.'
    return
  }

  loading.value = true
  try {
    await resetPassword(token.value, newPassword.value)
    success.value = true
  } catch (e) {
    error.value = (e as Error).message ?? 'Password reset failed. The link may have expired.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="rp-shell">
    <div class="auth-mode-toggle">
      <ModeToggle :withLabel="false" />
    </div>

    <div class="rp-inner">
      <div class="rp-logo-wrap" aria-hidden="true">
        <BrainPulse :size="40" :slow="true" />
      </div>

      <h1 class="rp-title">Set a new password</h1>

      <!-- Token missing -->
      <div v-if="tokenMissing" class="rp-state">
        <PiCard>
          <div class="rp-state-inner">
            <PIIcon name="shield" :size="24" class="rp-state-icon rp-state-icon--warn" aria-hidden="true" />
            <p class="rp-state-text t-secondary">
              This link is missing a reset token. Please request a new password reset.
            </p>
          </div>
        </PiCard>
        <div class="rp-back">
          <router-link to="/forgot-password" class="auth-text-link">Request a new link</router-link>
        </div>
      </div>

      <!-- Success -->
      <div v-else-if="success" class="rp-state">
        <PiCard>
          <div class="rp-state-inner">
            <PIIcon name="check" :size="24" class="rp-state-icon rp-state-icon--success" aria-hidden="true" />
            <p class="rp-state-text t-secondary">
              Your password has been updated. You can now sign in with your new credentials.
            </p>
          </div>
        </PiCard>
        <div class="rp-back">
          <router-link to="/login" class="auth-text-link">Sign in →</router-link>
        </div>
      </div>

      <!-- Form -->
      <form v-else style="width: 100%;" @submit.prevent="handleSubmit" novalidate>
        <PiCard>
          <div class="rp-fields">
            <!-- New password -->
            <div class="pi-field">
              <label class="pi-label" for="rp-password">New password</label>
              <PiInput
                id="rp-password"
                v-model="newPassword"
                type="password"
                placeholder="••••••••••••"
                autocomplete="new-password"
                :disabled="loading"
              />
              <!-- 3-dot strength meter -->
              <div class="rp-strength" aria-hidden="true">
                <span
                  v-for="i in [0, 1, 2]"
                  :key="i"
                  class="rp-strength__dot"
                  :style="{ background: dotColor(i) }"
                />
              </div>
              <p class="pi-field__hint">At least 12 characters.</p>
            </div>

            <!-- Confirm -->
            <div class="pi-field">
              <label class="pi-label" for="rp-confirm">Confirm new password</label>
              <PiInput
                id="rp-confirm"
                v-model="confirmPass"
                type="password"
                placeholder="••••••••••••"
                autocomplete="new-password"
                :disabled="loading"
                :error="confirmMismatch ? 'error' : ''"
              />
              <p v-if="confirmMismatch" class="pi-field__error" role="alert">
                Passwords do not match.
              </p>
            </div>

            <PiButton variant="cta" :block="true" :loading="loading" type="submit">
              Set new password
            </PiButton>

            <p v-if="error" class="pi-field__error rp-error-center" role="alert">
              {{ error }}
            </p>
          </div>
        </PiCard>

        <div class="rp-back">
          <router-link to="/login" class="auth-text-link auth-text-link--muted">
            Back to sign in
          </router-link>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.rp-shell {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  position: relative;
  background: var(--background-page);
}

.auth-mode-toggle {
  position: absolute;
  top: var(--space-6);
  right: var(--space-6);
}

.rp-inner {
  width: 100%;
  max-width: 440px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-5);
}

.rp-logo-wrap {
  display: flex;
  justify-content: center;
}

.rp-title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 700;
  text-align: center;
}

.rp-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Strength meter */
.rp-strength {
  display: flex;
  gap: 6px;
  margin-top: var(--space-2);
}

.rp-strength__dot {
  width: 28px;
  height: 6px;
  border-radius: var(--radius-pill);
  transition: background 0.2s var(--ease);
}

.rp-error-center {
  text-align: center;
}

/* State cards (success / error) */
.rp-state {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.rp-state-inner {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.rp-state-icon {
  flex-shrink: 0;
  margin-top: 2px;
}
.rp-state-icon--success { color: var(--success); }
.rp-state-icon--warn    { color: var(--warning); }

.rp-state-text {
  font-size: var(--text-sm);
  line-height: 1.65;
}

.rp-back {
  text-align: center;
  margin-top: var(--space-2);
}

.auth-text-link {
  color: var(--accent-primary);
  font-size: var(--text-sm);
  text-decoration: none;
}
.auth-text-link:hover { color: var(--accent-hover); }
.auth-text-link--muted { color: var(--text-tertiary); }
.auth-text-link--muted:hover { color: var(--text-secondary); }
</style>
