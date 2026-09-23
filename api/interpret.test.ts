import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getVercelOidcToken } from '@vercel/oidc'
import handler, { AI_INTERPRETATION_MODEL } from './interpret'

vi.mock('@vercel/oidc', () => ({ getVercelOidcToken: vi.fn() }))
const getVercelOidcTokenMock = vi.mocked(getVercelOidcToken)

declare const process: { env: Record<string, string | undefined> }

const request = () => new Request('https://threadline.test/api/interpret', {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ capture: {
    id: 'capture-1', source: 'text', createdAt: '2026-09-20T00:00:00Z',
    originalContent: 'Organize the launch notes', evidence: 'text-only',
  } }),
})

const validProviderResponse = { content: [{
  type: 'tool_use', input: { summary: 'Organize launch notes', rationale: 'A clear idea.', confidence: .9, proposedKind: 'idea' },
}] }

beforeEach(() => {
  vi.unstubAllGlobals()
  getVercelOidcTokenMock.mockReset()
  process.env.AI_INTERPRETATION_PROVIDER = 'enabled'
})

afterEach(() => {
  delete process.env.AI_GATEWAY_API_KEY
  delete process.env.VERCEL_OIDC_TOKEN
  delete process.env.AI_INTERPRETATION_PROVIDER
  delete process.env.AI_INTERPRETATION_API_KEY
  delete process.env.AI_INTERPRETATION_MODEL
  vi.unstubAllGlobals()
})

describe('API endpoint', () => {
  it('rejects non-POST requests', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(validProviderResponse)))
    vi.stubGlobal('fetch', fetchMock)

    const getRequest = new Request('https://threadline.test/api/interpret', { method: 'GET' })
    const response = await handler(getRequest)
    expect(response.status).toBe(405)
    expect(await response.json()).toEqual({ error: 'method_not_allowed' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects invalid JSON', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(validProviderResponse)))
    vi.stubGlobal('fetch', fetchMock)

    const badRequest = new Request('https://threadline.test/api/interpret', {
      method: 'POST',
      body: 'not json',
    })
    const response = await handler(badRequest)
    expect(response.status).toBe(400)
    expect(await response.json()).toEqual({ error: 'invalid_json' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects invalid capture structure', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(validProviderResponse)))
    vi.stubGlobal('fetch', fetchMock)

    const badRequest = new Request('https://threadline.test/api/interpret', {
      method: 'POST',
      body: JSON.stringify({ capture: { id: 'test' } }),
    })
    const response = await handler(badRequest)
    expect(response.status).toBe(400)
    expect(await response.json()).toEqual({ error: 'invalid_capture' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('calls Vercel AI Gateway endpoint with Bearer token auth', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-bearer-key'
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(validProviderResponse), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://ai-gateway.vercel.sh/v1/messages')
    expect(init?.headers).toHaveProperty('authorization', 'Bearer test-bearer-key')
  })

  it('calls Vercel AI Gateway endpoint with OIDC token fallback', async () => {
    process.env.VERCEL_OIDC_TOKEN = 'test-oidc-token'
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(validProviderResponse), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://ai-gateway.vercel.sh/v1/messages')
    expect(init?.headers).toHaveProperty('authorization', 'Bearer test-oidc-token')
  })

  it('uses the trusted Vercel runtime OIDC helper when no environment token is present', async () => {
    getVercelOidcTokenMock.mockResolvedValue('runtime-oidc-token')
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(validProviderResponse), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(200)
    expect(getVercelOidcTokenMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.headers).toHaveProperty('authorization', 'Bearer runtime-oidc-token')
  })

  it('prefers Bearer token over OIDC token when both are present', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-bearer-key'
    process.env.VERCEL_OIDC_TOKEN = 'test-oidc-token'
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(validProviderResponse), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(200)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.headers).toHaveProperty('authorization', 'Bearer test-bearer-key')
  })
})

describe('Authentication', () => {
  it('does not call the provider when only automatic OIDC is available and the server gate is disabled', async () => {
    delete process.env.AI_INTERPRETATION_PROVIDER
    process.env.VERCEL_OIDC_TOKEN = 'automatic-oidc-token'
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(503)
    expect(await response.json()).toEqual({
      error: 'provider_disabled',
      message: 'AI interpretation is not enabled for this deployment.',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('returns 503 when neither Bearer token nor OIDC token is configured', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(503)
    const json = await response.json()
    expect(json.error).toBe('not_configured')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('AI interpretation provider model', () => {
  it('always sends Haiku through the Vercel AI Gateway model namespace', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(validProviderResponse)))
    vi.stubGlobal('fetch', fetchMock)

    const response = await handler(request())
    expect(response.status).toBe(200)
    expect(AI_INTERPRETATION_MODEL).toBe('anthropic/claude-haiku-4.5')
    const providerBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(providerBody.model).toBe('anthropic/claude-haiku-4.5')
  })
})

describe('Provider response validation', () => {
  it('returns 200 with valid proposal for action', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: { summary: 'Call Ahmed', rationale: 'Clear action.', confidence: .95, proposedKind: 'action' } }],
    }))))

    const response = await handler(request())
    expect(response.status).toBe(200)
    const proposal = await response.json()
    expect(proposal.proposedKind).toBe('action')
    expect(proposal.proposedAction).toBeDefined()
    expect(proposal.proposedAction?.summary).toBe('Call Ahmed')
    expect(proposal.reviewState).toBe('review')
  })

  it('forces reviewState to "review" regardless of provider output', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: {
        summary: 'Test', rationale: 'Test.', confidence: .9, proposedKind: 'idea', reviewState: 'confirmed',
      } }],
    }))))

    const response = await handler(request())
    const proposal = await response.json()
    expect(proposal.reviewState).toBe('review')
  })

  it('derives proposedAction.summary from validated summary, not provider override', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: {
        summary: 'Organize notes', rationale: 'Clear.', confidence: .9, proposedKind: 'action',
      } }],
    }))))

    const response = await handler(request())
    const proposal = await response.json()
    expect(proposal.proposedAction?.summary).toBe('Organize notes')
    expect(proposal.proposedAction?.summary).toBe(proposal.summary)
  })

  it('handles unresolved kind with proposedReminder derived from capture', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: {
        summary: 'Call Ahmed Monday', rationale: 'Timing not confirmed.', confidence: .7, proposedKind: 'unresolved',
      } }],
    }))))

    const response = await handler(request())
    const proposal = await response.json()
    expect(proposal.proposedKind).toBe('unresolved')
    expect(proposal.proposedReminder).toBeDefined()
    expect(proposal.proposedReminder?.captureIds).toEqual(['capture-1'])
    expect(proposal.proposedReminder?.trigger.wording).toBe('Organize the launch notes')
    expect(proposal.proposedReminder?.deliveryState).toBe('needs-review')
  })

  it('rejects response without tool_use block', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'text', text: 'Some text' }],
    }))))

    const response = await handler(request())
    expect(response.status).toBe(502)
    expect(await response.json()).toEqual({ error: 'provider_error', message: expect.stringContaining('structured output') })
  })

  it('rejects response with non-object tool input', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: 'not an object' }],
    }))))

    const response = await handler(request())
    expect(response.status).toBe(502)
  })

  it('handles missing summary field gracefully', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: { rationale: 'Test.', confidence: .9, proposedKind: 'idea' } }],
    }))))

    const response = await handler(request())
    const proposal = await response.json()
    expect(proposal.summary).toBe('Organize the launch notes')
  })

  it('truncates oversized summary to 200 chars', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    const longSummary = 'a'.repeat(300)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: { summary: longSummary, rationale: 'Test.', confidence: .9, proposedKind: 'idea' } }],
    }))))

    const response = await handler(request())
    const proposal = await response.json()
    expect(proposal.summary.length).toBe(200)
  })

  it('rejects unsupported proposedKind', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      content: [{ type: 'tool_use', input: { summary: 'Test', rationale: 'Test.', confidence: .9, proposedKind: 'unsupported' } }],
    }))))

    const response = await handler(request())
    expect(response.status).toBe(502)
  })
})

