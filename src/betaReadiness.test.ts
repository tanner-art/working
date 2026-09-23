import { describe, expect, it } from 'vitest'
import { BETA_READINESS_CHECK_IDS, scoreBetaReadiness, type BetaReadinessCheck } from './betaReadiness'

const complete = (status: BetaReadinessCheck['status'] = 'pass'): BetaReadinessCheck[] =>
  BETA_READINESS_CHECK_IDS.map(id => ({ id, status, evidence: `observed ${id}` }))

describe('friends-and-family beta readiness', () => {
  it('reports full readiness only from explicit passing checks', () => {
    const result = scoreBetaReadiness(complete())
    expect(result.overall).toBe('ready')
    expect(result.counts).toEqual({ total: 15, pass: 15, fail: 0, notTested: 0, blocked: 0 })
    expect(result.blockingCheckIds).toEqual([])
    expect(result.nextActions).toEqual([])
  })

  it('allows a provider-blocked deterministic-only conditional beta', () => {
    const checks = complete().map(check => check.id === 'provider-backed-ai-verification' ? { ...check, status: 'blocked' as const } : check)
    const result = scoreBetaReadiness(checks)
    expect(result.overall).toBe('conditional')
    expect(result.blockingCheckIds).toEqual([])
    expect(result.nextActions).toEqual(['provider-backed-ai-verification'])
  })

  it('makes critical failures not-ready and orders their actions canonically', () => {
    const checks = complete().map(check => ['capture', 'calendar', 'canvas'].includes(check.id) ? { ...check, status: 'fail' as const } : check)
    const result = scoreBetaReadiness(checks)
    expect(result.overall).toBe('not-ready')
    expect(result.blockingCheckIds).toEqual(['capture', 'calendar', 'canvas'])
    expect(result.nextActions.slice(0, 3)).toEqual(['capture', 'calendar', 'canvas'])
  })

  it('does not treat absent or not-tested checks as success', () => {
    const result = scoreBetaReadiness([{ id: 'capture', status: 'not-tested' }])
    expect(result.overall).toBe('not-ready')
    expect(result.counts).toMatchObject({ pass: 0, notTested: 15 })
    expect(result.blockingCheckIds[0]).toBe('sign-in-link')
    expect(result.checks.find(check => check.id === 'capture')).toEqual({ id: 'capture', status: 'not-tested' })
  })

  it('keeps ordering stable regardless of input order', () => {
    const result = scoreBetaReadiness([...complete()].reverse())
    expect(result.checks.map(check => check.id)).toEqual([...BETA_READINESS_CHECK_IDS])
    expect(result.nextActions).toEqual([])
  })

  it('rejects duplicate IDs', () => {
    expect(() => scoreBetaReadiness([{ id: 'capture', status: 'pass' }, { id: 'capture', status: 'fail' }])).toThrow('Duplicate')
  })

  it('does not mutate the supplied checks or evidence', () => {
    const checks = complete(); const before = structuredClone(checks)
    const result = scoreBetaReadiness(checks)
    expect(checks).toEqual(before)
    expect(result.checks).not.toBe(checks)
    expect(result.checks[0]).not.toBe(checks[0])
  })
})
