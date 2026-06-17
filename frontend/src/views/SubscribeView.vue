<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiButton from '../components/ui/PiButton.vue'
import PiCard from '../components/ui/PiCard.vue'
import PIIcon from '../components/ui/PIIcon.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'
import { useBilling } from '../composables/useBilling'
import { logout } from '../composables/useAuth'
import { PLANS, resolveFeature } from '../config/plans'

const route = useRoute()
const router = useRouter()
const { status, fetchStatus, startCheckout, openPortal, redeemCoupon } = useBilling()

const loading = ref<string | null>(null) // stores which plan key is loading
const error = ref('')
const canceled = computed(() => route.query.checkout === 'cancel')

// ── Coupon / access code redemption (testers & early adopters) ──
const couponCode = ref('')
const couponLoading = ref(false)
const couponError = ref('')
const couponSuccess = ref('')

async function redeem() {
  const code = couponCode.value.trim()
  if (!code || couponLoading.value) return
  couponLoading.value = true
  couponError.value = ''
  couponSuccess.value = ''
  try {
    const plan = await redeemCoupon(code)
    couponSuccess.value = `Code applied — you're on ${plan === 'max' ? 'Max' : plan} now. Taking you in…`
    setTimeout(() => router.replace('/overview'), 900)
  } catch (e) {
    couponError.value = (e as Error).message
  } finally {
    couponLoading.value = false
  }
}

// When the route guard (or a 402) sends the user here, ?feature=… tells us what
// they were trying to reach so we can explain which plan unlocks it.
const lockedFeature = computed(() => resolveFeature(route.query.feature as string | undefined))

const currentPlan = computed(() => status.value?.plan ?? 'free')

const hasCustomer = computed(() => {
  const s = status.value
  return s ? (s.subscription_status !== 'inactive' && s.subscription_status !== '') : false
})

onMounted(async () => {
  const s = await fetchStatus(true)
  // If billing is entirely disabled, nothing to buy — go to the app.
  if (s && !s.billing_enabled) {
    router.replace('/overview')
  }
})

async function subscribe(plan: 'pro' | 'max') {
  loading.value = plan
  error.value = ''
  try {
    await startCheckout(plan) // redirects to Stripe on success
  } catch (e) {
    error.value = (e as Error).message
    loading.value = null
  }
}

async function managePortal() {
  loading.value = 'portal'
  error.value = ''
  try {
    await openPortal()
  } catch (e) {
    error.value = (e as Error).message
    loading.value = null
  }
}
</script>

