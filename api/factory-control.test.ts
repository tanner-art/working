import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authenticateInterpretCaller } from './interpretAuth'
import handler, { readAllowedUserIds, readProjectionTransport } from './factory-control'
import { factoryControlFixture } from '../src/factoryControl.fixture'

vi.mock('./interpretAuth', () => ({ authenticateInterpretCaller: vi.fn() }))
const authenticateMock = vi.mocked(authenticateInterpretCaller)
declare const process: { env: Record<string, string | undefined> }

const request = () => new Request('https://threadline.test/api/factory-control', { method: 'GET', headers: { authorization: 'Bearer user-jwt', 'sec-fetch-site': 'same-origin' } })

async function signature(body: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const bytes = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body)))
  return `sha256=${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`
}

beforeEach(() => {
  authenticateMock.mockReset()
  authenticateMock.mockResolvedValue({ ok: true, userId: 'owner-1' })
  process.env.FACTORY_CONTROL_PROJECTION_URL = 'https://registry.threadline.test/control-center.json'
  process.env.FACTORY_CONTROL_PROJECTION_TOKEN = 'transport-token'
  process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET = 'a-32-character-minimum-signing-secret'
  process.env.FACTORY_CONTROL_ALLOWED_USER_IDS = 'owner-1'
})

afterEach(() => {
  delete process.env.FACTORY_CONTROL_PROJECTION_URL
  delete process.env.FACTORY_CONTROL_PROJECTION_TOKEN
  delete process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET
  delete process.env.FACTORY_CONTROL_ALLOWED_USER_IDS
  vi.unstubAllGlobals()
})

describe('Factory Control Center API', () => {
  it('authenticates before reading the projection transport', async () => {
    authenticateMock.mockResolvedValue({ ok: false, status: 401, error: 'unauthorized', message: 'Sign in.' })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect((await handler(request())).status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(authenticateMock).toHaveBeenCalledWith(expect.any(Request), expect.any(Function), {
      allowSameOriginSafeRequestWithoutOrigin: true,
    })
  })

  it('fails closed when the projection transport is incomplete', async () => {
    delete process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const result = await handler(request())
    expect(result.status).toBe(503)
    expect(await result.json()).toMatchObject({ error: 'projection_unconfigured' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fails closed without an owner allowlist and rejects an unlisted account', async () => {
    delete process.env.FACTORY_CONTROL_ALLOWED_USER_IDS
    expect((await handler(request())).status).toBe(503)
    process.env.FACTORY_CONTROL_ALLOWED_USER_IDS = 'another-owner'
    expect((await handler(request())).status).toBe(403)
    expect(readAllowedUserIds(' owner-1, owner-2 ')?.has('owner-2')).toBe(true)
  })

  it('returns only a verified and runtime-sanitized Registry projection', async () => {
    const { verification: _verification, ...projection } = factoryControlFixture
    const body = JSON.stringify({ ...projection, privateTransportField: 'strip me' })
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => new Response(body, { status: 200, headers: { 'content-type': 'application/json', 'x-threadline-factory-signature': await signature(body, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!) } }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await handler(request())
    expect(result.status).toBe(200)
    expect(result.headers.get('cache-control')).toContain('no-store')
    const snapshot = await result.json()
    expect(snapshot).toMatchObject({ registryRevision: 'registry-1842', verification: { status: 'verified', algorithm: 'HMAC-SHA-256' } })
    expect(snapshot).not.toHaveProperty('privateTransportField')
    expect(fetchMock).toHaveBeenCalledWith('https://registry.threadline.test/control-center.json', expect.objectContaining({ headers: expect.objectContaining({ authorization: 'Bearer transport-token' }), redirect: 'error' }))
  })

  it('rejects a bad signature or invalid contract', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json', 'x-threadline-factory-signature': `sha256=${'0'.repeat(64)}` } })))
    const result = await handler(request())
    expect(result.status).toBe(503)
    expect(await result.json()).toMatchObject({ error: 'projection_invalid' })

    const body = '{}'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200, headers: { 'content-type': 'application/json', 'x-threadline-factory-signature': await signature(body, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!) } })))
    const invalidContract = await handler(request())
    expect(await invalidContract.json()).toMatchObject({ error: 'projection_invalid' })
  })

  it('rejects non-GET requests and malformed transport URLs', async () => {
    expect((await handler(new Request('https://threadline.test/api/factory-control', { method: 'POST' }))).status).toBe(405)
    expect(readProjectionTransport({ FACTORY_CONTROL_PROJECTION_URL: 'http://registry.test', FACTORY_CONTROL_PROJECTION_TOKEN: 'x', FACTORY_CONTROL_PROJECTION_SIGNING_SECRET: 'x'.repeat(32) })).toBeUndefined()
  })
})
