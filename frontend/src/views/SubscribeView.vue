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

const route = useRoute()
const router = useRouter()
const { status, fetchStatus, startCheckout } = useBilling()

const loading = ref(false)
const error = ref('')
const canceled = computed(() => route.query.checkout === 'cancel')

const trialDays = computed(() => status.value?.trial_days ?? 0)

const VALUE_PROPS = [
  'Your private AI brain — memory, health, finances, and a feed that learns from you',
  'No ads, no tracking, nothing sold. Your data stays on your server',
  'Cancel anytime from your account',
]

onMounted(async () => {
  const s = await fetchStatus(true)
  // Already subscribed? Don't strand them here.
  if (s && (!s.billing_enabled || s.entitled)) {
    router.replace('/overview')
  }
})

async function subscribe() {
  loading.value = true
  error.value = ''
  try {
    await startCheckout() // redirects to Stripe on success
  } catch (e) {
    error.value = (e as Error).message
    loading.value = false
  }
}
</script>

<template>
  <div class="pi-auth pi-auth--single">
    <div style="position: absolute; top: var(--space-6); right: var(--space-6);"><ModeToggle /></div>

    <div style="width: 100%; max-width: 460px;">
      <div style="text-align: center; margin-bottom: var(--space-6);">
        <div style="display: flex; justify-content: center; margin-bottom: var(--space-4);">
          <BrainPulse :size="48" :slow="true" aria-hidden="true" />
        </div>
        <h1 style="font-size: var(--text-xl);">Activate your membership</h1>
        <p class="t-secondary" style="font-size: var(--text-base); margin-top: var(--space-2);">
          One subscription unlocks everything in Private Internet.
        </p>
      </div>

      <PiCard>
        <div
          v-if="canceled"
          style="font-size: var(--text-sm); color: var(--text-secondary); background: var(--background-raised); border-radius: var(--radius-sm); padding: var(--space-3) var(--space-4); margin-bottom: var(--space-4);"
        >
          Checkout canceled — you can subscribe whenever you're ready.
        </div>

        <ul style="list-style: none; display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-5);">
          <li v-for="(p, i) in VALUE_PROPS" :key="i" style="display: flex; gap: var(--space-3); align-items: flex-start;">
            <span style="color: var(--brain-amber); display: flex; flex: 0 0 auto; margin-top: 1px;"><PIIcon name="check" :size="16" /></span>
            <span style="font-size: var(--text-sm); line-height: 1.55;">{{ p }}</span>
          </li>
        </ul>

        <PiButton variant="cta" block :loading="loading" @click="subscribe">
          {{ trialDays > 0 ? `Start ${trialDays}-day free trial` : 'Subscribe' }}
        </PiButton>

        <p v-if="error" class="pi-field__error" role="alert" style="text-align: center; margin-top: var(--space-3);">{{ error }}</p>

        <p class="t-tertiary" style="font-size: var(--text-xs); text-align: center; margin-top: var(--space-4); line-height: 1.5;">
          Secure checkout by Stripe. {{ trialDays > 0 ? 'No charge until your trial ends. ' : '' }}Cancel anytime.
        </p>
      </PiCard>

      <div style="text-align: center; margin-top: var(--space-4); font-size: var(--text-sm);">
        <a href="#" class="t-secondary" @click.prevent="logout(); router.replace('/login')">Sign out</a>
      </div>
    </div>
  </div>
</template>