<template>
  <div class="pi-auth pi-auth--wide">
    <div style="position: absolute; top: var(--space-6); right: var(--space-6);"><ModeToggle /></div>

    <div class="sub__inner">
      <!-- Header -->
      <div class="sub__hero">
        <div style="display: flex; justify-content: center; margin-bottom: var(--space-4);">
          <BrainPulse :size="48" :slow="true" aria-hidden="true" />
        </div>
        <h1 style="font-size: var(--text-xl); text-align: center;">Choose your plan</h1>
        <p class="t-secondary" style="font-size: var(--text-base); margin-top: var(--space-2); text-align: center;">
          Start free. Upgrade when you want more.
        </p>
      </div>

      <!-- Upgrade-context banner (arrived from a locked feature) -->
      <div v-if="lockedFeature" class="sub__notice sub__notice--upgrade">
        <span class="sub__notice-icon" aria-hidden="true"><PIIcon name="lock" :size="16" /></span>
        <span>
          <strong>{{ lockedFeature.label }}</strong> is part of the
          <strong>{{ lockedFeature.plan === 'max' ? 'Max' : 'Pro' }}</strong> plan.
          Upgrade below to unlock it.
        </span>
      </div>

      <!-- Canceled notice -->
      <div
        v-if="canceled"
        class="sub__notice"
      >
        Checkout canceled — you can subscribe whenever you're ready.
      </div>

      <!-- Error -->
      <p v-if="error" class="pi-field__error" role="alert" style="text-align: center; margin-bottom: var(--space-4);">{{ error }}</p>

      <!-- Pricing grid -->
      <div class="sub__grid">
        <PiCard
          v-for="plan in PLANS"
          :key="plan.key"
          class="sub__card"
          :class="{ 'sub__card--highlight': plan.highlight, 'sub__card--current': currentPlan === plan.key }"
        >
          <!-- Highlight badge -->
          <div v-if="plan.highlight" class="sub__badge">Most popular</div>

          <!-- Current plan badge -->
          <div v-if="currentPlan === plan.key" class="sub__current-badge">Current plan</div>

          <div class="sub__card-header">
            <span class="sub__plan-name">{{ plan.name }}</span>
            <div class="sub__price-row">
              <span class="sub__amount">{{ plan.price }}</span>
              <span v-if="plan.period" class="sub__period t-tertiary">{{ plan.period }}</span>
            </div>
          </div>

          <ul class="sub__features">
            <li v-for="feat in plan.features" :key="feat" class="sub__feature">
              <span class="sub__check"><PIIcon name="check" :size="14" /></span>
              <span>{{ feat }}</span>
            </li>
          </ul>

          <!-- CTA -->
          <div class="sub__cta-wrap">
            <!-- Free: already on it — let the user into the app's free features -->
            <template v-if="plan.key === 'free'">
              <PiButton
                v-if="currentPlan === 'free'"
                variant="secondary"
                block
                @click="router.replace('/overview')"
              >
                Continue with Free
              </PiButton>
              <PiButton
                v-else
                variant="ghost"
                block
                :disabled="true"
              >
                Included
              </PiButton>
            </template>

            <!-- Paid plans -->
            <template v-else>
              <PiButton
                v-if="currentPlan === plan.key"
                variant="secondary"
                block
                :disabled="true"
              >
                Current plan
              </PiButton>
              <PiButton
                v-else
                :variant="plan.highlight ? 'cta' : 'primary'"
                block
                :loading="loading === plan.key"
                :disabled="loading !== null"
                @click="subscribe(plan.key as 'pro' | 'max')"
              >
                {{ plan.cta }}
              </PiButton>
            </template>
          </div>
        </PiCard>
      </div>

      <!-- Coupon / access code (testers & early adopters) -->
      <div class="sub__coupon">
        <p class="sub__coupon-label t-secondary">
          Have a gift or early-adopter code? Enter it to unlock everything.
        </p>
        <form class="sub__coupon-row" @submit.prevent="redeem">
          <input
            v-model="couponCode"
            type="text"
            class="pi-input sub__coupon-input"
            placeholder="Enter your code"
            autocapitalize="characters"
            autocomplete="off"
            spellcheck="false"
            :disabled="couponLoading"
            aria-label="Access code"
          />
          <PiButton
            type="submit"
            variant="secondary"
            :loading="couponLoading"
            :disabled="!couponCode.trim() || couponLoading"
          >
            Redeem
          </PiButton>
        </form>
        <p v-if="couponError" class="pi-field__error" role="alert" style="margin-top: var(--space-2);">{{ couponError }}</p>
        <p v-if="couponSuccess" class="sub__coupon-success" role="status">{{ couponSuccess }}</p>
      </div>

      <!-- Manage billing link (visible once user has an active subscription) -->
      <div v-if="hasCustomer" style="text-align: center; margin-top: var(--space-6);">
        <button
          class="sub__portal-link t-secondary"
          :disabled="loading === 'portal'"
          @click="managePortal"
        >
          {{ loading === 'portal' ? 'Opening portal…' : 'Manage billing' }}
        </button>
      </div>

      <p class="t-tertiary" style="font-size: var(--text-xs); text-align: center; margin-top: var(--space-5); line-height: 1.5;">
        Secure checkout by Stripe. Cancel anytime.
      </p>

      <div style="text-align: center; margin-top: var(--space-4); font-size: var(--text-sm);">
        <a href="#" class="t-secondary" @click.prevent="logout(); router.replace('/login')">Sign out</a>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Override pi-auth to allow wider content for the 3-column grid */
.pi-auth--wide {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-6);
  background: var(--background-page);
  position: relative;
}

.sub__inner {
  width: 100%;
  max-width: 860px;
}

.sub__hero {
  margin-bottom: var(--space-8);
}

.sub__notice {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  background: var(--background-raised);
  border-radius: var(--radius-sm);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-6);
  text-align: center;
}

.sub__notice--upgrade {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  text-align: left;
  background: var(--accent-surface);
  color: var(--text-primary);
  border: 1px solid var(--accent-primary);
}

.sub__notice-icon {
  color: var(--accent-primary);
  display: flex;
  flex-shrink: 0;
}

.sub__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-4);
  align-items: start;
}

.sub__card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
}

.sub__card--highlight {
  border-color: var(--accent-primary) !important;
  background: var(--accent-surface) !important;
}

.sub__card--current {
  border-color: var(--brain-amber) !important;
}

.sub__badge {
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--accent-primary);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 3px 12px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.sub__current-badge {
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--brain-amber);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 3px 12px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.sub__card-header {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.sub__plan-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.sub__price-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
}

.sub__amount {
  font-family: var(--font-mono);
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
}

.sub__period {
  font-size: var(--text-sm);
}

.sub__features {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  flex: 1;
}

.sub__feature {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.45;
}

.sub__check {
  color: var(--success);
  flex-shrink: 0;
  margin-top: 1px;
}

.sub__cta-wrap {
  margin-top: auto;
}

.sub__coupon {
  margin-top: var(--space-8);
  padding-top: var(--space-6);
  border-top: 1px solid var(--border-subtle);
  max-width: 460px;
  margin-left: auto;
  margin-right: auto;
  text-align: center;
}

.sub__coupon-label {
  font-size: var(--text-sm);
  margin-bottom: var(--space-3);
}

.sub__coupon-row {
  display: flex;
  gap: var(--space-2);
  align-items: stretch;
}

.sub__coupon-input {
  flex: 1;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sub__coupon-success {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--success);
}

.sub__portal-link {
  background: none;
  border: none;
  cursor: pointer;
  font-size: var(--text-sm);
  text-decoration: underline;
  text-underline-offset: 2px;
  padding: 0;
}
.sub__portal-link:disabled {
  opacity: 0.5;
  cursor: default;
}
.sub__portal-link:hover:not(:disabled) {
  color: var(--text-primary);
}

@media (max-width: 600px) {
  .sub__grid {
    grid-template-columns: 1fr;
  }
}
</style>
