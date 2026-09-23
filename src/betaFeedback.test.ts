import { describe, expect, it } from 'vitest'
import { createBetaFeedback, exportBetaFeedback, type BetaFeedbackInput } from './betaFeedback'

const valid = (): BetaFeedbackInput => ({
  category: 'bug', severity: 'high', description: 'The save button does not respond.',
  reproductionSteps: 'Open a thought, edit it, and press Save.', createdAt: '2026-09-23T10:00:00.000Z',
})

describe('local beta feedback model', () => {
  it('creates valid feedback without browser or network access', () => {
    expect(createBetaFeedback(valid())).toEqual(valid())
  })

  it('enforces description and reproduction length bounds', () => {
    expect(() => createBetaFeedback({ ...valid(), description: '' })).toThrow('description')
    expect(() => createBetaFeedback({ ...valid(), description: 'x'.repeat(501) })).toThrow('description')
    expect(() => createBetaFeedback({ ...valid(), reproductionSteps: 'x'.repeat(2_001) })).toThrow('reproductionSteps')
  })

  it('validates category, severity, and createdAt', () => {
    expect(() => createBetaFeedback({ ...valid(), category: 'unknown' as never })).toThrow('category')
    expect(() => createBetaFeedback({ ...valid(), severity: 'urgent' as never })).toThrow('severity')
    expect(() => createBetaFeedback({ ...valid(), createdAt: 'not-a-date' })).toThrow('createdAt')
  })

  it('requires explicit diagnostics opt-in and detaches the snapshot', () => {
    const diagnostics = { build: 'test', nested: { browser: 'none' } }
    const withoutOptIn = createBetaFeedback({ ...valid(), diagnosticsSnapshot: diagnostics })
    expect(withoutOptIn).not.toHaveProperty('diagnosticsSnapshot')
    const withOptIn = createBetaFeedback({ ...valid(), diagnosticsSnapshot: diagnostics, includeDiagnostics: true })
    expect(withOptIn.diagnosticsSnapshot).toEqual(diagnostics)
    expect(withOptIn.diagnosticsSnapshot).not.toBe(diagnostics)
  })

  it('rejects sensitive fields anywhere in the supplied payload', () => {
    expect(() => createBetaFeedback({ ...valid(), diagnosticsSnapshot: { deviceId: 'abc' }, includeDiagnostics: true })).toThrow('Sensitive')
    expect(() => createBetaFeedback({ ...valid(), canvas: [] } as never)).toThrow('Sensitive')
    expect(() => createBetaFeedback({ ...valid(), diagnosticsSnapshot: { nested: { email: 'a@b.test' } }, includeDiagnostics: true })).toThrow('Sensitive')
  })

  it('exports deterministic JSON with stable nested key order', () => {
    const feedback = { ...valid(), diagnosticsSnapshot: { z: 1, a: { y: 2, b: 3 } }, includeDiagnostics: true }
    expect(exportBetaFeedback(feedback)).toBe('{"category":"bug","createdAt":"2026-09-23T10:00:00.000Z","description":"The save button does not respond.","diagnosticsSnapshot":{"a":{"b":3,"y":2},"z":1},"reproductionSteps":"Open a thought, edit it, and press Save.","severity":"high"}')
  })

  it('does not mutate input or its diagnostics snapshot', () => {
    const input = { ...valid(), diagnosticsSnapshot: { z: 1, a: { value: true } }, includeDiagnostics: true }
    const before = JSON.stringify(input)
    createBetaFeedback(input)
    expect(JSON.stringify(input)).toBe(before)
  })
})
