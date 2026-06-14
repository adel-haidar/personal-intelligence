import { ref } from 'vue'
import { requireAuth } from './useAuth'
import { API_BASE } from '../config/env'

export interface BillingStatus {
  billing_enabled: boolean
  entitled: boolean
  subscription_status: string
  trial_days: number
  price_configured: boolean
  current_period_end: string | null
}

// Module-level cache so the router guard doesn't refetch on every navigation.
const status = ref<BillingStatus | null>(null)

async function fetchStatus(force = false): Promise<BillingStatus | null> {
  if (status.value && !force) return status.value
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/billing/status`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return null
    status.value = (await res.json()) as BillingStatus
    return status.value
  } catch {
    return null
  }
}

async function startCheckout(): Promise<void> {
  const token = await requireAuth()
  const res = await fetch(`${API_BASE}/api/billing/checkout`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  const data = await res.json().catch(() => ({}))
  if (res.ok && data.url) {
    window.location.href = data.url as string
    return
  }
  throw new Error(data.error || 'Could not start checkout. Please try again.')
}

async function openPortal(): Promise<void> {
  const token = await requireAuth()
  const res = await fetch(`${API_BASE}/api/billing/portal`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  const data = await res.json().catch(() => ({}))
  if (res.ok && data.url) {
    window.location.href = data.url as string
    return
  }
  throw new Error(data.error || 'Could not open the billing portal.')
}

function clearBillingStatus(): void {
  status.value = null
}

export function useBilling() {
  return { status, fetchStatus, startCheckout, openPortal, clearBillingStatus }
}

export { fetchStatus, clearBillingStatus }
