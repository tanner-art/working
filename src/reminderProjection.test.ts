import { describe, expect, it } from 'vitest'
import { dailyLogReminderProjection, specificReminderProjection } from './reminderProjection'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { resolveReminderInState } from './reminderWorkflow'
import type { ThoughtObject } from './domain'

const item = (id: string, kind: ThoughtObject['kind'], status: ThoughtObject['status']): ThoughtObject => ({ id, kind, status, originalContent: id, source: 'text', createdAt: '2026-09-27T08:00:00Z', confidence: .8, interpretation: { summary: id, suggestedKind: kind, rationale: 'fixture' }, metadata: {}, relationships: [], history: [] })

describe('Reminder projections', () => {
  it('separates due Specific from Daily log and never represents delivery as available', () => {
    let state = legacyUiProjection(migrateLegacyState({ objects: [item('target', 'idea', 'confirmed'), item('specific', 'reminder', 'review'), item('daily', 'reminder', 'review')], canvas: [] }))
    state = resolveReminderInState(state, 'specific', { targetId: 'target', mode: 'specific', dueAt: '2026-09-27T09:00:00.000Z' })
    state = resolveReminderInState(state, 'daily', { targetId: 'target', mode: 'daily-log' })
    expect(specificReminderProjection(state.model!, new Date('2026-09-27T10:00:00Z'))).toMatchObject([{ due: true, fallback: 'in-app-only' }])
    expect(dailyLogReminderProjection(state.model!)).toMatchObject([{ due: false, fallback: 'in-app-only' }])
  })
})
