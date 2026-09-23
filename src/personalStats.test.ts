import { describe, expect, it } from 'vitest'
import type { ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject, setObjectStatus } from './objectWorkflow'
import { calculatePersonalStats } from './personalStats'

const base = (patch: Partial<ThoughtObject>): ThoughtObject => ({
  id: 'idea', kind: 'idea', originalContent: 'A thought', source: 'text', createdAt: '2026-09-20T12:00:00.000Z',
  interpretation: { summary: 'A thought', suggestedKind: 'idea', rationale: 'Explicit idea' }, confidence: .9,
  relationships: [], history: [{ at: '2026-09-20T12:00:00.000Z', event: 'Captured' }], status: 'confirmed', metadata: {}, ...patch,
})

describe('private personal statistics', () => {
  it('calculates private account-owner metrics from canonical current meaning', () => {
    const action = base({
      id: 'done', kind: 'action', originalContent: 'Finish report', createdAt: '2026-09-01T12:00:00.000Z',
      interpretation: { summary: 'Finish report', suggestedKind: 'action', rationale: 'Explicit work' }, status: 'review',
    })
    const review = base({
      id: 'review', kind: 'action', originalContent: 'Maybe call', createdAt: '2026-09-21T12:00:00.000Z', confidence: .4, status: 'review',
      interpretation: { summary: 'Maybe call', suggestedKind: 'action', rationale: 'Ambiguous work' },
    })
    let model = migrateLegacyState({ objects: [base({}), action, review], canvas: [{ id: 'node', type: 'text', x: 0, y: 0 }] })
    let view = legacyUiProjection(model)
    view.objects[1] = confirmObject(view.objects[1])
    model = reconcileLegacyUi(view)
    view = legacyUiProjection(model)
    view.objects[1] = setObjectStatus(view.objects[1], 'complete')
    model = reconcileLegacyUi(view)
    const stats = calculatePersonalStats(model, new Date('2026-09-23T12:00:00.000Z'))

    expect(stats.privacy).toEqual({ audience: 'account-owner', sharing: 'disabled', rankings: 'not-calculated' })
    expect(stats.totals).toEqual({ captures: 3, currentObjects: 2, completedObjects: 1, pendingReview: 1, canvasElements: 1 })
    expect(stats.activity).toEqual({ capturesLast7Days: 2, capturesLast30Days: 3 })
    expect(stats.actions).toEqual({ confirmed: 1, completed: 1, completionPercent: 100 })
    expect(stats.byKind).toMatchObject({ idea: 1, action: 1, commitment: 0 })
    expect(stats.provenance.captureIds).toEqual(['capture:idea', 'capture:done', 'capture:review'])
    expect(stats.provenance.semanticObjectIds).toEqual(['idea', 'done'])
    expect(stats).not.toHaveProperty('leaderboard')
  })

  it('uses null instead of inventing a completion rate when no confirmed actions exist', () => {
    const stats = calculatePersonalStats(migrateLegacyState({ objects: [base({})], canvas: [] }), new Date('2026-09-23T12:00:00.000Z'))
    expect(stats.actions).toEqual({ confirmed: 0, completed: 0, completionPercent: null })
  })

  it('rejects malformed models and invalid calculation dates', () => {
    expect(() => calculatePersonalStats({} as never)).toThrow('valid saved model')
    expect(() => calculatePersonalStats(migrateLegacyState({ objects: [], canvas: [] }), new Date('invalid'))).toThrow('valid saved model')
  })
})
