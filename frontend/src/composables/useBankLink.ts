import { ref } from 'vue'
import { requireAuth } from './useAuth'
import { API_BASE } from '../config/env'

// ── Types ───────────────────────────────────────────────────────────────────

export interface BankInstitution {
  id:   string
  name: string
  logo?: string | null
  bic?:  string | null
}

export interface BankStatus {
  connected:           boolean
  configured:          boolean
  status?:             'pending' | 'connected' | 'error' | 'expired'
  institution_name?:   string | null
  institution_id?:     string | null
  account_count?:      number
  last_sync_at?:       string | null
  last_balance?:       number | null
  consent_expires_at?: string | null
  last_error?:         string | null
}

const BASE = `${API_BASE}/api/bank`

async function authHeaders(): Promise<Record<string, string>> {
  const token = await requireAuth()
  return { Authorization: `Bearer ${token}` }
}

/**
 * Bank-account linking (GoCardless PSD2). The user picks their Sparkasse /
 * Volksbank, authenticates at their own bank via a redirect, and the brain is
 * then refreshed daily — no more monthly PDF uploads.
 */
export function useBankLink() {
  const status = ref<BankStatus | null>(null)
  const institutions = ref<BankInstitution[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadStatus(): Promise<void> {
    try {
      const res = await fetch(`${BASE}/status`, { headers: await authHeaders() })
      if (res.ok) status.value = await res.json()
    } catch {
      // Non-fatal: the card just stays in its last-known state.
    }
  }

  async function loadInstitutions(country = 'de'): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`${BASE}/institutions?country=${country}`, { headers: await authHeaders() })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Could not load banks')
      institutions.value = (await res.json()).institutions
    } catch (e: any) {
      error.value = e?.message || 'Could not load banks'
    } finally {
      loading.value = false
    }
  }

  /** Start consent: open the bank's login page (redirects back to /finances). */
  async function connect(institutionId: string): Promise<void> {
    error.value = null
    const res = await fetch(`${BASE}/authorize?institution_id=${encodeURIComponent(institutionId)}`, {
      headers: await authHeaders(),
    })
    if (!res.ok) {
      error.value = (await res.json().catch(() => ({}))).detail || 'Could not start bank connection'
      return
    }
    const { authorize_url } = await res.json()
    window.location.href = authorize_url
  }

  async function syncNow(): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`${BASE}/sync`, { method: 'POST', headers: await authHeaders() })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Sync failed')
      await loadStatus()
      return true
    } catch (e: any) {
      error.value = e?.message || 'Sync failed'
      return false
    } finally {
      loading.value = false
    }
  }

  async function disconnect(): Promise<void> {
    loading.value = true
    try {
      await fetch(BASE, { method: 'DELETE', headers: await authHeaders() })
      await loadStatus()
    } finally {
      loading.value = false
    }
  }

  return { status, institutions, loading, error, loadStatus, loadInstitutions, connect, syncNow, disconnect }
}
