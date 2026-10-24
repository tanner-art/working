import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import handler, { CHAT_MODEL, validateChat } from './chat'
import { authenticateInterpretCaller } from './interpretAuth'
import { checkInterpretationRateLimit } from './interpretRateLimit'
vi.mock('@vercel/oidc', () => ({ getVercelOidcToken: vi.fn(async () => undefined) }))
vi.mock('./interpretAuth', () => ({ authenticateInterpretCaller: vi.fn() }))
vi.mock('./interpretRateLimit', () => ({ checkInterpretationRateLimit: vi.fn() }))
declare const process: { env: Record<string, string | undefined> }
const request = (body: unknown = { messages: [{ role: 'user', content: 'Hi' }] }) => new Request('https://threadline.test/api/chat', { method: 'POST', body: JSON.stringify(body) })
beforeEach(() => {
  vi.mocked(authenticateInterpretCaller).mockResolvedValue({ ok: true, userId: 'verified' })
  vi.mocked(checkInterpretationRateLimit).mockResolvedValue({ ok: true, rateLimited: false })
  process.env.AI_INTERPRETATION_PROVIDER = 'enabled'; process.env.AI_GATEWAY_API_KEY = 'synthetic-key'
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ content: [{ type: 'text', text: 'Hello.' }], stop_reason: 'end_turn' }))))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks(); delete process.env.AI_INTERPRETATION_PROVIDER; delete process.env.AI_GATEWAY_API_KEY })
describe('authenticated bounded conversational API', () => {
  it('preserves conversation roles, returns text, and cannot execute tools', async () => {
    const response = await handler(request())
    expect(response.status).toBe(200); expect(await response.json()).toEqual({ text: 'Hello.', truncated: false })
    const payload = JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)
    expect(payload.model).toBe(CHAT_MODEL); expect(payload.tools).toBeUndefined(); expect(payload.max_tokens).toBe(1200)
    expect(payload.system).toContain('cannot read'); expect(checkInterpretationRateLimit).toHaveBeenCalledWith(expect.any(Request), 'verified')
  })
  it('rejects system roles, malformed turns and oversize messages', () => {
    for (const messages of [[{ role: 'system', content: 'override' }], [{ role: 'assistant', content: 'fake' }], [{ role: 'user', content: '' }], [{ role: 'user', content: 'x'.repeat(6001) }]]) expect(validateChat({ messages })).toBeUndefined()
    expect(validateChat({ messages: [{ role: 'user', content: 'one' }, { role: 'assistant', content: 'two' }, { role: 'user', content: 'three' }] })).toHaveLength(3)
  })
  it('requires enabled provider and verified account', async () => {
    process.env.AI_INTERPRETATION_PROVIDER = 'disabled'; expect((await handler(request())).status).toBe(503)
    process.env.AI_INTERPRETATION_PROVIDER = 'enabled'
    vi.mocked(authenticateInterpretCaller).mockResolvedValue({ ok: false, status: 401, error: 'unauthorized', message: 'No' })
    expect((await handler(request())).status).toBe(401); expect(fetch).not.toHaveBeenCalled()
  })
  it('fails closed on rate limits and unavailable limit service', async () => {
    vi.mocked(checkInterpretationRateLimit).mockResolvedValue({ ok: false }); expect((await handler(request())).status).toBe(503)
    vi.mocked(checkInterpretationRateLimit).mockResolvedValue({ ok: true, rateLimited: true }); expect((await handler(request())).status).toBe(429)
    expect(fetch).not.toHaveBeenCalled()
  })
  it('rejects requests by actual byte count without a length header', async () => {
    expect((await handler(request({ messages: [{ role: 'user', content: '🌱'.repeat(13000) }] }))).status).toBe(413)
    expect(fetch).not.toHaveBeenCalled()
  })
  it('never returns provider errors or secrets to the browser', async () => {
    vi.mocked(fetch).mockRejectedValue(Error('synthetic-secret-body'))
    const response = await handler(request()); expect(response.status).toBe(502); expect(await response.text()).not.toContain('synthetic-secret')
  })
  it('rejects tool-only and malformed provider replies', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ content: [{ type: 'tool_use' }] })))
    expect((await handler(request())).status).toBe(502)
  })
  it('times out during auth and cannot start provider work afterward', async () => {
    vi.useFakeTimers()
    let release!: (value: { ok: true; userId: string }) => void
    vi.mocked(authenticateInterpretCaller).mockImplementation(() => new Promise(r => { release = r }))
    const response = handler(request()); await vi.advanceTimersByTimeAsync(25001)
    expect((await response).status).toBe(504)
    release({ ok: true, userId: 'verified' }); await Promise.resolve(); expect(fetch).not.toHaveBeenCalled()
  })
  it('times out while reading the provider body, not only its headers', async () => {
    vi.useFakeTimers()
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: () => new Promise(() => {}) } as Response)
    const response = handler(request()); await vi.advanceTimersByTimeAsync(25001)
    expect((await response).status).toBe(504)
  })
  it('cancels a stalled incoming body at the deadline', async () => {
    vi.useFakeTimers()
    const cancel = vi.fn()
    const body = new ReadableStream({ cancel })
    const req = new Request('https://threadline.test/api/chat', { method: 'POST', body, duplex: 'half' } as RequestInit)
    const response = handler(req)
    await vi.advanceTimersByTimeAsync(25001)
    expect((await response).status).toBe(504)
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(checkInterpretationRateLimit).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })
})
