import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authenticateInterpretCaller } from './interpretAuth'
import handler, { readAllowedUserIds, readMirrorConfig } from './factory-control'
import { factoryControlFixture } from '../src/factoryControl.fixture'

vi.mock('./interpretAuth', () => ({ authenticateInterpretCaller: vi.fn() }))
const authenticateMock = vi.mocked(authenticateInterpretCaller)
declare const process: { env: Record<string, string | undefined> }
const request = () => new Request('https://threadline.test/api/factory-control', { method: 'GET', headers: { authorization: 'Bearer user-jwt', 'sec-fetch-site': 'same-origin' } })

async function gzip(body: string): Promise<Uint8Array> { return new Uint8Array(await new Response(new Blob([body]).stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer()) }
async function signature(body: Uint8Array, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const buffer = new ArrayBuffer(body.byteLength); new Uint8Array(buffer).set(body)
  const bytes = new Uint8Array(await crypto.subtle.sign('HMAC', key, buffer))
  return `sha256=${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`
}
function encoded(bytes: Uint8Array): string {
  let raw = ''
  for (let index = 0; index < bytes.length; index += 8192) raw += String.fromCharCode(...bytes.subarray(index, index + 8192))
  return btoa(raw)
}
function requestBody(bytes: Uint8Array): ArrayBuffer { const body = new ArrayBuffer(bytes.byteLength); new Uint8Array(body).set(bytes); return body }
async function storedRow(body: string) { const bytes = await gzip(body); return { body: encoded(bytes), signature: await signature(bytes, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!) } }
async function decoded(result: Response) { return JSON.parse(await new Response(result.body!.pipeThrough(new DecompressionStream('gzip'))).text()) }

beforeEach(() => {
  authenticateMock.mockReset(); authenticateMock.mockResolvedValue({ ok: true, userId: 'owner-1' })
  process.env.SUPABASE_URL = 'https://db.threadline.test'; process.env.FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY = 'service-key'; process.env.FACTORY_CONTROL_PUBLISH_TOKEN = 'publisher-token'; process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET = 'a-32-character-minimum-signing-secret'; process.env.FACTORY_CONTROL_ALLOWED_USER_IDS = 'owner-1'
})
afterEach(() => { delete process.env.SUPABASE_URL; delete process.env.FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY; delete process.env.FACTORY_CONTROL_PUBLISH_TOKEN; delete process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET; delete process.env.FACTORY_CONTROL_ALLOWED_USER_IDS; vi.unstubAllGlobals() })

describe('Factory Control Center API', () => {
  it('authenticates before reading the hosted snapshot', async () => {
    authenticateMock.mockResolvedValue({ ok: false, status: 401, error: 'unauthorized', message: 'Sign in.' }); const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock)
    expect((await handler(request())).status).toBe(401); expect(fetchMock).not.toHaveBeenCalled()
  })
  it('fails closed when mirror configuration or owner authorization is absent', async () => {
    delete process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET; expect((await handler(request())).status).toBe(503)
    process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET = 'a-32-character-minimum-signing-secret'; delete process.env.FACTORY_CONTROL_ALLOWED_USER_IDS; expect((await handler(request())).status).toBe(503)
    process.env.FACTORY_CONTROL_ALLOWED_USER_IDS = 'another-owner'; expect((await handler(request())).status).toBe(403); expect(readAllowedUserIds(' owner-1, owner-2 ')?.has('owner-2')).toBe(true)
  })
  it('returns only a verified and runtime-sanitized Registry projection', async () => {
    const { verification: _verification, ...projection } = factoryControlFixture; const body = JSON.stringify({ ...projection, privateTransportField: 'strip me' })
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([await storedRow(body)]), { status: 200 })); vi.stubGlobal('fetch', fetchMock)
    const result = await handler(request()); expect(result.status).toBe(200); expect(result.headers.get('cache-control')).toContain('no-store')
    const snapshot = await decoded(result); expect(snapshot).toMatchObject({ registryRevision: 'registry-1842', verification: { status: 'verified', algorithm: 'HMAC-SHA-256' } }); expect(snapshot).not.toHaveProperty('privateTransportField')
  })
  it('accepts the exact maximum base64 representation but rejects one byte more', async () => {
    const maximum = new Uint8Array(1_048_576); const accepted = encoded(maximum); expect(accepted).toHaveLength(1_398_104)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([{ body: accepted, signature: await signature(maximum, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!) }]), { status: 200 })))
    expect((await handler(request())).status).toBe(503) // Signature passes; non-gzip data still fails closed.
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([{ body: `${accepted}A`, signature: await signature(maximum, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!) }]), { status: 200 })))
    expect(await (await handler(request())).json()).toMatchObject({ error: 'projection_invalid' })
  })
  it('accepts only a signed publisher and stores one snapshot', async () => {
    const { verification: _verification, ...projection } = factoryControlFixture; const bytes = await gzip(JSON.stringify(projection)); const signed = await signature(bytes, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!); const fetchMock = vi.fn(async () => new Response(null, { status: 201 })); vi.stubGlobal('fetch', fetchMock)
    const publish = (token: string, value: string) => handler(new Request('https://threadline.test/api/factory-control', { method: 'POST', headers: { authorization: `Bearer ${token}`, 'content-type': 'application/gzip', 'x-threadline-factory-signature': value }, body: requestBody(bytes) }))
    expect((await publish('wrong', signed)).status).toBe(401); expect((await publish('publisher-token', `sha256=${'0'.repeat(64)}`)).status).toBe(400); expect((await publish('publisher-token', signed)).status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith('https://db.threadline.test/rest/v1/factory_dashboard_snapshot?on_conflict=id', expect.objectContaining({ method: 'POST' })); expect(authenticateMock).not.toHaveBeenCalled()
  })
  it('rejects malformed, oversized, or unreadable compressed publications', async () => {
    const bad = new TextEncoder().encode('not gzip'); const signed = await signature(bad, process.env.FACTORY_CONTROL_PROJECTION_SIGNING_SECRET!); const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock)
    const publish = (body: Uint8Array) => handler(new Request('https://threadline.test/api/factory-control', { method: 'POST', headers: { authorization: 'Bearer publisher-token', 'content-type': 'application/gzip', 'x-threadline-factory-signature': signed }, body: requestBody(body) }))
    expect((await publish(bad)).status).toBe(400); expect((await publish(new Uint8Array(1_048_577))).status).toBe(413); expect(fetchMock).not.toHaveBeenCalled()
  })
  it('rejects other methods and malformed backend URLs', async () => {
    expect((await handler(new Request('https://threadline.test/api/factory-control', { method: 'PUT' }))).status).toBe(405)
    expect(readMirrorConfig({ SUPABASE_URL: 'http://db.test', FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY: 'x', FACTORY_CONTROL_PUBLISH_TOKEN: 'x', FACTORY_CONTROL_PROJECTION_SIGNING_SECRET: 'x'.repeat(32) })).toBeUndefined()
  })
})
