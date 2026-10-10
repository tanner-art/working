import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { dailyLogReminderProjection, specificReminderProjection } from './reminderProjection'
import { reminderDeliveryFailureMessage } from './ReminderResolution'
import { resolveReminder, resolveReminderInState, setReminderDeliveryState } from './reminderWorkflow'
import { hasCreatedReminderInstruction, reviewObjects, reverseObject, setObjectKind, setObjectStatus, updateObject } from './objectWorkflow'
import { loadStateResult, saveState } from './store'
import { accountData, validateData } from './accountStorage'
import { defaultSettings } from './settings'
import { resolveReviewCapture } from './reviewResolution'
import { resolveCommitment } from './commitmentWorkflow'

const target = (): ThoughtObject => ({ id: 'idea:target', kind: 'idea', originalContent: 'Launch concept', source: 'text', createdAt: '2026-09-27T08:00:00Z', confidence: .9, status: 'confirmed', interpretation: { summary: 'Launch concept', suggestedKind: 'idea', rationale: 'Confirmed idea' }, metadata: {}, relationships: [], history: [] })
const reminder = (): ThoughtObject => ({ id: 'capture:reminder', kind: 'reminder', originalContent: 'Remind me about launch', source: 'text', createdAt: '2026-09-27T08:01:00Z', confidence: .5, status: 'review', interpretation: { summary: 'Launch reminder', suggestedKind: 'reminder', rationale: 'Timing needs review' }, metadata: {}, relationships: [], history: [] })
const state = () => legacyUiProjection(migrateLegacyState({ objects: [target(), reminder()], canvas: [] }))
afterEach(() => vi.unstubAllGlobals())

