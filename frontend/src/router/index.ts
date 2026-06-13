import { createRouter, createWebHistory } from 'vue-router'
import {
  isAuthenticated,
  hasRefreshToken,
  refreshTokens,
} from '../composables/useAuth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
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
    { path: '/overview',   component: () => import('../views/OverviewView.vue') },
    { path: '/memory',     component: () => import('../views/MemoryBrowser.vue') },
    { path: '/repository', component: () => import('../views/FileRepository.vue') },
    { path: '/email',      component: () => import('../views/EmailView.vue') },
    { path: '/bank',   component: () => import('../views/BankAdviser.vue') },
    { path: '/health', component: () => import('../views/HealthView.vue') },
    { path: '/job', name: 'jobs', component: () => import('../views/JobsView.vue'), meta: { title: 'Job Hunt' } },
    { path: '/hermes',     component: () => import('../views/HermesView.vue') },
    { path: '/pulse',      component: () => import('../views/PulseFeed.vue'), meta: { title: 'Pulse' } },
    { path: '/signal',     component: () => import('../views/SignalPlayer.vue'), meta: { title: 'Signal' } },
    { path: '/settings',   component: () => import('../views/SettingsView.vue') },
    { path: '/finances',   component: () => import('../views/FinancesView.vue') },
    { path: '/about',      component: () => import('../views/AboutView.vue'), meta: { public: true } },
  ],
})

const PUBLIC = new Set(['/login', '/register', '/oauth/callback', '/about'])

router.beforeEach(async (to) => {
  if (PUBLIC.has(to.path)) return true
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