describe('Upstream provider errors', () => {
  it('returns 502 when provider responds with non-2xx status', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 })))

    const response = await handler(request())
    expect(response.status).toBe(502)
    const error = await response.json()
    expect(error.error).toBe('provider_error')
    expect(error.message).toContain('status 401')
  })

  it('returns 502 when provider returns invalid JSON', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => new Response('not json', { status: 200 })))

    const response = await handler(request())
    expect(response.status).toBe(502)
    expect(await response.json()).toEqual({ error: 'provider_error', message: expect.any(String) })
  })

  it('returns 502 on network error', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('Network timeout')
    }))

    const response = await handler(request())
    expect(response.status).toBe(502)
    const error = await response.json()
    expect(error.message).toContain('Network timeout')
  })
})

describe('Timeout behavior (abort-aware mock)', () => {
  it('aborts the fetch when timeout expires', async () => {
    vi.useFakeTimers()
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    let receivedSignal: AbortSignal | undefined
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      receivedSignal = init?.signal ?? undefined
      await new Promise(resolve => {
        if (receivedSignal) receivedSignal.addEventListener('abort', resolve)
      })
      throw new Error('aborted')
    })
    vi.stubGlobal('fetch', fetchMock)

    try {
      const responsePromise = handler(request())
      await vi.runAllTimersAsync()
      const response = await responsePromise
      expect(response.status).toBe(502)
      expect(receivedSignal?.aborted).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('clears timeout after successful response', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout')
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(validProviderResponse))))

    const response = await handler(request())
    expect(response.status).toBe(200)
    expect(clearTimeoutSpy).toHaveBeenCalled()
  })

  it('clears timeout even on error', async () => {
    process.env.AI_GATEWAY_API_KEY = 'test-key'
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout')
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('fetch failed')
    }))

    const response = await handler(request())
    expect(response.status).toBe(502)
    expect(clearTimeoutSpy).toHaveBeenCalled()
  })
})
