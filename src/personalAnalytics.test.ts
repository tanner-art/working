import { describe, expect, it } from 'vitest'
import { calculatePersonalStatistics } from './personalAnalytics'

describe('personal statistics', () => {
  it('returns honest empty-set values and does not opt into ranking', () => {
    expect(calculatePersonalStatistics()).toEqual({
      thoughtCount: 0,
      averageThoughtCharacterCount: null,
      commitmentCount: 0,
      completionRate: null,
      averageCompletionTimeMs: null,
      crossUserRankingOptIn: false,
    })
  })

  it('counts thoughts and commitments from explicit local records', () => {
    expect(calculatePersonalStatistics({
      thoughts: [
        { originalContent: 'hello' },
        { originalContent: '🙂🙂' },
        { originalContent: '' },
        { originalContent: 42 },
      ],
      commitments: [
        { status: 'complete' },
        { status: 'inbox' },
      ],
    })).toMatchObject({
      thoughtCount: 3,
      averageThoughtCharacterCount: 7 / 3,
      commitmentCount: 2,
      completionRate: 0.5,
    })
  })

  it('treats incomplete commitments as incomplete and averages valid completion intervals', () => {
    expect(calculatePersonalStatistics({
      commitments: [
        { status: 'complete', createdAt: '2026-01-01T00:00:00Z', completedAt: '2026-01-01T01:00:00Z' },
        { status: 'inbox', createdAt: '2026-01-01T00:00:00Z', completedAt: '2026-01-01T02:00:00Z' },
        { status: 'inbox', createdAt: '2026-01-01T00:00:00Z' },
      ],
    })).toMatchObject({ commitmentCount: 3, completionRate: 1 / 3, averageCompletionTimeMs: 3_600_000 })
  })

  it('excludes malformed records and invalid timestamps without inventing values', () => {
    expect(calculatePersonalStatistics({
      thoughts: [
        { originalContent: 'valid' },
        { originalContent: null },
        null as unknown as { originalContent: string },
      ],
      commitments: [
        { status: 'complete', createdAt: 'not-a-date', completedAt: '2026-01-01T01:00:00Z' },
        { status: 'complete', createdAt: '2026-01-01T02:00:00Z', completedAt: '2026-01-01T01:00:00Z' },
      ],
    })).toMatchObject({
      thoughtCount: 1,
      commitmentCount: 2,
      completionRate: 1,
      averageCompletionTimeMs: null,
    })
  })

  it('requires the explicit true opt-in and remains deterministic for input order', () => {
    const input = {
      thoughts: [{ originalContent: 'a' }, { originalContent: 'abcd' }],
      commitments: [{ status: 'complete', createdAt: '2026-01-01T00:00:00Z', completedAt: '2026-01-01T00:00:02Z' }],
    }
    expect(calculatePersonalStatistics(input)).toEqual(calculatePersonalStatistics({
      thoughts: [...input.thoughts].reverse(),
      commitments: [...input.commitments].reverse(),
    }))
    expect(calculatePersonalStatistics({ ...input, crossUserRankingOptIn: 'yes' as unknown as boolean }).crossUserRankingOptIn).toBe(false)
    expect(calculatePersonalStatistics({ ...input, crossUserRankingOptIn: true }).crossUserRankingOptIn).toBe(true)
  })
})
