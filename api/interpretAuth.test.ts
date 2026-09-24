import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authenticateInterpretCaller } from './interpretAuth'

declare const process: { env: Record<string, string | undefined> }

function request(headers: Record<string, string> = {}) {
  return new Request('https://threadline.test/api/interpret', {
    method: 'POST',
    headers: {
      origin: 'https://threadline.test',
      authorization: 'Bearer user-jwt',
      ...headers,
    },
  })
}

beforeEach(() => {
  process.env.VITE_SUPABASE_URL = 'https://threadline.supabase.co'
  process.env.VITE_SUPABASE_ANON_KEY = 'publishable-key'
})

afterEach(() => {
  delete process.env.VITE_SUPABASE_URL
  delete process.env.VITE_SUPABASE_ANON_KEY
  delete process.env.SUPABASE_URL
  delete process.env.SUPABASE_PUBLISHABLE_KEY
  delete process.env.AI_ALLOWED_ORIGINS
  vi.restoreAllMocks()
})

describe('authenticateInterpretCaller', () => {
  it('verifies the bearer token with Supabase and returns only the account id', async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ id: 'account-1', email: 'private@example.test' }), { status: 200 }))
    await expect(authenticateInterpretCaller(request(), fetchImpl)).resolves.toEqual({ ok: true, userId: 'account-1' })
    expect(fetchImpl).toHaveBeenCalledOnce()
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('https://threadline.supabase.co/auth/v1/user')
    expect(init?.headers).toEqual({ apikey: 'publishable-key', authorization: 'Bearer user-jwt' })
    expect(init?.cache).toBe('no-store')
  })

  it.each([
    [{ origin: '' }, 'origin_not_allowed'],
    [{ origin: 'https://attacker.test' }, 'origin_not_allowed'],
    [{ 'sec-fetch-site': 'cross-site' }, 'origin_not_allowed'],
    [{ authorization: '' }, 'unauthorized'],
    [{ authorization: 'Basic credentials' }, 'unauthorized'],
  ])('rejects an invalid browser boundary before account verification: %j', async (headers, error) => {
    const fetchImpl = vi.fn()
    const result = await authenticateInterpretCaller(request(headers), fetchImpl)
    expect(result).toMatchObject({ ok: false, error })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('accepts a deliberately configured additional origin', async () => {
    process.env.AI_ALLOWED_ORIGINS = 'https://preview.threadline.test'
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ id: 'account-1' }), { status: 200 }))
    const result = await authenticateInterpretCaller(request({ origin: 'https://preview.threadline.test' }), fetchImpl)
    expect(result).toEqual({ ok: true, userId: 'account-1' })
  })

  it('accepts an Origin-less safe browser request only with same-origin fetch metadata', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ id: 'account-1' }), { status: 200 }))
    const browserRequest = new Request('https://threadline.test/api/factory-control', {
      method: 'GET',
      headers: { authorization: 'Bearer user-jwt', 'sec-fetch-site': 'same-origin' },
    })
    await expect(authenticateInterpretCaller(browserRequest, fetchImpl, {
      allowSameOriginSafeRequestWithoutOrigin: true,
    })).resolves.toEqual({ ok: true, userId: 'account-1' })

    const rejectedHeaders: Array<Record<string, string>> = [
      { authorization: 'Bearer user-jwt' },
      { authorization: 'Bearer user-jwt', 'sec-fetch-site': 'cross-site' },
    ]
    for (const headers of rejectedHeaders) {
      const rejected = new Request('https://threadline.test/api/factory-control', { method: 'GET', headers })
      await expect(authenticateInterpretCaller(rejected, fetchImpl, {
        allowSameOriginSafeRequestWithoutOrigin: true,
      })).resolves.toMatchObject({ ok: false, error: 'origin_not_allowed' })
    }
    expect(fetchImpl).toHaveBeenCalledOnce()
  })

  it('returns unauthorized for an expired or invalid Supabase session', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ message: 'invalid' }), { status: 401 }))
    await expect(authenticateInterpretCaller(request(), fetchImpl)).resolves.toMatchObject({
      ok: false, status: 401, error: 'unauthorized',
    })
  })

  it('fails closed when Supabase account verification is not configured', async () => {
    delete process.env.VITE_SUPABASE_URL
    const fetchImpl = vi.fn()
    await expect(authenticateInterpretCaller(request(), fetchImpl)).resolves.toMatchObject({
      ok: false, status: 503, error: 'auth_unavailable',
    })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('fails closed on a network error or invalid identity response', async () => {
    const offline = vi.fn(async () => { throw new Error('offline') })
    await expect(authenticateInterpretCaller(request(), offline)).resolves.toMatchObject({
      ok: false, status: 503, error: 'auth_unavailable',
    })
    const invalid = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }))
    await expect(authenticateInterpretCaller(request(), invalid)).resolves.toMatchObject({
      ok: false, status: 503, error: 'auth_unavailable',
    })
  })
})