describe('Reminder workflow', () => {
  it.each(['active', 'handled', 'dismissed'] as const)('rejects %s Reminder reclassification without changing append-only evidence', deliveryState => {
    let current = resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' }, '2026-09-27T08:02:00.000Z')
    if (deliveryState !== 'active') current = setReminderDeliveryState(current, current.model!.reminderInstructions![0].id, deliveryState, '2026-09-27T08:03:00.000Z')
    const original = current.objects.find(item => item.id === 'capture:reminder')!
    const before = structuredClone(original)
    expect(hasCreatedReminderInstruction(original)).toBe(true)
    for (const kind of ['idea', 'action'] as const) {
      expect(() => updateObject(original, { ...original, kind })).toThrow('Its type cannot be changed')
      expect(() => setObjectKind(original, kind)).toThrow('Its type cannot be changed')
    }
    expect(original).toEqual(before)
    expect(current.model!.reminderInstructions![0].deliveryState).toBe(deliveryState)
  })

  it.each(['active', 'handled', 'dismissed'] as const)('keeps %s Reminder out of Review after Advanced Status edits', async deliveryState => {
    let current = resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' }, '2026-09-27T08:02:00.000Z')
    if (deliveryState !== 'active') current = setReminderDeliveryState(current, current.model!.reminderInstructions![0].id, deliveryState, '2026-09-27T08:03:00.000Z')
    const original = current.objects.find(item => item.id === 'capture:reminder')!
    const before = structuredClone(original)
    for (const status of ['review', 'inbox'] as const) {
      expect(setObjectStatus(original, status).status).toBe(original.status)
      const saved = updateObject(original, { ...original, status })
      expect(saved.status).toBe(original.status)
      expect(reviewObjects([saved])).toEqual([])
    }
    expect(() => reverseObject(original)).toThrow('cannot return to Review')
    expect(setObjectKind(original, 'reminder')).toBe(original)
    // Even an already-corrupt historical projection must not show a Review card or resolve again.
    const stale = { ...original, status: 'review' as const }
    expect(reviewObjects([stale])).toEqual([])
    for (const kind of ['idea', 'action', 'commitment', 'reminder'] as const) {
      await expect(resolveReviewCapture(stale, kind)).resolves.toMatchObject({ status: 'recoverable-error' })
    }
    expect(() => resolveReminder(stale, current.model!.semanticObjects, { targetId: 'idea:target', mode: 'daily-log' })).toThrow('already has a created instruction')
    expect(() => resolveReminderInState({ ...current, objects: current.objects.map(item => item.id === stale.id ? stale : item) }, stale.id,
      { targetId: 'idea:target', mode: 'daily-log' })).toThrow('already has a created instruction')
    expect(() => resolveCommitment(stale, { title: 'Launch', dependencyIds: [] })).toThrow('cannot be reclassified')
    expect(original).toEqual(before)
    expect(current.model!.reminderInstructions).toHaveLength(1)
  })

  it('rejects a stale cross-kind save before local data changes', () => {
    let raw = JSON.stringify(state().model)
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const current = resolveReminderInState(loadStateResult().state, 'capture:reminder',
      { targetId: 'idea:target', mode: 'daily-log' }, '2026-09-27T08:02:00.000Z')
    expect(saveState(current)).toBeUndefined()
    const stored = raw
    const object = current.objects.find(item => item.id === 'capture:reminder')!
    expect(() => updateObject(object, { ...object, kind: 'idea' })).toThrow('Its type cannot be changed')
    expect(raw).toBe(stored)
    expect(loadStateResult().state.model!.reminderInstructions).toHaveLength(1)
  })

  it('keeps unresolved Reminder classification editable, but permits detail edits after resolution through local and account validation', () => {
    const pending = reminder()
    expect(hasCreatedReminderInstruction(pending)).toBe(false)
    expect(setObjectKind(pending, 'idea')).toMatchObject({ kind: 'idea', status: 'review' })
    expect(updateObject(pending, { ...pending, kind: 'action' })).toMatchObject({ kind: 'action', status: 'review' })

    let raw = JSON.stringify(state().model)
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const loaded = loadStateResult().state
    const resolved = resolveReminderInState(loaded, 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' }, '2026-09-27T08:02:00.000Z')
    const edited = { ...resolved, objects: resolved.objects.map(item => item.id === 'capture:reminder'
      ? updateObject(item, { ...item, context: 'Work' }) : item) }
    expect(saveState(edited)).toBeUndefined()
    const reloaded = loadStateResult().state
    expect(reloaded.objects.find(item => item.id === 'capture:reminder')?.context).toBe('Work')
    expect(reloaded.model!.reminderInstructions).toEqual(resolved.model!.reminderInstructions)
    const account = accountData(reloaded, defaultSettings, { enabled: false })
    expect(validateData(structuredClone(account)).model.reminderInstructions).toEqual(resolved.model!.reminderInstructions)
  })

  it('records Specific from Review with source/target evidence and makes it visibly due after reload', () => {
    const resolved = resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'specific', dueAt: '2026-09-27T09:00:00.000Z' }, '2026-09-27T08:02:00.000Z')
    expect(resolved.objects.find(item => item.id === 'capture:reminder')?.status).toBe('confirmed')
    const due = specificReminderProjection(legacyUiProjection(resolved.model!).model!, new Date('2026-09-27T10:00:00Z'))
    expect(due).toMatchObject([{ due: true, fallback: 'in-app-only', target: { id: 'idea:target' }, instruction: { mode: 'specific', deliveryState: 'active' } }])
  })

  it('allows the actual Review choice to classify a non-Reminder proposal before setup', () => {
    const initial = legacyUiProjection(migrateLegacyState({ objects: [target(), { ...reminder(), kind: 'idea', interpretation: { ...reminder().interpretation, suggestedKind: 'idea' } }], canvas: [] }))
    const resolved = resolveReminderInState(initial, 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' })
    expect(resolved.model?.reminderInstructions).toHaveLength(1)
    expect(resolved.objects.find(item => item.id === 'capture:reminder')).toMatchObject({ kind: 'reminder', status: 'confirmed' })
  })

  it('keeps Daily log active across reload, then retains handled and dismissed evidence while removing active rows', () => {
    let resolved = resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' }, '2026-09-27T08:02:00.000Z')
    expect(dailyLogReminderProjection(legacyUiProjection(resolved.model!).model!)).toHaveLength(1)
    const id = resolved.model!.reminderInstructions![0].id
    resolved = setReminderDeliveryState(resolved, id, 'handled', '2026-09-27T08:03:00.000Z')
    expect(dailyLogReminderProjection(resolved.model!)).toEqual([])
    expect(resolved.model!.reminderInstructions?.[0]).toMatchObject({ deliveryState: 'handled', handledAt: '2026-09-27T08:03:00.000Z' })
    expect(resolved.objects.find(item => item.id === 'capture:reminder')?.history.at(-1)?.reminderInstruction).toMatchObject({ action: 'handled' })
    const dismissed = setReminderDeliveryState(resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' }), id, 'dismissed', '2026-09-27T08:04:00.000Z')
    expect(dailyLogReminderProjection(dismissed.model!)).toEqual([])
    expect(dismissed.model!.reminderInstructions?.[0]).toMatchObject({ deliveryState: 'dismissed', dismissedAt: '2026-09-27T08:04:00.000Z' })
  })

  it('keeps the first delivery state and turns a stale duplicate click into recoverable feedback', () => {
    const active = resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' })
    const id = active.model!.reminderInstructions![0].id
    const handled = setReminderDeliveryState(active, id, 'handled', '2026-09-27T08:03:00.000Z')
    const feedback = reminderDeliveryFailureMessage(() => setReminderDeliveryState(handled, id, 'dismissed'))
    expect(feedback).toBe('This reminder is no longer active. Refresh and try again.')
    expect(handled.model!.reminderInstructions?.[0]).toMatchObject({ deliveryState: 'handled', handledAt: '2026-09-27T08:03:00.000Z' })
    expect(dailyLogReminderProjection(handled.model!)).toEqual([])
  })

  it('keeps autosaved interpretations intact through Review resolution and delivery without a reload', () => {
    let raw = JSON.stringify(state().model)
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let current = loadStateResult().state
    const original = structuredClone(current.model!.interpretations)
    current = { ...current, objects: current.objects.map(item => item.id === 'idea:target'
      ? updateObject(item, { ...item, context: 'Launch planning' }) : item) }
    expect(saveState(current)).toBeUndefined()
    const edited = structuredClone(JSON.parse(raw).interpretations)
    expect(edited).toHaveLength(original.length + 1)

    current = resolveReminderInState(current, 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' }, '2026-09-27T08:02:00.000Z')
    expect(saveState(current)).toBeUndefined()
    const resolved = JSON.parse(raw)
    expect(resolved.interpretations.slice(0, edited.length)).toEqual(edited)
    const instructionId = resolved.reminderInstructions[0].id
    current = setReminderDeliveryState(current, instructionId, 'handled', '2026-09-27T08:03:00.000Z')
    expect(saveState(current)).toBeUndefined()
    const reloaded = loadStateResult().state
    expect(reloaded.model!.interpretations.slice(0, edited.length)).toEqual(edited)
    expect(reloaded.model!.reminderInstructions?.[0].deliveryState).toBe('handled')
    expect(dailyLogReminderProjection(reloaded.model!)).toEqual([])
  })
})
