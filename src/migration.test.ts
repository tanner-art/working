import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, ThoughtObject } from './domain'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject, setObjectKind, setObjectStatus, updateObject } from './objectWorkflow'
import { loadStateResult, makeObject, saveState } from './store'
import { interpret } from './interpreter'

const key = 'thoughtflow-state-v1'
const thought = (patch: Partial<ThoughtObject> = {}): ThoughtObject => ({
  id: 'original', originalContent: '  My exact expression\n第二行  ', source: 'voice', createdAt: '2026-09-13T10:00:00Z',
  context: 'As captured', kind: 'idea', confidence: .73, status: 'review',
  interpretation: { summary: 'Reading', suggestedKind: 'idea', rationale: 'Original reasoning', suggestedProject: 'Possibility' },
  metadata: {}, history: [{ at: '2026-09-13T10:00:00Z', event: 'Captured' }], relationships: [], ...patch
})
const legacy = (objects = [thought()]): AppState => ({ objects, canvas: [
  { id: 'text', type: 'text', text: 'Untouched canvas', x: -12.5, y: 8, width: 150 },
  { id: 'arrow', type: 'arrow', fromId: 'text', toId: 'missing-historical-endpoint', x: 0, y: 0 }
] })
function storage(initial: string | null) {
  let raw = initial
  const setItem = vi.fn((_key: string, value: string) => { raw = value })
  vi.stubGlobal('localStorage', { getItem: () => raw, setItem })
  return { raw: () => raw, replace: (value: string) => { raw = value }, setItem }
}
afterEach(() => vi.unstubAllGlobals())

