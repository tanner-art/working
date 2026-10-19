import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, ThoughtObject } from './domain'
import { scheduleStagedAction, setStagedActionPriority, stageAction } from './actionStaging'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { reverseObject, setObjectKind } from './objectWorkflow'
import { confirmedActions } from './objectWorkflow'
import { accountData } from './accountStorage'
import { defaultSettings } from './settings'
import { disabledDelivery } from './digestDelivery'
import { loadStateResult, saveState, serializeState } from './store'

const reviewAction = (): ThoughtObject => ({ id: 'action-1', kind: 'action', status: 'review', originalContent: 'Ship the repair', source: 'text', createdAt: '2026-09-27T08:00:00.000Z', confidence: .8, interpretation: { summary: 'Ship the repair', suggestedKind: 'action', rationale: 'Explicit work' }, metadata: {}, relationships: [], history: [{ at: '2026-09-27T08:00:00.000Z', event: 'Captured' }] })
const staged = (): AppState => {
  const state = legacyUiProjection(migrateLegacyState({ objects: [reviewAction()], canvas: [] }))
  return { ...state, objects: [stageAction({ ...state.objects[0], kind: 'action' }, 3)] }
}

describe('Action staging lifecycle', () => {
  afterEach(() => vi.unstubAllGlobals())

  function localStage() {
    let raw: string | null = JSON.stringify({ objects: [reviewAction()], canvas: [] })
    const storage = { getItem: () => raw, setItem: vi.fn((_key: string, value: string) => { raw = value }) }
    vi.stubGlobal('localStorage', storage)
    let state = loadStateResult().state
    expect(saveState(state)).toBeUndefined()
    state = { ...state, objects: [stageAction(state.objects[0])] }
    expect(saveState(state)).toBeUndefined()
    state = setStagedActionPriority(state, 'action-1', 5)
    expect(saveState(state)).toBeUndefined()
    return { state, storage }
  }

  it.each([false, true])('saves scheduling and reversal with prior revisions (reload first: %s)', reload => {
    const { state: initial } = localStage()
    const state = reload ? loadStateResult().state : initial
    const before = serializeState(state)
    const scheduled = scheduleStagedAction(state, 'action-1', '2026-10-22T14:00:00.000Z', 'UTC')
    // Render consumers reconcile directly; persistence must produce the same evidence.
    expect(reconcileLegacyUi(scheduled)).toEqual(serializeState(scheduled))
    expect(saveState(scheduled)).toBeUndefined()
    expect(saveState(scheduled)).toBeUndefined()
    const loaded = loadStateResult()
    expect(loaded.error).toBeUndefined()
    expect(loaded.state.model?.captures).toEqual(before.captures)
    expect(loaded.state.model?.interpretations.slice(0, before.interpretations.length)).toEqual(before.interpretations)
    expect(loaded.state.model?.calendarEvents).toHaveLength(1)
    expect(loaded.state.model?.temporalHistory).toHaveLength(1)
    expect(loaded.state.model?.stagedActions).toMatchObject([{ priority: 5, status: 'scheduled' }])
    const reversed = { ...scheduled, objects: scheduled.objects.map(object => reverseObject(object)) }
    expect(saveState(reversed)).toBeUndefined()
    const after = loadStateResult()
    expect(after.error).toBeUndefined()
    expect(after.state.model?.calendarEvents).toMatchObject([{ status: 'cancelled' }])
    expect(after.state.model?.temporalHistory?.map(entry => entry.decision)).toEqual(['confirmed', 'reversed'])
    expect(after.state.model?.captures).toEqual(before.captures)
  })

  it.each(['before scheduling', 'after scheduling'] as const)('rejects a concurrent write %s without overwriting it', timing => {
    const { state, storage } = localStage()
    const other = loadStateResult().state
    const otherWrite = () => expect(saveState(setStagedActionPriority(other, 'action-1', 1))).toBeUndefined()
    if (timing === 'before scheduling') otherWrite()
    const scheduled = scheduleStagedAction(state, 'action-1', '2026-10-22T14:00:00.000Z', 'UTC')
    if (timing === 'after scheduling') otherWrite()
    const preserved = storage.getItem()
    expect(saveState(scheduled)).toContain('Stored data changed')
    expect(storage.getItem()).toBe(preserved)
  })

  it('retries a failed scheduling write without duplicating an event or confirmation', () => {
    const { state, storage } = localStage()
    const scheduled = scheduleStagedAction(state, 'action-1', '2026-10-22T14:00:00.000Z', 'UTC')
    const preserved = storage.getItem()
    storage.setItem.mockImplementationOnce(() => { throw new Error('Quota exceeded') })
    expect(saveState(scheduled)).toContain('only in this open tab')
    expect(storage.getItem()).toBe(preserved)
    expect(saveState(scheduled)).toBeUndefined()
    expect(loadStateResult().state.model?.calendarEvents).toHaveLength(1)
    expect(loadStateResult().state.model?.temporalHistory).toHaveLength(1)
  })

  it('does not grant a storage session to an unregistered model', () => {
    const { state, storage } = localStage()
    const detached = structuredClone(state)
    const scheduled = scheduleStagedAction(detached, 'action-1', '2026-10-22T14:00:00.000Z', 'UTC')
    const preserved = storage.getItem()
    expect(saveState(scheduled)).toContain('not loaded by this session')
    expect(storage.getItem()).toBe(preserved)
  })

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
