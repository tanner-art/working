declare const process: { env: Record<string, string | undefined> }

const MAX_BEARER_LENGTH = 8_192

export type CallerAuthentication =
  | { ok: true; userId: string }
  | { ok: false; status: 401 | 403 | 503; error: 'unauthorized' | 'origin_not_allowed' | 'auth_unavailable'; message: string }

function allowedOrigins(request: Request): Set<string> {
  const allowed = new Set([new URL(request.url).origin])
  for (const value of (process.env.AI_ALLOWED_ORIGINS ?? '').split(',')) {
    const origin = value.trim()
    if (!origin) continue
    try { allowed.add(new URL(origin).origin) } catch { /* ignore malformed deployment config */ }
  }
  return allowed
}

function authorizationToken(request: Request): string | undefined {
  const header = request.headers.get('authorization')
  if (!header?.startsWith('Bearer ')) return undefined
  const token = header.slice('Bearer '.length).trim()
  return token && token.length <= MAX_BEARER_LENGTH ? token : undefined
}

function supabaseConfig(): { url: string; key: string } | undefined {
  const rawUrl = process.env.SUPABASE_URL ?? process.env.VITE_SUPABASE_URL
  const key = process.env.SUPABASE_PUBLISHABLE_KEY ?? process.env.VITE_SUPABASE_ANON_KEY
  if (!rawUrl?.trim() || !key?.trim()) return undefined
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) return undefined
    return { url: url.origin, key: key.trim() }
  } catch { return undefined }
}

/**
 * Verifies a browser request against the existing Threadline Supabase project.
 * Calling Supabase Auth's user endpoint also supports projects that still use legacy
 * symmetric JWT signing, unlike local JWKS-only verification.
 */
export async function authenticateInterpretCaller(
  request: Request,
  fetchImpl: typeof fetch = fetch,
): Promise<CallerAuthentication> {
  const origin = request.headers.get('origin')
  const fetchSite = request.headers.get('sec-fetch-site')
  if (!origin || !allowedOrigins(request).has(origin) || (fetchSite && fetchSite !== 'same-origin')) {
    return { ok: false, status: 403, error: 'origin_not_allowed', message: 'The request origin is not allowed.' }
  }

  const token = authorizationToken(request)
  if (!token) return { ok: false, status: 401, error: 'unauthorized', message: 'Sign in before using AI interpretation.' }

  const config = supabaseConfig()
  if (!config) {
    return { ok: false, status: 503, error: 'auth_unavailable', message: 'Account verification is not configured.' }
  }

  try {
    const response = await fetchImpl(`${config.url}/auth/v1/user`, {
      method: 'GET',
      headers: { apikey: config.key, authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    if (!response.ok) {
      return { ok: false, status: 401, error: 'unauthorized', message: 'The account session is invalid or expired.' }
    }
    const user = await response.json() as { id?: unknown }
    if (typeof user.id !== 'string' || !user.id.trim()) {
      return { ok: false, status: 503, error: 'auth_unavailable', message: 'Account verification returned an invalid identity.' }
    }
    return { ok: true, userId: user.id }
  } catch {
    return { ok: false, status: 503, error: 'auth_unavailable', message: 'Account verification is temporarily unavailable.' }
  }
}
