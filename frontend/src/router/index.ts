import { createRouter, createWebHistory } from 'vue-router'
import {
  isAuthenticated,
  hasRefreshToken,
  refreshTokens,
} from '../composables/useAuth'

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
    { path: '/overview',   component: () => import('../views/DashboardView.vue'), meta: { title: 'Dashboard' } },
    { path: '/memory',     component: () => import('../views/BrainView.vue'), meta: { title: 'Your Brain' } },
    { path: '/email',      component: () => import('../views/EmailView.vue') },
    { path: '/health', component: () => import('../views/HealthView.vue') },
    { path: '/job', name: 'jobs', component: () => import('../views/JobsView.vue'), meta: { title: 'Job Hunt' } },
    { path: '/pulse',      component: () => import('../views/PulseFeed.vue'), meta: { title: 'Pulse' } },
    { path: '/signal',     component: () => import('../views/SignalPlayer.vue'), meta: { title: 'Signal' } },
    { path: '/settings',   component: () => import('../views/SettingsView.vue') },
    // Finances IS the bank adviser (statements, investing, day-trading analysis).
    { path: '/finances',   component: () => import('../views/BankAdviser.vue'), meta: { title: 'Finances' } },
    { path: '/about',      component: () => import('../views/AboutView.vue'), meta: { public: true } },
  ],
})

const PUBLIC = new Set(['/', '/login', '/register', '/oauth/callback', '/about', '/forgot-password', '/reset-password'])

router.beforeEach(async (to) => {
  if (PUBLIC.has(to.path)) return true
  // Allow /onboarding when arriving from an email-verification link that carries ?token=
  if (to.path === '/onboarding' && to.query.token) return true
  if (isAuthenticated()) return true
  if (hasRefreshToken()) {
    try {
      await refreshTokens()
      return true
    } catch {
      return `/login?redirect=${encodeURIComponent(to.fullPath)}`
    }
  }
  return `/login?redirect=${encodeURIComponent(to.fullPath)}`
})

export default router
