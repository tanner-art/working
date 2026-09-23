import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import handler, { AI_INTERPRETATION_MODEL } from './interpret'

declare const process: { env: Record<string, string | undefined> }

const request = () => new Request('https://threadline.test/api/interpret', {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ capture: {
    id: 'capture-1', source: 'text', createdAt: '2026-09-20T00:00:00Z',
    originalContent: 'Organize the launch notes', evidence: 'text-only',
  } }),
})

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  delete process.env.AI_INTERPRETATION_API_KEY
  delete process.env.AI_INTERPRETATION_MODEL
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('AI interpretation provider model', () => {
  it('always sends Haiku even when a deployment environment requests another model', async () => {
    vi.useRealTimers()
    process.env.AI_INTERPRETATION_API_KEY = 'test-key'
    process.env.AI_INTERPRETATION_MODEL = 'claude-sonnet-5'
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => new Response(JSON.stringify({ content: [{
      type: 'tool_use', input: { summary: 'Organize launch notes', rationale: 'A clear idea.', confidence: .9, proposedKind: 'idea' },
    }] }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(200)
    expect(AI_INTERPRETATION_MODEL).toBe('claude-haiku-4-5-20251001')
    const providerBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(providerBody.model).toBe('claude-haiku-4-5-20251001')
  })
})

describe('timeout handling', () => {
  it('aborts the fetch when timeout expires', async () => {
    process.env.AI_INTERPRETATION_API_KEY = 'test-key'

    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.signal) {
        return new Promise((_, reject) => {
          init.signal!.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'))
          })
        })
      }
      return Promise.reject(new Error('fetch called without abort signal'))
    })
    vi.stubGlobal('fetch', fetchMock)

    const handlerPromise = handler(request())

    await vi.runAllTimersAsync()

    const response = await handlerPromise
    expect(response.status).toBe(502)
    const body = await response.json() as Record<string, unknown>
    expect(body.error).toBe('provider_error')
  })
})
