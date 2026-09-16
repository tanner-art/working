import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CaptureRecord } from './domain'
import {
  createFailClosedInterpretationService, createProviderInterpretationService,
  providerStatus, readProviderConfig, validateInterpretationProposal,
} from './aiInterpretation'
import { deterministicInterpretationService } from './interpreter'

const capture: CaptureRecord = Object.freeze({ id: 'capture:test', source: 'text',
  createdAt: '2026-09-16T00:00:00.000Z', originalContent: 'Give marketing guys access',
  context: 'Marketing', evidence: 'text-only' })

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response
}
function failResponse(status: number) {
  return { ok: false, status, json: async () => ({}) } as Response
}
/** Typed exactly like `fetch` so assignment to ProviderCallOptions.fetchImpl and reads of
 * `.mock.calls` stay type-safe without widening to `any`. */
function fetchMock(impl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  return vi.fn(impl)
}

beforeEach(() => { vi.spyOn(console, 'warn').mockImplementation(() => {}) })
afterEach(() => { vi.restoreAllMocks() })

describe('readProviderConfig', () => {
  it.each([{}, { VITE_AI_INTERPRETATION_PROVIDER: undefined }, { VITE_AI_INTERPRETATION_PROVIDER: '' },
    { VITE_AI_INTERPRETATION_PROVIDER: 'true' }, { VITE_AI_INTERPRETATION_PROVIDER: 'ENABLED' },
    { VITE_AI_INTERPRETATION_PROVIDER: 'disabled' }])('defaults to disabled: %j', env => {
    expect(readProviderConfig(env).status).toBe('disabled')
  })

  it('enables only on the exact opt-in value', () => {
    expect(readProviderConfig({ VITE_AI_INTERPRETATION_PROVIDER: 'enabled' }).status).toBe('enabled')
    expect(readProviderConfig({ VITE_AI_INTERPRETATION_PROVIDER: ' enabled ' }).status).toBe('enabled')
  })
})



describe('providerStatus', () => {
  it('describes deterministic-only mode without claiming provider access', () => {
    expect(providerStatus({ status: 'disabled' })).toMatchObject({ enabled: false, label: 'Built-in rules only' })
    expect(providerStatus({ status: 'disabled' }).description).toContain('No provider request')
  })

  it('describes enabled mode as provider attempts with fail-closed fallback', () => {
    expect(providerStatus({ status: 'enabled' })).toMatchObject({ enabled: true, label: 'Provider attempts enabled' })
    expect(providerStatus({ status: 'enabled' }).description).toContain('falls back')
  })
})

describe('validateInterpretationProposal', () => {
  it.each([undefined, null, 'text', 42])('rejects a non-object payload: %j', value => {
    expect(() => validateInterpretationProposal(capture, value)).toThrow('not an object')
  })

  it.each([
    { rationale: 'r', confidence: .5, proposedKind: 'idea' },
    { summary: '  ', rationale: 'r', confidence: .5, proposedKind: 'idea' },
    { summary: 's', confidence: .5, proposedKind: 'idea' },
    { summary: 's', rationale: '  ', confidence: .5, proposedKind: 'idea' },
    { summary: 's', rationale: 'r', proposedKind: 'idea' },
    { summary: 's', rationale: 'r', confidence: 1.5, proposedKind: 'idea' },
    { summary: 's', rationale: 'r', confidence: -0.1, proposedKind: 'idea' },
    { summary: 's', rationale: 'r', confidence: Number.NaN, proposedKind: 'idea' },
    { summary: 's', rationale: 'r', confidence: '0.5', proposedKind: 'idea' },
  ])('rejects a malformed payload: %j', payload => {
    expect(() => validateInterpretationProposal(capture, payload)).toThrow()
  })

  it.each(['task', 'note', '', undefined, 123])('rejects an unsupported proposedKind: %j', proposedKind => {
    expect(() => validateInterpretationProposal(capture, { summary: 's', rationale: 'r', confidence: .5, proposedKind }))
      .toThrow('unsupported proposedKind')
  })

  it('forces reviewState to review even if the payload claims otherwise', () => {
    const result = validateInterpretationProposal(capture,
      { summary: 's', rationale: 'r', confidence: .5, proposedKind: 'idea', reviewState: 'accepted' })
    expect(result.reviewState).toBe('review')
  })

  it.each(['idea', 'project', 'commitment', 'person', 'reference', 'objective'])
  ('accepts each resolved kind: %s', proposedKind => {
    const result = validateInterpretationProposal(capture, { summary: 'Summary', rationale: 'Rationale', confidence: .7, proposedKind })
    expect(result).toMatchObject({ proposedKind, summary: 'Summary', rationale: 'Rationale', confidence: .7, reviewState: 'review' })
    expect(result.proposedAction).toBeUndefined()
    expect(result.proposedReminder).toBeUndefined()
  })

  it('derives proposedAction.summary from the validated summary, not a payload-supplied field', () => {
    const result = validateInterpretationProposal(capture,
      { summary: 'Real summary', rationale: 'r', confidence: .9, proposedKind: 'action', proposedAction: { summary: 'Spoofed summary' } })
    expect(result.proposedKind).toBe('action')
    if (result.proposedKind === 'action') expect(result.proposedAction).toEqual({ summary: 'Real summary' })
  })

  it('derives the unresolved reminder from the capture, ignoring an attacker-controlled trigger/captureIds', () => {
    const result = validateInterpretationProposal(capture, {
      summary: 's', rationale: 'r', confidence: .7, proposedKind: 'unresolved', suggestedDate: 'Tuesday',
      proposedReminder: { captureIds: ['capture:someone-else'], deliveryState: 'needs-review',
        trigger: { kind: 'unresolved', wording: 'attacker-controlled text', legacyDate: 'Friday' } },
    })
    expect(result.proposedKind).toBe('unresolved')
    if (result.proposedKind === 'unresolved') {
      expect(result.proposedReminder).toEqual({ captureIds: [capture.id], deliveryState: 'needs-review',
        trigger: { kind: 'unresolved', wording: capture.originalContent, legacyDate: 'Tuesday' } })
    }
  })

  it('drops a non-string or empty suggestedDate', () => {
    expect(validateInterpretationProposal(capture, { summary: 's', rationale: 'r', confidence: .5, proposedKind: 'idea', suggestedDate: '' }).suggestedDate).toBeUndefined()
    expect(validateInterpretationProposal(capture, { summary: 's', rationale: 'r', confidence: .5, proposedKind: 'idea', suggestedDate: 5 }).suggestedDate).toBeUndefined()
  })

  it('does not let a provider claim confidence above the accepted range', () => {
    expect(() => validateInterpretationProposal(capture, { summary: 's', rationale: 'r', confidence: .99, proposedKind: 'action' })).not.toThrow()
    expect(() => validateInterpretationProposal(capture, { summary: 's', rationale: 'r', confidence: 1.01, proposedKind: 'action' })).toThrow('invalid confidence')
  })
})

