import { describe, expect, it } from 'vitest'
import { factoryControlFixture } from './factoryControl.fixture'
import { formatDuration, formatFactoryState, formatRelativeTime, parseFactoryControlSnapshot, parseFactoryProjection, safeExternalUrl } from './factoryControl'

describe('Factory Control Center snapshot contract', () => {
  it('accepts and sanitizes the representative Registry projection', () => {
    const parsed = parseFactoryControlSnapshot({ ...factoryControlFixture, ignored: 'not returned' })
    expect(parsed.registryRevision).toBe('registry-1842')
    expect(parsed.features[0].packages[0].currentLease?.workerId).toBe('agent-b')
    expect(parsed.features[0].packages[0].attempts[0].commitSha).toMatch(/^c4f2da8/)
    expect(parsed.capacity.find(scope => scope.workerId === 'claude')?.usedPercent).toBeNull()
    expect(parsed.usageInvocations[0]).toMatchObject({ workerId: 'claude', inputTokens: 2, outputTokens: 18, outcome: 'SUCCEEDED' })
    expect(parsed).not.toHaveProperty('ignored')
  })

  it('fails closed for unknown states and missing required collections', () => {
    expect(() => parseFactoryControlSnapshot({ ...factoryControlFixture, factory: { ...factoryControlFixture.factory, health: 'excellent' } })).toThrow('unsupported')
    const { reviews: _reviews, ...withoutReviews } = factoryControlFixture
    expect(() => parseFactoryControlSnapshot(withoutReviews)).toThrow('snapshot.reviews')
    const { usageInvocations: _usage, ...withoutUsage } = factoryControlFixture
    expect(() => parseFactoryControlSnapshot(withoutUsage)).toThrow('snapshot.usageInvocations')
  })

  it('fails closed when usage provenance or source history is incomplete', () => {
    const missingAttempt = structuredClone(factoryControlFixture)
    missingAttempt.usageInvocations[0].attemptId = null
    expect(() => parseFactoryControlSnapshot(missingAttempt)).toThrow('invalid provenance')
    const missingSource = structuredClone(factoryControlFixture)
    missingSource.usageInvocations[0].sources = []
    expect(() => parseFactoryControlSnapshot(missingSource)).toThrow('must contain an observation')
  })

  it('fails closed when invocation provenance does not resolve in the same projection', () => {
    const unknownAttempt = structuredClone(factoryControlFixture)
    unknownAttempt.usageInvocations[0].attemptId = 'attempt-not-in-registry-projection'
    expect(() => parseFactoryControlSnapshot(unknownAttempt)).toThrow('unknown package attempt')
    const unknownWorker = structuredClone(factoryControlFixture)
    unknownWorker.usageInvocations[0].workerId = 'unknown-worker'
    expect(() => parseFactoryControlSnapshot(unknownWorker)).toThrow('unknown worker')
    const wrongAttemptWorker = structuredClone(factoryControlFixture)
    wrongAttemptWorker.usageInvocations[0].workerId = 'agent-b'
    expect(() => parseFactoryControlSnapshot(wrongAttemptWorker)).toThrow('does not match the attempt worker')
  })

  it('preserves legacy unclassified usage without claiming task provenance', () => {
    const parsed = parseFactoryControlSnapshot(factoryControlFixture)
    expect(parsed.usageInvocations.find(item => item.id === 'usage-claude-legacy')).toMatchObject({
      observationClass: 'LEGACY_UNCLASSIFIED', packageId: 'SOAK-001-A', attemptId: null,
    })
  })

  it('parses the signed transport payload before API verification metadata is added', () => {
    const { verification: _verification, ...projection } = factoryControlFixture
    expect(parseFactoryProjection(projection).source.kind).toBe('registry-projection')
  })

  it('formats human-readable state and elapsed time labels', () => {
    expect(formatFactoryState('VERIFY_REVIEW')).toBe('VERIFY / REVIEW')
    expect(formatDuration(3720)).toBe('1h 2m')
    expect(formatRelativeTime('2026-09-24T18:29:30Z', new Date('2026-09-24T18:30:00Z'))).toBe('30s ago')
  })

  it.each([
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'file:///private/factory.json',
    'https://user:secret@example.test/evidence',
    '/relative/evidence',
  ])('does not make an unsafe external URL clickable: %s', value => {
    expect(safeExternalUrl(value)).toBeNull()
  })

  it('normalizes safe HTTP and HTTPS evidence links', () => {
    expect(safeExternalUrl('https://example.test/evidence')).toBe('https://example.test/evidence')
    expect(safeExternalUrl('http://localhost:4173/report')).toBe('http://localhost:4173/report')
  })
})