describe('TASK-002 migration', () => {
  it('roundtrips exact captures, IDs, canvas, confidence, rationale and relationship evidence', () => {
    const original = legacy([thought({ relationships: [{ type: 'belongs_to', targetId: 'missing-old-object' }] })])
    const before = structuredClone(original)
    const model = migrateLegacyState(original)
    const decoded = JSON.parse(JSON.stringify(model))
    expect(isPersistedState(decoded)).toBe(true)
    expect(legacyUiProjection(decoded).objects).toEqual(original.objects)
    expect(decoded.canvas).toEqual(original.canvas)
    expect(decoded.captures[0]).toMatchObject({ originalContent: original.objects[0].originalContent, evidence: 'text-only' })
    expect(decoded.semanticObjects[0]).not.toHaveProperty('originalContent')
    expect(decoded.relationships[0]).toMatchObject({ sourceId: 'original', targetId: 'missing-old-object', scope: 'semantic' })
    expect(reconcileLegacyUi(legacyUiProjection(decoded))).toEqual(decoded)
    expect(original).toEqual(before)
  })

  it('keeps ambiguous reminders and legacy obligations as review evidence, without inventing a target or event', () => {
    const model = migrateLegacyState(legacy([
      thought({ id: 'r', kind: 'reminder', status: 'confirmed', metadata: { deadline: 'tomorrow' } }),
      thought({ id: 'c', kind: 'commitment', status: 'confirmed' }),
      thought({ id: 'a', kind: 'action', status: 'confirmed', confidence: 1 })
    ]))
    expect(model.semanticObjects).toEqual([])
    expect(model.calendarEvents).toEqual([])
    expect(model.interpretations[0].proposedReminder?.trigger.legacyDate).toBe('tomorrow')
    expect(model.interpretations[2].proposedAction).toBeDefined()
    expect(legacyUiProjection(model).objects.every(o => o.status === 'review')).toBe(true)
    expect(model.interpretations.every(i => i.legacy.status === 'confirmed')).toBe(true)
  })

  it('attaches a pending instruction to a reviewed target without changing original evidence or delivering it', () => {
    const initial = migrateLegacyState(legacy([thought({ kind: 'reminder' })]))
    const view = legacyUiProjection(initial)
    view.objects[0] = confirmObject(setObjectKind(view.objects[0], 'idea'))
    const result = reconcileLegacyUi(view)
    expect(result.semanticObjects[0]).toMatchObject({ id: 'original', kind: 'idea', reminders: [{ deliveryState: 'needs-review' }] })
    expect(result.interpretations).toHaveLength(2)
    expect(result.interpretations[0]).toEqual(initial.interpretations[0])
    expect(result.captures).toEqual(initial.captures)
    expect(isPersistedState(JSON.parse(JSON.stringify(result)))).toBe(true)
  })

  it('versions confirmation and reversal without replacing rationale, confidence or capture', () => {
    const initial = migrateLegacyState(legacy([thought({ kind: 'action' })]))
    const view = legacyUiProjection(initial)
    view.objects[0] = confirmObject(view.objects[0])
    const confirmed = reconcileLegacyUi(view)
    expect(confirmed.semanticObjects[0].kind).toBe('action')
    expect(confirmed.interpretations[1]).toMatchObject({ version: 2, confidence: .73, rationale: 'Original reasoning', confirmation: { transition: 'action' } })
    const revised = legacyUiProjection(confirmed)
    revised.objects[0] = setObjectKind(revised.objects[0], 'idea')
    const result = reconcileLegacyUi(revised)
    expect(result.interpretations).toHaveLength(3)
    expect(result.interpretations.slice(0, 2)).toEqual(confirmed.interpretations)
    expect(result.captures).toEqual(initial.captures)
    expect(isPersistedState(JSON.parse(JSON.stringify(result)))).toBe(true)
  })

  it('preserves confirmed semantic identity through completion and archival', () => {
    let view = legacyUiProjection(migrateLegacyState(legacy([thought({ kind: 'action' })])))
    view.objects[0] = confirmObject(view.objects[0])
    view = legacyUiProjection(reconcileLegacyUi(view))
    for (const status of ['complete', 'archived'] as const) {
      view.objects[0] = setObjectStatus(view.objects[0], status)
      const model = reconcileLegacyUi(view)
      expect(model.semanticObjects[0]).toMatchObject({ id: 'original', kind: 'action', status })
      expect(model.interpretations.at(-1)?.confirmation).toBeDefined()
      view = legacyUiProjection(model)
    }
  })

  it.each(['action', 'commitment'] as const)('keeps unresolved %s in Review through editor helper chains and persistence', kind => {
    for (const initialStatus of ['review', 'inbox'] as const) {
      for (const status of ['confirmed', 'complete', 'archived', 'inbox'] as const) {
        const original = thought({ kind, status: initialStatus })
        const before = structuredClone(original)
        const baseline = migrateLegacyState(legacy([original]))
        // ObjectPanel Complete/Archive -> onSave -> updateObject, plus direct Status dropdown saves.
        for (const draft of [setObjectStatus(original, status), { ...original, status },
          setObjectStatus({ ...original, status: 'confirmed' }, status)]) {
          const updated = updateObject(original, draft)
          expect(updated.status).toBe('review')
          expect(updated.originalContent).toBe(original.originalContent)
          expect(updated.interpretation).toEqual(original.interpretation)
          expect(updated.confidence).toBe(original.confidence)
          expect(updated.history.slice(0, original.history.length)).toEqual(original.history)
          const model = reconcileLegacyUi({ ...legacyUiProjection(baseline), objects: [updated] })
          expect(model.captures).toEqual(baseline.captures)
          expect(model.interpretations[0]).toEqual(baseline.interpretations[0])
          expect(model.semanticObjects).toEqual([])
          expect(model.interpretations.at(-1)?.confirmation).toBeUndefined()
          expect(legacyUiProjection(JSON.parse(JSON.stringify(model))).objects[0].status).toBe('review')
          expect(isPersistedState(model)).toBe(true)
        }
        expect(setObjectStatus(original, status).status).toBe('review')
        expect(original).toEqual(before)
      }
    }
  })

  it.each(['action', 'commitment'] as const)('does not hide unconfirmed terminal %s evidence on projection', kind => {
    for (const status of ['complete', 'archived'] as const) {
      const model = migrateLegacyState(legacy([thought({ kind, status })]))
      expect(model.interpretations[0].legacy.status).toBe(status)
      expect(legacyUiProjection(model).objects[0].status).toBe('review')
      expect(reconcileLegacyUi(legacyUiProjection(model))).toEqual(model)
    }
  })

  it.each(['action', 'commitment'] as const)('allows dedicated confirmed %s through the actual Complete and Archive chain', kind => {
    let view = legacyUiProjection(migrateLegacyState(legacy([thought({ kind })])))
    view.objects[0] = confirmObject(view.objects[0])
    view = legacyUiProjection(reconcileLegacyUi(view))
    for (const status of ['complete', 'archived'] as const) {
      const original = view.objects[0]
      view.objects[0] = updateObject(original, setObjectStatus(original, status))
      expect(view.objects[0].status).toBe(status)
      const model = reconcileLegacyUi(view)
      expect(model.semanticObjects[0]).toMatchObject({ kind, status })
      expect(model.interpretations.at(-1)?.confirmation?.transition).toBe(kind)
      view = legacyUiProjection(model)
    }
    const original = setObjectKind(view.objects[0], kind)
    expect(updateObject(original, setObjectStatus(original, 'complete')).status).toBe('review')
  })

  it('separates a confirmed unscheduled commitment from calendar event and fixed deadline', () => {
    const view = legacyUiProjection(migrateLegacyState(legacy([thought({ kind: 'commitment', metadata: { deadline: 'Friday' } })])))
    view.objects[0] = confirmObject(view.objects[0])
    const model = reconcileLegacyUi(view)
    expect(model.semanticObjects[0]).toMatchObject({ kind: 'commitment', metadata: {} })
    expect(model.calendarEvents).toEqual([])
    model.calendarEvents.push({ id: 'event', title: 'Separate meeting', startsAt: '2026-09-14T10:00:00Z', temporalContext: 'UTC',
      objectIds: ['original'], captureIds: ['capture:original'], status: 'scheduled' })
    expect(isPersistedState(model)).toBe(true)
    expect(reconcileLegacyUi(legacyUiProjection(model)).calendarEvents).toEqual(model.calendarEvents)
  })

  it('retains every interpretation across sequential saves from the unchanged React model snapshot', () => {
    const db = storage(JSON.stringify(legacy()))
    const state = loadStateResult().state
    expect(saveState(state)).toBeUndefined()
    state.objects[0] = confirmObject(state.objects[0], 'project')
    expect(saveState(state)).toBeUndefined()
    state.objects[0] = updateObject(state.objects[0], { ...state.objects[0], context: 'Later context' })
    expect(saveState(state)).toBeUndefined()
    const saved = JSON.parse(db.raw()!)
    expect(saved.interpretations).toHaveLength(3)
    expect(saved.captures[0].context).toBe('As captured')
    expect(saved.interpretations[2].legacy.context).toBe('Later context')
    expect(loadStateResult().error).toBeUndefined()
    expect(saveState(state)).toBeUndefined()
    expect(JSON.parse(db.raw()!).interpretations).toHaveLength(3)
  })

  it('persists newly captured data in the real schema and leaves inferred work proposed', () => {
    const db = storage(null)
    const state = loadStateResult().state
    const result = interpret('Send the draft')
    state.objects.push(makeObject({ ...result, originalContent: 'Send the draft', source: 'text' }))
    expect(saveState(state)).toBeUndefined()
    const saved = JSON.parse(db.raw()!)
    expect(saved.schemaVersion).toBe(2)
    expect(saved).not.toHaveProperty('objects')
    expect(saved.captures.at(-1).originalContent).toBe('Send the draft')
    expect(saved.semanticObjects.some((o: { kind: string }) => o.kind === 'action')).toBe(false)
    expect(loadStateResult().error).toBeUndefined()
  })

  it.each(['bad json', JSON.stringify({ schemaVersion: 99, objects: [], canvas: [] }),
    JSON.stringify(legacy([thought(), thought()])), JSON.stringify({ ...legacy(), unknownPayload: 'retain me' })])(
    'does not overwrite invalid, unsupported or ambiguous input: %s', raw => {
      const db = storage(raw)
      const result = loadStateResult()
      expect(result.error).toContain('left untouched')
      expect(saveState(result.state)).toBeTruthy()
      expect(db.raw()).toBe(raw)
      expect(db.setItem).not.toHaveBeenCalled()
    })

  it('blocks source mutation, history truncation, deletion, and damaged references without overwriting', () => {
    const db = storage(JSON.stringify(legacy()))
    const state = loadStateResult().state
    expect(saveState(state)).toBeUndefined()
    const raw = db.raw()
    for (const change of [
      (s: AppState) => { s.objects[0].originalContent = 'overwrite' },
      (s: AppState) => { s.objects[0].history = [] },
      (s: AppState) => { s.objects = [] }
    ]) {
      // Use the registered model identity, just as React object spreads do.
      const changed = { ...state, objects: structuredClone(state.objects) }
      change(changed)
      expect(saveState(changed)).toBeTruthy()
      expect(db.raw()).toBe(raw)
    }
    const damaged = JSON.parse(raw!)
    damaged.interpretations[0].captureIds = ['absent']
    db.replace(JSON.stringify(damaged))
    expect(loadStateResult().error).toBeTruthy()
    expect(saveState(state)).toContain('left untouched')
    expect(db.raw()).toBe(JSON.stringify(damaged))
  })

  it('rejects forged semantic kind, non-finite canvas geometry, duplicate interpretation IDs and unknown schema', () => {
    const model = migrateLegacyState(legacy())
    for (const mutate of [
      (m: typeof model) => { m.semanticObjects[0].kind = 'reminder' as 'idea' },
      (m: typeof model) => { m.canvas[0].x = Infinity },
      (m: typeof model) => { m.interpretations.push(m.interpretations[0]) },
      (m: typeof model) => { m.schemaVersion = 3 as 2 }
    ]) {
      const changed = structuredClone(model)
      mutate(changed)
      expect(isPersistedState(changed)).toBe(false)
    }
  })
})
