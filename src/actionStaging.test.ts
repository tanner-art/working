import { describe, expect, it, vi } from 'vitest'
import type { AppState, ThoughtObject } from './domain'
import { scheduleStagedAction, setStagedActionPriority, stageAction } from './actionStaging'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { reverseObject, setObjectKind } from './objectWorkflow'
import { confirmedActions } from './objectWorkflow'
import { accountData } from './accountStorage'
import { defaultSettings } from './settings'
import { disabledDelivery } from './digestDelivery'

const reviewAction = (): ThoughtObject => ({ id: 'action-1', kind: 'action', status: 'review', originalContent: 'Ship the repair', source: 'text', createdAt: '2026-09-27T08:00:00.000Z', confidence: .8, interpretation: { summary: 'Ship the repair', suggestedKind: 'action', rationale: 'Explicit work' }, metadata: {}, relationships: [], history: [{ at: '2026-09-27T08:00:00.000Z', event: 'Captured' }] })
const staged = (): AppState => {
  const state = legacyUiProjection(migrateLegacyState({ objects: [reviewAction()], canvas: [] }))
  return { ...state, objects: [stageAction({ ...state.objects[0], kind: 'action' }, 3)] }
}

describe('Action staging lifecycle', () => {
  it('persists a user-selected priority through local serialization and exposes no execution eligibility while staged', () => {
    const state = setStagedActionPriority(staged(), 'action-1', 5)
    const model = reconcileLegacyUi(state)
    expect(model.stagedActions).toMatchObject([{ objectId: 'action-1', priority: 5, status: 'staged' }])
    expect(model.stagedActions?.[0].schedule).toBeUndefined()
    expect(model.calendarEvents).toEqual([])
    expect(model.semanticObjects).toHaveLength(1)
    expect(confirmedActions(state.objects)).toEqual([])
    expect(model.interpretations.at(-1)?.legacy.history.at(-1)?.actionPriority).toEqual({ priority: 5, source: 'schedule-priority-selection' })
    expect(isPersistedState(structuredClone(model))).toBe(true)
    expect(accountData(state, defaultSettings, disabledDelivery).model.stagedActions).toMatchObject([{ priority: 5, status: 'staged' }])
  })

  it('creates a separate confirmed CalendarEvent only on scheduling, then reverses its projection without losing audit', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'calendar-event-1' })
    let state = scheduleStagedAction(setStagedActionPriority(staged(), 'action-1', 4), 'action-1', '2026-09-28T09:00:00.000Z', 'UTC')
    let model = reconcileLegacyUi(state)
    expect(model.stagedActions).toMatchObject([{ priority: 4, status: 'scheduled', schedule: { eventId: 'calendar-event-1' } }])
    expect(model.calendarEvents).toMatchObject([{ id: 'calendar-event-1', status: 'scheduled' }])
    expect(model.temporalHistory).toHaveLength(1)
    state = { ...state, objects: [reverseObject(state.objects[0])] }
    model = reconcileLegacyUi(state)
    expect(model.stagedActions).toMatchObject([{ status: 'reversed' }])
    expect(model.calendarEvents).toMatchObject([{ id: 'calendar-event-1', status: 'cancelled' }])
    expect(model.temporalHistory?.map(entry => entry.decision)).toEqual(['confirmed', 'reversed'])
    expect(isPersistedState(model)).toBe(true)
  })

  it('reclassifies Action evidence without leaving a schedulable stage or scheduled CalendarEvent', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'calendar-event-2' })
    let state = scheduleStagedAction(staged(), 'action-1', '2026-09-28T09:00:00.000Z', 'UTC')
    state = { ...state, objects: [setObjectKind(state.objects[0], 'idea')] }
    const model = reconcileLegacyUi(state)
    expect(model.stagedActions).toEqual([])
    expect(model.calendarEvents).toMatchObject([{ id: 'calendar-event-2', status: 'cancelled' }])
    expect(() => scheduleStagedAction(state, 'action-1', '2026-09-29T09:00:00.000Z', 'UTC')).toThrow('no longer awaiting')
    expect(isPersistedState(model)).toBe(true)
  })
})
