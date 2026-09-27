import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { resolveReviewCapture } from './reviewResolution'
import { ScheduleView } from './ScheduleView'

describe('Review to Action to Schedule flow', () => {
  it('turns the dedicated Review Action gesture into a visible, non-executable Schedule item', async () => {
    const review: ThoughtObject = { id: 'review-action', kind: 'idea', status: 'review', originalContent: 'Send proposal', source: 'text', createdAt: '2026-09-27T08:00:00.000Z', confidence: .7, interpretation: { summary: 'Send proposal', suggestedKind: 'action', rationale: 'Work implied' }, metadata: {}, relationships: [], history: [] }
    const result = await resolveReviewCapture(review, 'action')
    expect(result.status).toBe('completed')
    if (result.status !== 'completed') return
    const state = legacyUiProjection(migrateLegacyState({ objects: [result.object], canvas: [] }))
    expect(state.model?.stagedActions).toMatchObject([{ objectId: 'review-action', status: 'staged', priority: 3 }])
    const markup = renderToStaticMarkup(<ScheduleView state={state} update={() => undefined} />)
    expect(markup).toContain('Send proposal')
    expect(markup).toContain('Unscheduled staged Action')
  })
})
