import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, ThoughtObject } from './domain'
import { scheduleStagedAction, setStagedActionPriority, stageAction } from './actionStaging'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { hasStagedActionResolution, reverseObject, setObjectKind, setObjectStatus, updateObject } from './objectWorkflow'
import { confirmedActions } from './objectWorkflow'
import { accountData } from './accountStorage'
import { defaultSettings } from './settings'
import { disabledDelivery } from './digestDelivery'
import { loadStateResult, saveState } from './store'

afterEach(() => vi.unstubAllGlobals())

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

  it('loads, schedules, saves and reloads a staged Action without losing local session ownership', () => {
    let raw: string | null = JSON.stringify(migrateLegacyState({ objects: [reviewAction()], canvas: [] }))
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const loaded = loadStateResult().state
    const stagedState = { ...loaded, objects: [stageAction(loaded.objects[0])] }
    expect(saveState(stagedState)).toBeUndefined()
    const beforeSchedule = loadStateResult().state
    const scheduled = scheduleStagedAction(beforeSchedule, 'action-1', '2026-10-12T09:00:00.000Z', 'UTC')
    expect(isPersistedState(scheduled.model)).toBe(true)
    expect(saveState(scheduled)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(reloaded.state.model?.stagedActions).toMatchObject([{ status: 'scheduled', objectId: 'action-1' }])
    expect(reloaded.state.model?.calendarEvents).toMatchObject([{ status: 'scheduled', objectIds: ['action-1'] }])
    expect(reloaded.state.model?.temporalHistory).toHaveLength(1)
  })

  it('completes, archives or withdraws a staged Action without manufacturing execution confirmation', () => {
    for (const status of ['complete', 'archived', 'review'] as const) {
      let raw: string | null = JSON.stringify(migrateLegacyState({ objects: [reviewAction()], canvas: [] }))
      vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
      const loaded = loadStateResult().state
      expect(saveState({ ...loaded, objects: [stageAction(loaded.objects[0])] })).toBeUndefined()
      const stagedState = loadStateResult().state
      const object = stagedState.objects[0]
      expect(hasStagedActionResolution(object)).toBe(true)
      const changed = status === 'review' ? reverseObject(object) : updateObject(object, setObjectStatus(object, status))
      const next = { ...stagedState, objects: [changed] }
      expect(next.objects[0].status).toBe(status)
      expect(saveState(next)).toBeUndefined()
      const reloaded = loadStateResult()
      expect(reloaded.error).toBeUndefined()
      expect(reloaded.state.objects[0].status).toBe(status)
      expect(reloaded.state.model?.semanticObjects.find(item => item.id === object.id)?.status).toBe(status)
      expect(reloaded.state.model?.stagedActions).toMatchObject([{ status: status === 'review' ? 'reversed' : 'staged' }])
      expect(confirmedActions(reloaded.state.objects)).toEqual([])
      expect(hasStagedActionResolution(reloaded.state.objects[0])).toBe(status !== 'review')
      vi.unstubAllGlobals()
    }
  })

  it('keeps a separately confirmed CalendarEvent fixed when its staged Action is completed', () => {
    const scheduled = scheduleStagedAction(staged(), 'action-1', '2026-10-12T09:00:00.000Z', 'UTC')
    const completed = { ...scheduled, objects: [updateObject(scheduled.objects[0], setObjectStatus(scheduled.objects[0], 'complete'))] }
    const model = reconcileLegacyUi(completed)
    expect(model.semanticObjects.find(item => item.id === 'action-1')?.status).toBe('complete')
    expect(model.calendarEvents).toMatchObject([{ status: 'scheduled', objectIds: ['action-1'] }])
    expect(model.stagedActions).toMatchObject([{ status: 'scheduled' }])
    expect(isPersistedState(model)).toBe(true)
  })
})
