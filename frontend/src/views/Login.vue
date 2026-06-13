<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  initiateLogin,
  hasRefreshToken,
  refreshTokens,
  isAuthenticated,
  loginWithPassword,
  resendVerification,
  AuthHttpError,
} from '../composables/useAuth'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiCard from '../components/ui/PiCard.vue'
import PiInput from '../components/ui/PiInput.vue'
import PiButton from '../components/ui/PiButton.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'
import PIIcon from '../components/ui/PIIcon.vue'

const router  = useRouter()
const vRoute  = useRoute()

const email    = ref('')
const password = ref('')

const loading        = ref(false)
const oauthLoading   = ref(false)
const resuming       = ref(false)
const error          = ref('')
const hasSession     = computed(() => hasRefreshToken())

/** Set when backend returns 403 email_not_verified */
const emailNotVerified     = ref(false)
const resendEmail          = ref('')
const resendLoading        = ref(false)
const resendSent           = ref(false)

/** Banner from ?verify_error= query param (email link redirected back here) */
const verifyErrorBanner = computed<string | null>(() => {
  const q = vRoute.query.verify_error as string | undefined
  if (q === 'expired') return 'That verification link has expired. Request a new one below.'
  if (q === 'invalid') return 'That verification link is invalid or already used.'
  return null
})

/** Banner when landing on /login?verified=... (shouldn't happen per spec, but defensive) */

const intendedRoute = computed(
  () => (vRoute.query.redirect as string | undefined) ?? '/overview'
)

onMounted(() => {
  if (isAuthenticated()) {
    router.replace(intendedRoute.value)
  }
})

async function handleLogin() {
  if (!email.value.trim() || !password.value) {
    error.value = 'Email and password are required.'
    return
  }
  loading.value        = true
  error.value          = ''
  emailNotVerified.value = false

  try {
    await loginWithPassword({ email: email.value.trim(), password: password.value })
    router.replace(intendedRoute.value)
  } catch (e) {
    const err = e as AuthHttpError

    if (err.status === 404) {
      error.value = 'No account found with this email address.'
    } else if (err.status === 401) {
      error.value = 'Incorrect password.'
    } else if (err.status === 403 && err.message === 'email_not_verified') {
      emailNotVerified.value = true
      resendEmail.value = email.value.trim()
    } else {
      error.value = err.message ?? 'Login failed'
    }

    loading.value = false
  }
}

async function handleResendVerification() {
  if (resendLoading.value || resendSent.value) return
  resendLoading.value = true
  try {
    await resendVerification(resendEmail.value)
    resendSent.value = true
  } finally {
    resendLoading.value = false
  }
}

async function handleOAuth() {
  oauthLoading.value = true
  error.value        = ''
  try {
    await initiateLogin(intendedRoute.value)
    // Hard redirect happens inside initiateLogin — never reached.
  } catch (e) {
    error.value        = (e as Error).message ?? 'Failed to start login'
    oauthLoading.value = false
  }
}

async function handleResume() {
  resuming.value = true
  error.value    = ''
  try {
    await refreshTokens()
    router.replace(intendedRoute.value)
  } catch (e) {
    error.value    = (e as Error).message ?? 'Session could not be resumed'
    resuming.value = false
  }
}

const VALUE_PROPS = [
  'Everything learns from your private memory',
  'No ads. No tracking. No corporate servers.',
  'The more you share, the smarter it gets.',
]
</script>

