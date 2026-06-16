// API calls are always relative — proxy in dev, same-origin in prod
export const OAUTH_BASE = ''

// Only REDIRECT_URI needs to be absolute (backend redirects the browser to it)
export const REDIRECT_URI =
  import.meta.env.VITE_REDIRECT_URI ??
  `${window.location.origin}/oauth/callback`

// Backend API base. The dashboard is always served same-origin with the API
// (CloudFront routes /api/* on the same host to the backend; dev uses the Vite
// proxy), so this is empty — identical to OAUTH_BASE above.
// NOTE: we deliberately no longer read VITE_API_BASE_URL. A stale build secret
// still pointing at the retired domain silently baked the dead host into every
// /api/auth/* call, breaking login / password reset with a NetworkError.
export const API_BASE = ''