describe('createProviderInterpretationService', () => {
  it('posts only the minimal capture fields to the configured endpoint', async () => {
    const fetchImpl = fetchMock(async () => okResponse({ summary: 'Provider summary', rationale: 'Provider rationale', confidence: .8, proposedKind: 'idea' }))
    const service = createProviderInterpretationService({ fetchImpl, endpoint: '/api/custom' })
    const result = await service.interpret(capture)
    expect(result).toMatchObject({ proposedKind: 'idea', summary: 'Provider summary', reviewState: 'review' })
    expect(fetchImpl).toHaveBeenCalledOnce()
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/custom')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ capture: {
      id: capture.id, source: capture.source, createdAt: capture.createdAt,
      originalContent: capture.originalContent, context: capture.context, evidence: capture.evidence,
    } })
  })

  it('defaults to the /api/interpret endpoint', async () => {
    const fetchImpl = fetchMock(async () => okResponse({ summary: 's', rationale: 'r', confidence: .5, proposedKind: 'idea' }))
    await createProviderInterpretationService({ fetchImpl }).interpret(capture)
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/interpret')
  })

  it('propagates a network failure', async () => {
    const fetchImpl = fetchMock(async () => { throw new Error('offline') })
    await expect(createProviderInterpretationService({ fetchImpl }).interpret(capture)).rejects.toThrow('offline')
  })

  it('propagates a non-2xx response as an error', async () => {
    const fetchImpl = fetchMock(async () => failResponse(503))
    await expect(createProviderInterpretationService({ fetchImpl }).interpret(capture)).rejects.toThrow('status 503')
  })

  it('propagates a malformed payload as a validation error', async () => {
    const fetchImpl = fetchMock(async () => okResponse({ proposedKind: 'idea' }))
    await expect(createProviderInterpretationService({ fetchImpl }).interpret(capture)).rejects.toThrow()
  })

  it('aborts and rejects when the endpoint never responds within the timeout', async () => {
    const fetchImpl = fetchMock((_input, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    await expect(createProviderInterpretationService({ fetchImpl, timeoutMs: 5 }).interpret(capture)).rejects.toThrow()
  })
})

describe('createFailClosedInterpretationService', () => {
  it('never calls the network when disabled and matches the deterministic service exactly', async () => {
    const fetchImpl = fetchMock(async () => okResponse({}))
    const service = createFailClosedInterpretationService({ status: 'disabled' }, { fetchImpl })
    const result = await service.interpret(capture)
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(result).toEqual(await deterministicInterpretationService.interpret(capture))
  })

  it('returns the validated provider result when enabled and the endpoint succeeds', async () => {
    const fetchImpl = fetchMock(async () => okResponse({ summary: 'Provider summary', rationale: 'Provider rationale', confidence: .81, proposedKind: 'action' }))
    const service = createFailClosedInterpretationService({ status: 'enabled' }, { fetchImpl })
    const result = await service.interpret(capture)
    expect(result).toMatchObject({ proposedKind: 'action', summary: 'Provider summary', reviewState: 'review' })
  })

  it('falls back to the deterministic service on a network error', async () => {
    const fetchImpl = fetchMock(async () => { throw new Error('offline') })
    const service = createFailClosedInterpretationService({ status: 'enabled' }, { fetchImpl })
    expect(await service.interpret(capture)).toEqual(await deterministicInterpretationService.interpret(capture))
  })

  it('falls back to the deterministic service on a non-2xx response', async () => {
    const fetchImpl = fetchMock(async () => failResponse(500))
    const service = createFailClosedInterpretationService({ status: 'enabled' }, { fetchImpl })
    expect(await service.interpret(capture)).toEqual(await deterministicInterpretationService.interpret(capture))
  })

  it('falls back to the deterministic service on a malformed payload', async () => {
    const fetchImpl = fetchMock(async () => okResponse({ proposedKind: 'idea' }))
    const service = createFailClosedInterpretationService({ status: 'enabled' }, { fetchImpl })
    expect(await service.interpret(capture)).toEqual(await deterministicInterpretationService.interpret(capture))
  })

  it('never lets a provider response bypass review, even when it tries to', async () => {
    const fetchImpl = fetchMock(async () => okResponse({ summary: 's', rationale: 'r', confidence: .9, proposedKind: 'idea', reviewState: 'accepted' }))
    const service = createFailClosedInterpretationService({ status: 'enabled' }, { fetchImpl })
    const result = await service.interpret(capture)
    expect(result.reviewState).toBe('review')
  })
})