<template>
  <div class="pi-auth">
    <!-- Left: identity / brand panel -->
    <div class="pi-auth__brand">
      <div class="auth-brand-inner">
        <div class="auth-logo-wrap">
          <BrainPulse :size="64" :slow="true" aria-hidden="true" />
        </div>
        <h1 class="auth-product-name">Private Internet</h1>
        <p class="auth-tagline t-serif">Your AI. Your server. Your rules.</p>

        <ul class="auth-value-props" role="list">
          <li v-for="(prop, i) in VALUE_PROPS" :key="i" class="auth-value-prop">
            <span class="auth-check-icon" aria-hidden="true">
              <PIIcon name="check" :size="16" />
            </span>
            <span>{{ prop }}</span>
          </li>
        </ul>

        <div class="auth-brand-links">
          <router-link to="/" class="auth-text-link">Home</router-link>
          <span class="t-tertiary" aria-hidden="true">·</span>
          <router-link to="/about" class="auth-text-link">How it works</router-link>
          <span class="t-tertiary" aria-hidden="true">·</span>
          <a
            href="https://github.com/personal-intelligence"
            target="_blank"
            rel="noopener noreferrer"
            class="auth-text-link"
          >GitHub</a>
        </div>
      </div>
    </div>

    <!-- Right: sign-in form -->
    <div class="pi-auth__form">
      <div class="auth-mode-toggle">
        <ModeToggle :withLabel="false" />
      </div>

      <!-- verify_error banner -->
      <div
        v-if="verifyErrorBanner"
        class="auth-banner auth-banner--warning"
        role="alert"
        style="width: 100%; max-width: 360px; margin-bottom: var(--space-4);"
      >
        <PIIcon name="shield" :size="14" aria-hidden="true" />
        {{ verifyErrorBanner }}
        <button
          v-if="email"
          class="auth-banner__action"
          type="button"
          @click="resendEmail = email; handleResendVerification()"
        >Resend verification</button>
      </div>

      <form style="width: 100%; max-width: 360px;" @submit.prevent="handleLogin" novalidate>
        <PiCard>
          <h2 class="auth-card-title">Sign in</h2>

          <div class="auth-fields">
            <div class="pi-field">
              <label class="pi-label" for="login-email">Email</label>
              <PiInput
                id="login-email"
                v-model="email"
                type="email"
                placeholder="you@yourserver.com"
                autocomplete="email"
                :disabled="loading"
              />
            </div>

            <div class="pi-field">
              <div class="auth-password-label-row">
                <label class="pi-label" for="login-password">Password</label>
                <router-link to="/forgot-password" class="auth-text-link auth-text-link--muted auth-text-link--sm">
                  Forgot password?
                </router-link>
              </div>
              <PiInput
                id="login-password"
                v-model="password"
                type="password"
                placeholder="••••••••••••"
                autocomplete="current-password"
                :disabled="loading"
              />
            </div>

            <PiButton variant="cta" :block="true" :loading="loading" type="submit">
              Sign in →
            </PiButton>

            <!-- Generic error -->
            <p v-if="error" class="pi-field__error auth-error-center" role="alert">
              {{ error }}
            </p>

            <!-- Email not verified error -->
            <div v-if="emailNotVerified" class="auth-verify-error" role="alert">
              <p class="pi-field__error auth-error-center">
                Please verify your email before signing in.
              </p>
              <div class="auth-verify-error__action">
                <span v-if="resendSent" class="auth-resend-sent t-secondary">
                  Verification email sent. Check your inbox.
                </span>
                <button
                  v-else
                  type="button"
                  class="auth-resend-btn"
                  :disabled="resendLoading"
                  @click="handleResendVerification"
                >
                  {{ resendLoading ? 'Sending…' : 'Resend verification →' }}
                </button>
              </div>
            </div>
          </div>
        </PiCard>

        <!-- OAuth / secondary auth -->
        <div class="auth-divider" aria-hidden="true">
          <span class="auth-divider__line" />
          <span class="auth-divider__label t-tertiary">or</span>
          <span class="auth-divider__line" />
        </div>

        <PiButton
          variant="secondary"
          :block="true"
          :loading="oauthLoading"
          :disabled="resuming"
          type="button"
          @click="handleOAuth"
        >
          Continue with OAuth 2.1
        </PiButton>

        <div v-if="hasSession" class="auth-resume">
          <span class="auth-resume__text t-tertiary">Session token found.</span>
          <button
            type="button"
            class="auth-resume__link"
            :disabled="resuming"
            @click="handleResume"
          >{{ resuming ? 'Resuming…' : 'Resume session →' }}</button>
        </div>

        <div class="auth-switch-link">
          <span class="t-secondary">New here? </span>
          <router-link to="/register">Create an account</router-link>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
/* Brand panel inner layout */
.auth-brand-inner {
  max-width: 380px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.auth-logo-wrap {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-5);
}

.auth-product-name {
  font-size: var(--text-xl);
  text-align: center;
  margin-bottom: var(--space-2);
}

.auth-tagline {
  text-align: center;
  color: var(--text-secondary);
  font-size: var(--text-md);
  font-style: italic;
  margin-bottom: var(--space-8);
}

/* Value props list */
.auth-value-props {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  width: 100%;
  margin-bottom: var(--space-8);
}

.auth-value-prop {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  font-size: var(--text-base);
}

.auth-check-icon {
  color: var(--brain-amber);
  display: flex;
  flex: 0 0 auto;
}

.auth-brand-links {
  display: flex;
  gap: var(--space-4);
  justify-content: center;
  align-items: center;
}

.auth-text-link {
  font-size: var(--text-sm);
  color: var(--accent-primary);
  text-decoration: none;
}
.auth-text-link:hover { color: var(--accent-hover); }
.auth-text-link--muted { color: var(--text-tertiary); }
.auth-text-link--muted:hover { color: var(--text-secondary); }
.auth-text-link--sm { font-size: var(--text-xs); }

/* Mode toggle — absolute top-right of form panel */
.auth-mode-toggle {
  position: absolute;
  top: var(--space-6);
  right: var(--space-6);
}

/* Password field: label + forgot link on same row */
.auth-password-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

/* Card internals */
.auth-card-title {
  font-size: var(--text-md);
  margin-bottom: var(--space-5);
}

.auth-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Error below CTA */
.auth-error-center {
  text-align: center;
}

/* Email-not-verified compound error block */
.auth-verify-error {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-items: center;
}

.auth-verify-error__action {
  text-align: center;
}

.auth-resend-btn {
  background: none;
  border: none;
  padding: 0;
  color: var(--accent-primary);
  font-size: var(--text-sm);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.auth-resend-btn:hover:not(:disabled) { color: var(--accent-hover); }
.auth-resend-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.auth-resend-sent {
  font-size: var(--text-sm);
}

/* Info/warning banner */
.auth-banner {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  line-height: 1.55;
  flex-wrap: wrap;
}
.auth-banner--warning {
  background: var(--warning-surface);
  color: var(--warning);
  border: 1px solid var(--warning);
}
.auth-banner__action {
  background: none;
  border: none;
  padding: 0;
  color: var(--warning);
  font-size: var(--text-sm);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
  margin-left: auto;
}
.auth-banner__action:hover { opacity: 0.8; }

/* Divider between password login and OAuth */
.auth-divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-4) 0;
}
.auth-divider__line {
  flex: 1;
  height: 1px;
  background: var(--border-subtle);
}
.auth-divider__label {
  font-size: var(--text-xs);
}

/* Session resume row */
.auth-resume {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-top: var(--space-3);
}
.auth-resume__text {
  font-size: var(--text-sm);
}
.auth-resume__link {
  font-size: var(--text-sm);
  color: var(--accent-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
}
.auth-resume__link:disabled { opacity: 0.4; cursor: not-allowed; }
.auth-resume__link:hover:not(:disabled) { color: var(--accent-hover); }

/* Bottom nav link */
.auth-switch-link {
  text-align: center;
  margin-top: var(--space-4);
  font-size: var(--text-sm);
}
</style>
