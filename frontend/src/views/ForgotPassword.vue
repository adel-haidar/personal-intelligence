<script setup lang="ts">
import { ref } from 'vue'
import { forgotPassword } from '../composables/useAuth'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiInput from '../components/ui/PiInput.vue'
import PiButton from '../components/ui/PiButton.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'

const email    = ref('')
const loading  = ref(false)
const sent     = ref(false)
const error    = ref('')

async function handleSubmit() {
  const trimmed = email.value.trim()
  if (!trimmed) {
    error.value = 'Email is required.'
    return
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
    error.value = 'Enter a valid email address.'
    return
  }

  loading.value = true
  error.value   = ''
  try {
    await forgotPassword(trimmed)
    sent.value = true
  } catch {
    // forgotPassword always resolves, but be defensive.
    sent.value = true
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="fp-shell">
    <div class="auth-mode-toggle">
      <ModeToggle :withLabel="false" />
    </div>

    <div class="fp-inner">
      <div class="fp-logo-wrap" aria-hidden="true">
        <BrainPulse :size="40" :slow="true" />
      </div>

      <h1 class="fp-title">Reset your password</h1>

      <!-- Sent state -->
      <div v-if="sent" class="fp-sent">
        <PiCard>
          <p class="fp-sent-text">
            If that email address is registered, we've sent a reset link. Check your inbox —
            the link expires in one hour.
          </p>
        </PiCard>
        <div class="fp-back">
          <router-link to="/login" class="auth-text-link">Back to sign in</router-link>
        </div>
      </div>

      <!-- Form -->
      <form v-else style="width: 100%;" @submit.prevent="handleSubmit" novalidate>
        <PiCard>
          <div class="fp-fields">
            <p class="fp-desc t-secondary">
              Enter your account email and we'll send you a link to reset your password.
            </p>

            <div class="pi-field">
              <label class="pi-label" for="fp-email">Email</label>
              <PiInput
                id="fp-email"
                v-model="email"
                type="email"
                placeholder="you@yourserver.com"
                autocomplete="email"
                :disabled="loading"
              />
              <p v-if="error" class="pi-field__error" role="alert">{{ error }}</p>
            </div>

            <PiButton variant="cta" :block="true" :loading="loading" type="submit">
              Send reset link
            </PiButton>
          </div>
        </PiCard>

        <div class="fp-back">
          <router-link to="/login" class="auth-text-link auth-text-link--muted">
            Back to sign in
          </router-link>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.fp-shell {
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

.fp-inner {
  width: 100%;
  max-width: 440px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-5);
}

.fp-logo-wrap {
  display: flex;
  justify-content: center;
}

.fp-title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 700;
  text-align: center;
}

.fp-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.fp-desc {
  font-size: var(--text-sm);
  line-height: 1.6;
}

.fp-sent {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.fp-sent-text {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.65;
}

.fp-back {
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
