import { OAUTH_BASE, REDIRECT_URI, API_BASE } from '../config/env'
import { generateVerifier, generateChallenge, generateState } from '../utils/pkce'
import type { User } from '../types/user'

export class AuthError extends Error {
  constructor(msg: string) {
    super(msg)
    this.name = 'AuthError'
  }
}

// clientId is not a secret — persist across browser sessions so we reuse the
// same registered OAuth client instead of creating a new one every session.
const LS = {
  clientId: 'pi_client_id',
} as const

// Tokens are sensitive — scope to the browser session only.
const SS = {
  access:    'pi_access_token',
  refresh:   'pi_refresh_token',
  expiresAt: 'pi_token_expires_at',
} as const

const PKCE = {
  verifier:  'pi_pkce_verifier',
  state:     'pi_pkce_state',
  postRoute: 'pi_post_login_route',
} as const

function clearTokens(): void {
  sessionStorage.removeItem(SS.access)
  sessionStorage.removeItem(SS.refresh)
  sessionStorage.removeItem(SS.expiresAt)
}

export function isAuthenticated(): boolean {
  const token = sessionStorage.getItem(SS.access)
  const exp   = Number(sessionStorage.getItem(SS.expiresAt) ?? 0)
  return !!token && exp > Date.now() + 60_000
}

export function hasRefreshToken(): boolean {
  return !!sessionStorage.getItem(SS.refresh)
}

export function getClientId(): string | null {
  return localStorage.getItem(LS.clientId)
}

export async function refreshTokens(): Promise<void> {
  const refreshToken = sessionStorage.getItem(SS.refresh)
  const clientId     = localStorage.getItem(LS.clientId)

  if (!refreshToken || !clientId) {
    clearTokens()
    throw new AuthError('Session expired')
  }

  const res = await fetch(`${OAUTH_BASE}/api/oauth/token`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body:    new URLSearchParams({
      grant_type:    'refresh_token',
      refresh_token: refreshToken,
      client_id:     clientId,
    }),
  })

  if (res.status === 400 || res.status === 401) {
    clearTokens()
    throw new AuthError('Session expired')
  }
  if (!res.ok) throw new AuthError(`Token refresh failed: ${res.statusText}`)

  const data = await res.json() as {
    access_token:  string
    refresh_token: string
    expires_in:    number
  }

  sessionStorage.setItem(SS.access,    data.access_token)
  sessionStorage.setItem(SS.refresh,   data.refresh_token)
  sessionStorage.setItem(SS.expiresAt, String(Date.now() + data.expires_in * 1000))
}

export async function requireAuth(): Promise<string> {
  if (isAuthenticated()) return sessionStorage.getItem(SS.access)!
  if (hasRefreshToken()) {
    await refreshTokens()
    return sessionStorage.getItem(SS.access)!
  }
  throw new AuthError('Not authenticated')
}

export async function registerClient(): Promise<string> {
  const stored = localStorage.getItem(LS.clientId)
  if (stored) return stored

  const res = await fetch(`${OAUTH_BASE}/api/oauth/register`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({
      client_name:                'private-internet-dashboard',
      redirect_uris:              [REDIRECT_URI],
      token_endpoint_auth_method: 'none',
      grant_types:                ['authorization_code', 'refresh_token'],
      response_types:             ['code'],
    }),
  })

  if (!res.ok) throw new AuthError(`Client registration failed: ${res.status}`)

  const data = await res.json() as { client_id: string }
  localStorage.setItem(LS.clientId, data.client_id)
  return data.client_id
}

export async function initiateLogin(intendedRoute = '/'): Promise<void> {
  const clientId  = await registerClient()
  const verifier  = generateVerifier()
  const state     = generateState()
  const challenge = await generateChallenge(verifier)

  sessionStorage.setItem(PKCE.verifier,  verifier)
  sessionStorage.setItem(PKCE.state,     state)
  sessionStorage.setItem(PKCE.postRoute, intendedRoute)

  const params = new URLSearchParams({
    response_type:         'code',
    client_id:             clientId,
    redirect_uri:          REDIRECT_URI,
    code_challenge:        challenge,
    code_challenge_method: 'S256',
    state,
  })

  window.location.href = `${OAUTH_BASE}/api/oauth/authorize?${params}`
}

export function logout(): void {
  clearTokens()
  // Dynamic import avoids circular dep: router imports useAuth, useAuth imports router.
  import('../router/index').then(m => m.default.push('/login'))
}

// ---------------------------------------------------------------------------
// Password-based auth (Section 2)
// ---------------------------------------------------------------------------

/** Decode a JWT's payload segment without verifying the signature. */
function decodeJwtExp(token: string): number | null {
  try {
    const segment = token.split('.')[1]
    if (!segment) return null
    const json = atob(segment.replace(/-/g, '+').replace(/_/g, '/'))
    const payload = JSON.parse(json) as { exp?: number }
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}

/** Store a JWT returned from the password-auth endpoints. */
function storeJwt(token: string): void {
  const expMs = decodeJwtExp(token) ?? Date.now() + 7 * 24 * 60 * 60 * 1000
  sessionStorage.setItem(SS.access,    token)
  sessionStorage.setItem(SS.expiresAt, String(expMs))
  // No refresh token on this auth path.
  sessionStorage.removeItem(SS.refresh)
}

export interface RegisterParams {
  email: string
  display_name: string
  password: string
  referral_source?: string
  plan?: string
}

export interface LoginParams {
  email: string
  password: string
}

export interface PasswordAuthResult {
  token?: string
  user?: User
  email_verification_required?: boolean
  message?: string
}

/** Extended error that carries the HTTP status so callers can branch on 403/404/401. */
export class AuthHttpError extends AuthError {
  status: number
  constructor(msg: string, status: number) {
    super(msg)
    this.name   = 'AuthHttpError'
    this.status = status
  }
}

export async function registerWithPassword(params: RegisterParams): Promise<PasswordAuthResult> {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(params),
  })

  const data = await res.json() as PasswordAuthResult & { error?: string }

  if (!res.ok) {
    throw new AuthHttpError(data.error ?? `Registration failed (${res.status})`, res.status)
  }

  // Only store a token when one is present (email verification may withhold it).
  if (data.token) {
    storeJwt(data.token)
  }

  return data
}

export async function loginWithPassword(params: LoginParams): Promise<PasswordAuthResult> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(params),
  })

  const data = await res.json() as PasswordAuthResult & { error?: string }

  if (!res.ok) {
    throw new AuthHttpError(data.error ?? `Login failed (${res.status})`, res.status)
  }

  if (data.token) {
    storeJwt(data.token)
  }

  return data
}

export async function resendVerification(email: string): Promise<void> {
  await fetch(`${API_BASE}/api/auth/resend-verification`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ email }),
  })
  // Always resolves — backend returns 200 regardless of whether email exists.
}

export async function forgotPassword(email: string): Promise<void> {
  await fetch(`${API_BASE}/api/auth/forgot-password`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ email }),
  })
  // Always resolves with a 200 to avoid account enumeration.
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ token, new_password: newPassword }),
  })

  if (!res.ok) {
    const data = await res.json() as { error?: string }
    throw new AuthError(data.error ?? `Password reset failed (${res.status})`)
  }
}
