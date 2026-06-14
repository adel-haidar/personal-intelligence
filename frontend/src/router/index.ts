import { createRouter, createWebHistory } from 'vue-router'
import {
  isAuthenticated,
  hasRefreshToken,
  refreshTokens,
} from '../composables/useAuth'
import { fetchStatus as fetchBillingStatus } from '../composables/useBilling'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path:      '/',
      component: () => import('../views/LandingView.vue'),
      meta:      { public: true },
    },
    {
      path:      '/login',
      component: () => import('../views/Login.vue'),
      meta:      { public: true },
    },
    {
      path:      '/oauth/callback',
      component: () => import('../views/OAuthCallback.vue'),
      meta:      { public: true },
    },
    {
      path:      '/register',
      component: () => import('../views/Register.vue'),
      meta:      { public: true },
    },
    {
      path:      '/forgot-password',
      component: () => import('../views/ForgotPassword.vue'),
      meta:      { public: true },
    },
    {
      path:      '/reset-password',
      component: () => import('../views/ResetPassword.vue'),
      meta:      { public: true },
    },
    {
      path:      '/onboarding',
      component: () => import('../views/OnboardingView.vue'),
      meta:      { fullscreen: true },
    },
    {
      path:      '/subscribe',
      component: () => import('../views/SubscribeView.vue'),
      meta:      { fullscreen: true },
    },
    { path: '/overview',   component: () => import('../views/DashboardView.vue'), meta: { title: 'Dashboard' } },
    { path: '/memory',     component: () => import('../views/BrainView.vue'), meta: { title: 'Your Brain' } },
    { path: '/health', component: () => import('../views/HealthView.vue') },
    { path: '/job', name: 'jobs', component: () => import('../views/JobsView.vue'), meta: { title: 'Job Hunt' } },
    { path: '/pulse',      component: () => import('../views/PulseFeed.vue'), meta: { title: 'Pulse' } },
    { path: '/signal',     component: () => import('../views/SignalPlayer.vue'), meta: { title: 'Signal' } },
    { path: '/settings',   component: () => import('../views/SettingsView.vue') },
    // Finances — Calm-Intelligence redesign. Tabbed: Overview (plain-language
    // summary) + Spending & budget + Investments + Day trading, all wired to the
    // bank-adviser / advisory composables.
    { path: '/finances',   component: () => import('../views/FinancesView.vue'), meta: { title: 'Finances' } },
    { path: '/about',      component: () => import('../views/AboutView.vue'), meta: { public: true } },
  ],
})

const PUBLIC = new Set(['/', '/login', '/register', '/oauth/callback', '/about', '/forgot-password', '/reset-password'])

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

router.beforeEach(async (to) => {
  if (PUBLIC.has(to.path)) return true
  // Allow /onboarding when arriving from an email-verification link that carries ?token=
  const onboardingToken = to.path === '/onboarding' && to.query.token

  // 1. Authentication
  let authed = onboardingToken || isAuthenticated()
  if (!authed && hasRefreshToken()) {
    try {
      await refreshTokens()
      authed = true
    } catch {
      return `/login?redirect=${encodeURIComponent(to.fullPath)}`
    }
  }
  if (!authed) return `/login?redirect=${encodeURIComponent(to.fullPath)}`

  // 2. Billing gate (inert until BILLING_ENABLED on the server). Onboarding and
  //    the subscribe page itself are always reachable.
  if (to.path === '/subscribe' || to.path === '/onboarding') return true

  const billing = await fetchBillingStatus()
  if (billing?.billing_enabled && !billing.entitled) {
    // Just returned from Stripe Checkout — wait briefly for the webhook to land.
    if (to.query.checkout === 'success') {
      for (let i = 0; i < 5; i++) {
        const b = await fetchBillingStatus(true)
        if (b?.entitled) break
        await sleep(1000)
      }
      return true
    }
    return '/subscribe'
  }
  return true
})

export default router
