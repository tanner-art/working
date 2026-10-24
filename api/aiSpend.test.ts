import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BUDGET_MODEL, budgetedMessage, certifiedPrice, usageCharge } from './aiSpend'
declare const process: { env: Record<string, string | undefined> }
const pricing = { prompt: '.000001', completion: '.000005', request: '0', image: '0', image_output: '0', internal_reasoning: '0', input_cache_read: '.0000001', input_cache_write: '.00000125', web_search: '.01', discount: 0 }
const catalog = () => ({ data: { id: BUDGET_MODEL, endpoints: [{ provider_name: 'anthropic', context_length: 200000, pricing: { ...pricing } }] } })
const payload = { model: BUDGET_MODEL, max_tokens: 1200, system: 'Synthetic', messages: [{ role: 'user', content: 'Hi' }] }
const answer = { content: [{ type: 'text', text: 'Hello' }], usage: { input_tokens: 100, output_tokens: 10 } }
let calls: { url: string; body: Record<string, unknown> }[]
let reserve: unknown, reply: unknown, settleFails: boolean
beforeEach(() => {
  process.env.AI_BUDGET_SUPABASE_URL = 'https://synthetic.supabase.co'
  process.env.AI_BUDGET_SERVICE_ROLE_KEY = 'synthetic-private'
  calls = []; reserve = 'reserved'; reply = answer; settleFails = false
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    calls.push({ url, body })
    if (url.endsWith('/endpoints')) return Response.json(catalog())
    if (url.endsWith('/threadline_reserve_ai_spend')) return Response.json(reserve)
    if (url.endsWith('/threadline_settle_ai_spend')) { if (settleFails) throw Error('offline'); return Response.json(true) }
    return Response.json(reply)
  }))
})
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); delete process.env.AI_BUDGET_SUPABASE_URL; delete process.env.AI_BUDGET_SERVICE_ROLE_KEY })
describe('server spending guard', () => {
  it('reserves the entire context ceiling before provider execution; settles conservative verified usage', async () => {
    expect((await budgetedMessage('synthetic-gateway', payload)).status).toBe(200)
    expect(calls.map(c => c.url.split('/').at(-1))).toEqual(['endpoints', 'threadline_reserve_ai_spend', 'messages', 'threadline_settle_ai_spend'])
    expect(calls[1].body.p_micros).toBe(612000)
    expect(calls[2].body.providerOptions).toEqual({ gateway: { only: ['anthropic'] } })
    expect(calls[3].body).toEqual({ p_id: calls[1].body.p_id, p_micros: 400 })
  })
  it.each(['disabled', 'duplicate', null, {}, true])('refuses ambiguous reservation %j', async value => {
    reserve = value
    await expect(budgetedMessage('key', payload)).rejects.toMatchObject({ status: 503 })
    expect(calls.some(c => c.url.endsWith('/messages'))).toBe(false)
  })
  it('returns budget exhaustion without sending a paid request', async () => {
    reserve = 'exhausted'
    await expect(budgetedMessage('key', payload)).rejects.toMatchObject({ status: 402 })
    expect(calls).toHaveLength(2)
  })
  it('requires server-only credentials and valid URL', async () => {
    delete process.env.AI_BUDGET_SERVICE_ROLE_KEY
    await expect(budgetedMessage('key', payload)).rejects.toMatchObject({ status: 503 })
    expect(calls).toHaveLength(0)
    process.env.AI_BUDGET_SERVICE_ROLE_KEY = 'synthetic'; process.env.AI_BUDGET_SUPABASE_URL = 'http://unsafe.test'
    await expect(budgetedMessage('key', payload)).rejects.toMatchObject({ status: 503 })
    expect(calls).toHaveLength(0)
  })
  it.each([{ model: 'expensive' }, { max_tokens: 1201 }, { max_tokens: -1 }, { thinking: { budget_tokens: 50000 } }, { providerOptions: {} }, { tools: [{ type: 'web_search_20250305', name: 'web_search' }] }, { messages: [{ role: 'user', content: [{ type: 'image', source: {} }] }] }])('rejects unbudgeted configuration %j', async override => {
    await expect(budgetedMessage('key', { ...payload, ...override })).rejects.toMatchObject({ status: 503 })
    expect(calls).toHaveLength(0)
  })
  it('retains uncertain holds instead of guessing a refund', async () => {
    reply = { content: [] }
    await budgetedMessage('key', payload)
    expect(calls).toHaveLength(3)
  })
  it('preserves a successful response when settlement fails (hold remains)', async () => {
    settleFails = true
    expect((await budgetedMessage('key', payload)).status).toBe(200)
    expect(calls).toHaveLength(4)
  })
  it('never retries provider errors or releases their reservation', async () => {
    const original = fetch
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => url.endsWith('/messages') ? Promise.reject(Error('uncertain charge')) : original(url, init)))
    await expect(budgetedMessage('key', payload)).rejects.toMatchObject({ status: 503 })
    expect(vi.mocked(fetch).mock.calls.filter(c => String(c[0]).endsWith('/messages'))).toHaveLength(1)
    expect(calls.some(c => c.url.endsWith('/threadline_settle_ai_spend'))).toBe(false)
  })
  it('cannot send after cancellation during reservation', async () => {
    const controller = new AbortController(), original = fetch
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const result = await original(url, init)
      if (url.endsWith('/threadline_reserve_ai_spend')) controller.abort()
      return result
    }))
    await expect(budgetedMessage('key', payload, controller.signal)).rejects.toMatchObject({ status: 503 })
    expect(calls.some(c => c.url.endsWith('/messages'))).toBe(false)
  })
})
describe('price and usage verification', () => {
  it('recognizes the checked price snapshot', () => expect(certifiedPrice(catalog())).toBe(true))
  it.each(['prompt', 'completion', 'request', 'image', 'internal_reasoning', 'input_cache_write'])('rejects tariff increase: %s', key => {
    const c = catalog(); (c.data.endpoints[0].pricing as Record<string, unknown>)[key] = '10'
    expect(certifiedPrice(c)).toBe(false)
  })
  it('rejects missing pricing, unknown dimensions and changed context ceiling', () => {
    expect(certifiedPrice(null)).toBe(false)
    const c = catalog(); c.data.endpoints[0].context_length = 1000000; expect(certifiedPrice(c)).toBe(false)
    const d = catalog(); Object.assign(d.data.endpoints[0].pricing, { new_fee: '1' }); expect(certifiedPrice(d)).toBe(false)
  })
  it('includes cache creation/read tokens in the conservative charge', () => {
    expect(usageCharge({ usage: { input_tokens: 10, output_tokens: 2, cache_read_input_tokens: 20, cache_creation_input_tokens: 30 } }, 1200)).toBe(200)
  })
  it.each([{}, { input_tokens: -1, output_tokens: 1 }, { input_tokens: 200001, output_tokens: 1 }, { input_tokens: 1, output_tokens: 1201 }, { input_tokens: 1, output_tokens: 1, new_fee: 1 }, { input_tokens: 1, output_tokens: 1, service_tier: 'priority' }])('does not settle ambiguous usage %j', usage => expect(usageCharge({ usage }, 1200)).toBeUndefined())
})
