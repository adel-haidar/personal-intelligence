import { requireAuth, refreshTokens, hasRefreshToken } from '../composables/useAuth'
import type {
  MatchesResponse,
  RunResponse,
  RunReport,
  JobStatus,
  CountriesResponse,
  PlatformsResponse,
  JobApplication,
  StartApplicationResponse,
  ApplyResponse,
} from '../types/jobs'
import { API_BASE } from '../config/env'

const BASE = API_BASE

async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  let token = await requireAuth()

  const makeRequest = (t: string) =>
    fetch(url, {
      ...options,
      headers: {
        Authorization: `Bearer ${t}`,
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> ?? {}),
      },
    })

  let res = await makeRequest(token)

  // Only refresh when a refresh token exists (OAuth sessions). Password-login
  // sessions have none — refreshing there clears the session and logs the user
  // out on any 401 (e.g. the agents service rejecting a non-admin JWT).
  if (res.status === 401 && hasRefreshToken()) {
    await refreshTokens()
    token = await requireAuth()
    res = await makeRequest(token)
  }

  return res
}

export async function fetchMatches(params: {
  tier?: string
  country?: string
  status?: string
  platform?: string
}): Promise<MatchesResponse> {
  const query = new URLSearchParams()
  if (params.tier)     query.set('tier',     params.tier)
  if (params.country)  query.set('country',  params.country)
  if (params.status)   query.set('status',   params.status)
  if (params.platform) query.set('platform', params.platform)

  const qs = query.toString()
  const res = await authFetch(`${BASE}/api/jobs/matches${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`Failed to fetch matches: HTTP ${res.status}`)
  return res.json() as Promise<MatchesResponse>
}

export async function fetchCountries(): Promise<CountriesResponse> {
  const res = await authFetch(`${BASE}/api/jobs/countries`)
  if (!res.ok) throw new Error(`Failed to fetch countries: HTTP ${res.status}`)
  return res.json() as Promise<CountriesResponse>
}

export async function fetchPlatforms(countries: string[]): Promise<PlatformsResponse> {
  const query = new URLSearchParams()
  countries.forEach(c => query.append('countries', c))
  const res = await authFetch(`${BASE}/api/jobs/platforms?${query.toString()}`)
  if (!res.ok) throw new Error(`Failed to fetch platforms: HTTP ${res.status}`)
  return res.json() as Promise<PlatformsResponse>
}

/** Open the API-key setup guide in a new tab. The endpoint needs the auth
 * header, so we fetch the HTML and open it as a blob URL rather than linking. */
export async function openSetupGuide(): Promise<void> {
  const res = await authFetch(`${BASE}/api/jobs/platforms/setup-guide`)
  if (!res.ok) throw new Error(`Failed to load setup guide: HTTP ${res.status}`)
  const html = await res.text()
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
  window.open(url, '_blank', 'noopener')
  // Revoke after a tick so the new tab has time to load it.
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export async function triggerRun(countries: string[], platforms: string[] = []): Promise<RunResponse> {
  const query = new URLSearchParams()
  countries.forEach(c => query.append('countries', c))
  platforms.forEach(p => query.append('platforms', p))
  const res = await authFetch(`${BASE}/api/jobs/run?${query.toString()}`)
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
    throw new Error(`Failed to trigger run: ${detail}`)
  }
  return res.json() as Promise<RunResponse>
}

export async function fetchReport(): Promise<RunReport> {
  const res = await authFetch(`${BASE}/api/jobs/report`)
  if (!res.ok) throw new Error(`Failed to fetch report: HTTP ${res.status}`)
  return res.json() as Promise<RunReport>
}

export async function updateMatchStatus(id: number, status: JobStatus): Promise<void> {
  const res = await authFetch(`${BASE}/api/jobs/matches/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
  if (!res.ok) throw new Error(`Failed to update status: HTTP ${res.status}`)
}

// ── AI job applications ──────────────────────────────────────────────────────

export async function startApplication(matchId: number): Promise<StartApplicationResponse> {
  const res = await authFetch(`${BASE}/api/jobs/matches/${matchId}/application`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to start application: HTTP ${res.status}`)
  return res.json() as Promise<StartApplicationResponse>
}

/** The application for a match, or null if none has been generated yet. */
export async function getApplicationByMatch(matchId: number): Promise<JobApplication | null> {
  const res = await authFetch(`${BASE}/api/jobs/matches/${matchId}/application`)
  if (!res.ok) throw new Error(`Failed to load application: HTTP ${res.status}`)
  // The endpoint returns 200 with { application: null } when none exists yet
  // (a 404 would be rewritten to the SPA index.html by CloudFront).
  const data = await res.json() as { application: JobApplication | null }
  return data.application ?? null
}

export async function getApplication(appId: number): Promise<JobApplication> {
  const res = await authFetch(`${BASE}/api/jobs/applications/${appId}`)
  if (!res.ok) throw new Error(`Failed to load application: HTTP ${res.status}`)
  return res.json() as Promise<JobApplication>
}

/** Fetch the merged application PDF as a Blob (needs the auth header). */
export async function getApplicationPdf(appId: number): Promise<Blob> {
  const res = await authFetch(`${BASE}/api/jobs/applications/${appId}/pdf`)
  if (!res.ok) throw new Error(`Failed to load PDF: HTTP ${res.status}`)
  return res.blob()
}

export async function submitApplicationFeedback(
  appId: number,
  feedback: string,
): Promise<StartApplicationResponse> {
  const res = await authFetch(`${BASE}/api/jobs/applications/${appId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ feedback }),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
    throw new Error(`Failed to submit feedback: ${detail}`)
  }
  return res.json() as Promise<StartApplicationResponse>
}

export async function applyApplication(appId: number): Promise<ApplyResponse> {
  const res = await authFetch(`${BASE}/api/jobs/applications/${appId}/apply`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to mark applied: HTTP ${res.status}`)
  return res.json() as Promise<ApplyResponse>
}
