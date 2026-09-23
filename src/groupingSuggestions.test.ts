import { describe, expect, it } from 'vitest'
import type { CaptureRecord } from './domain'
import { suggestGroupingProposals } from './groupingSuggestions'

const item = (id: string, originalContent: string, createdAt: string, context?: string): CaptureRecord => ({
  id, originalContent, createdAt, context, source: 'text', evidence: 'text-only',
})
const generatedAt = '2026-09-23T12:00:00Z'

describe('deterministic grouping suggestions', () => {
  it('returns no proposal for one capture or unrelated captures', () => {
    expect(suggestGroupingProposals({ captures: [item('a', 'Alpha', generatedAt)], generatedAt })).toEqual([])
    expect(suggestGroupingProposals({ captures: [
      item('a', 'Plan campaign', '2026-09-20T10:00:00Z', 'Work'),
      item('b', 'Buy oranges', '2026-09-23T10:00:00Z', 'Home'),
    ], generatedAt })).toEqual([])
  })

  it.each([
    ['topic', [item('a', 'Launch campaign outline', '2026-09-20T10:00:00Z'), item('b', 'Campaign launch notes', '2026-09-23T10:00:00Z')]],
    ['context', [item('a', 'Outline', '2026-09-20T10:00:00Z', 'Ludus'), item('b', 'Budget', '2026-09-23T10:00:00Z', 'ludus')]],
    ['recent', [item('a', 'Outline', '2026-09-23T10:00:00Z'), item('b', 'Budget', '2026-09-23T10:20:00Z')]],
  ] as const)('can propose a %s grouping from that signal', (kind, captures) => {
    const results = suggestGroupingProposals({ captures, generatedAt })
    expect(results).toHaveLength(1)
    expect(results[0]).toMatchObject({ groupingKind: kind, reviewState: 'review' })
    expect(results[0].relationships).toHaveLength(1)
  })

  it('suppresses an existing unordered relationship before it reaches Review', () => {
    const captures = [item('a', 'Launch plan', generatedAt, 'Launch'), item('b', 'Launch copy', generatedAt, 'Launch')]
    expect(suggestGroupingProposals({ captures, generatedAt, existingRelationships: [
      { type: 'relates_to', sourceCaptureId: 'b', targetCaptureId: 'a' },
    ] })).toEqual([])
  })

  it('is stable regardless of capture order and never mutates inputs', () => {
    const captures = [item('b', 'Launch copy', generatedAt, 'Launch'), item('a', 'Launch plan', generatedAt, 'Launch')]
    const before = structuredClone(captures)
    const forward = suggestGroupingProposals({ captures, generatedAt })
    const reverse = suggestGroupingProposals({ captures: [...captures].reverse(), generatedAt })
    expect(forward).toEqual(reverse)
    expect(captures).toEqual(before)
  })
})
