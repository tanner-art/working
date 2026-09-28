import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authenticateInterpretCaller } from './interpretAuth'
import handler, { readAllowedUserIds, readMirrorConfig } from './factory-control'
import { factoryControlFixture } from '../src/factoryControl.fixture'

vi.mock('./interpretAuth', () => ({ authenticateInterpretCaller: vi.fn() }))
const authenticateMock = vi.mocked(authenticateInterpretCaller)
declare const process: { env: Record<string, string | undefined> }

const request = () => new Request('https://threadline.test/api/factory-control', { method: 'GET', headers: { authorization: 'Bearer user-jwt', 'sec-fetch-site': 'same-origin' } })

async function gzip(body: string): Promise<Uint8Array> {
  const stream = new Blob([body]).stream().pipeThrough(new CompressionStream('gzip'))
  return new Uint8Array(await new Response(stream).arrayBuffer())
}

async function signature(body: Uint8Array, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const buffer = new ArrayBuffer(body.byteLength)
  new Uint8Array(buffer).set(body)
  const bytes = new Uint8Array(await crypto.subtle.sign('HMAC', key, buffer))
  return `sha256=${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`
}

async function storedRow(body: string) {
  const bytes = await gzip(body)
  return { body: btoa(String.fromCharCode(...bytes)), signature: await signature(bytes, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!) }
}

async function decoded(result: Response) {
  if (result.headers.get('content-encoding') !== 'gzip') return result.json()
  const uncompressed = result.body!.pipeThrough(new DecompressionStream('gzip'))
  return JSON.parse(await new Response(uncompressed).text())
}

beforeEach(() => {
  authenticateMock.mockReset()
  authenticateMock.mockResolvedValue({ ok: true, userId: 'owner-1' })
  process.env.SUPABASE_URL = 'https://db.threadline.test'
  process.env.FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY = 'service-key'
  process.env.FACTORY_CONTROL_PUBLISH_TOKEN = 'publisher-token'
  process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET = 'a-32-character-minimum-signing-secret'
  process.env.FACTORY_CONTROL_ALLOWED_USER_IDS = 'owner-1'
})

afterEach(() => {
  delete process.env.SUPABASE_URL
  delete process.env.FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY
  delete process.env.FACTORY_CONTROL_PUBLISH_TOKEN
  delete process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET
  delete process.env.FACTORY_CONTROL_ALLOWED_USER_IDS
  vi.unstubAllGlobals()
})

describe('Factory Control Center API', () => {
  it('authenticates before reading the hosted snapshot', async () => {
    authenticateMock.mockResolvedValue({ ok: false, status: 401, error: 'unauthorized', message: 'Sign in.' })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect((await handler(request())).status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(authenticateMock).toHaveBeenCalledWith(expect.any(Request), expect.any(Function), {
      allowSameOriginSafeRequestWithoutOrigin: true,
    })
  })

  it('fails closed when the mirror configuration is incomplete', async () => {
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
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([await storedRow(body)]), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await handler(request())
    expect(result.status).toBe(200)
    expect(result.headers.get('cache-control')).toContain('no-store')
    const snapshot = await decoded(result)
    expect(snapshot).toMatchObject({ registryRevision: 'registry-1842', verification: { status: 'verified', algorithm: 'HMAC-SHA-256' } })
    expect(snapshot).not.toHaveProperty('privateTransportField')
    expect(fetchMock).toHaveBeenCalledWith('https://db.threadline.test/rest/v1/factory_dashboard_snapshot?id=eq.current&select=body,signature', expect.objectContaining({ headers: expect.objectContaining({ authorization: 'Bearer service-key' }), redirect: 'error' }))
  })

  it('rejects a bad signature or invalid contract', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([{ body: '{}', signature: `sha256=${'0'.repeat(64)}` }]), { status: 200 })))
    const result = await handler(request())
    expect(result.status).toBe(503)
    expect(await result.json()).toMatchObject({ error: 'projection_invalid' })

    const body = '{}'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([await storedRow(body)]), { status: 200 })))
    const invalidContract = await handler(request())
    expect(await invalidContract.json()).toMatchObject({ error: 'projection_invalid' })
  })

  it('accepts only a signed, authenticated publisher and stores a single snapshot', async () => {
    const { verification: _verification, ...projection } = factoryControlFixture
    const body = JSON.stringify(projection)
    const bytes = await gzip(body)
    const signed = await signature(bytes, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!)
    const fetchMock = vi.fn(async () => new Response(null, { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
    const publish = (token: string, signatureValue: string) => handler(new Request('https://threadline.test/api/factory-control', {
      method: 'POST', headers: { authorization: `Bearer ${token}`, 'content-type': 'application/gzip', 'x-threadline-factory-signature': signatureValue }, body: new Uint8Array(bytes).buffer,
    }))
    expect((await publish('wrong', signed)).status).toBe(401)
    expect((await publish('publisher-token', `sha256=${'0'.repeat(64)}`)).status).toBe(400)
    expect(fetchMock).not.toHaveBeenCalled()
    expect((await publish('publisher-token', signed)).status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith('https://db.threadline.test/rest/v1/factory_dashboard_snapshot?on_conflict=id', expect.objectContaining({ method: 'POST' }))
    expect(authenticateMock).not.toHaveBeenCalled()
  })

  it('rejects a signed but unreadable compressed publication', async () => {
    const bad = new TextEncoder().encode('not gzip')
    const signed = await signature(bad, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const result = await handler(new Request('https://threadline.test/api/factory-control', {
      method: 'POST', headers: { authorization: 'Bearer publisher-token', 'content-type': 'application/gzip', 'x-threadline-factory-signature': signed }, body: bad.buffer,
    }))
    expect(result.status).toBe(400)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects other methods and malformed backend URLs', async () => {
    expect((await handler(new Request('https://threadline.test/api/factory-control', { method: 'PUT' }))).status).toBe(405)
    expect(readMirrorConfig({ SUPABASE_URL: 'http://db.test', FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY: 'x', FACTORY_CONTROL_PUBLISH_TOKEN: 'x', FACTORY_CONTROL_PROJECTION_SIGNING_SECRET: 'x'.repeat(32) })).toBeUndefined()
  })
})
