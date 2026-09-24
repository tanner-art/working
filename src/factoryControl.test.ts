import { describe, expect, it } from 'vitest'
import { factoryControlFixture } from './factoryControl.fixture'
import { formatDuration, formatFactoryState, formatRelativeTime, parseFactoryControlSnapshot, parseFactoryProjection, safeExternalUrl } from './factoryControl'

describe('Factory Control Center snapshot contract', () => {
  it('accepts and sanitizes the representative Registry projection', () => {
    const parsed = parseFactoryControlSnapshot({ ...factoryControlFixture, ignored: 'not returned' })
    expect(parsed.registryRevision).toBe('registry-1842')
    expect(parsed.features[0].packages[0].currentLease?.workerId).toBe('agent-b')
    expect(parsed.capacity.find(scope => scope.workerId === 'claude')?.usedPercent).toBeNull()
    expect(parsed).not.toHaveProperty('ignored')
  })

  it('fails closed for unknown states and missing required collections', () => {
    expect(() => parseFactoryControlSnapshot({ ...factoryControlFixture, factory: { ...factoryControlFixture.factory, health: 'excellent' } })).toThrow('unsupported')
    const { reviews: _reviews, ...withoutReviews } = factoryControlFixture
    expect(() => parseFactoryControlSnapshot(withoutReviews)).toThrow('snapshot.reviews')
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
