import { describe, expect, it } from 'vitest'
import { createBetaDiagnosticsSnapshot } from './betaDiagnostics'

describe('beta diagnostics snapshot', () => {
  it('summarizes signed-out local-only testing', () => {
    const snapshot = createBetaDiagnosticsSnapshot({ buildLabel: 'beta 1', storageMode: 'local-only', authState: 'signed-out', provider: { kind: 'deterministic' }, displayMode: 'browser', recordCounts: { captures: 2 } })
    expect(snapshot).toMatchObject({ buildLabel: 'beta 1', storage: { status: 'Local-only storage' }, authentication: { status: 'Signed out' }, provider: { status: 'Deterministic provider ready' }, display: { status: 'Browser display' }, recordCounts: { captures: 2 } })
  })

  it('summarizes authenticated sync and a verified remote provider', () => {
    const snapshot = createBetaDiagnosticsSnapshot({ storageMode: 'sync', authState: 'authenticated', provider: { kind: 'remote', configured: true, verified: true }, displayMode: 'installed' })
    expect(snapshot).toMatchObject({ storage: { mode: 'sync' }, authentication: { state: 'authenticated' }, provider: { status: 'Remote provider verified' }, display: { mode: 'installed' } })
  })

  it('does not claim provider success from configuration alone', () => {
    const snapshot = createBetaDiagnosticsSnapshot({ provider: { kind: 'remote', configured: true, verified: false } })
    expect(snapshot.provider.status).toBe('Remote provider configured but unverified')
    expect(snapshot.provider.nextStep).toMatch(/explicit provider verification/)
  })

  it('handles missing values with actionable unknown states', () => {
    const snapshot = createBetaDiagnosticsSnapshot()
    expect(snapshot.buildLabel).toBe('Unknown build')
    expect(snapshot.storage.mode).toBe('unknown')
    expect(snapshot.authentication.state).toBe('unknown')
    expect(snapshot.provider.kind).toBe('unknown')
    expect(snapshot.display.mode).toBe('unknown')
    expect(snapshot.provider.nextStep).toMatch(/Provide/)
  })

  it('clamps counts and supplies zero for missing or invalid values', () => {
    const snapshot = createBetaDiagnosticsSnapshot({ recordCounts: { captures: -3, interpretations: 2.9, semanticObjects: Number.POSITIVE_INFINITY, canvasElements: 2_000_000_000 } })
    expect(snapshot.recordCounts).toEqual({ captures: 0, interpretations: 2, semanticObjects: 0, canvasElements: 999_999_999 })
  })

  it('does not mutate caller input and does not retain its count object', () => {
    const input = { buildLabel: '  test  ', recordCounts: { captures: 3 } }
    const snapshot = createBetaDiagnosticsSnapshot(input as Parameters<typeof createBetaDiagnosticsSnapshot>[0])
    input.recordCounts.captures = 99
    expect(snapshot.buildLabel).toBe('test')
    expect(snapshot.recordCounts.captures).toBe(3)
    expect(snapshot.recordCounts).not.toBe(input.recordCounts)
  })

  it('contains no sensitive content from extra input properties', () => {
    const input = { buildLabel: 'safe', recordCounts: { captures: 1 }, provider: { kind: 'deterministic' }, email: 'person@example.com', captureContents: 'private thought', userId: 'secret-id' }
    const snapshot = createBetaDiagnosticsSnapshot(input as Parameters<typeof createBetaDiagnosticsSnapshot>[0])
    expect(JSON.stringify(snapshot)).not.toMatch(/person@example\.com|private thought|secret-id/)
  })
})
