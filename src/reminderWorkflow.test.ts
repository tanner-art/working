import { describe, expect, it } from 'vitest'
import type { ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { dailyLogReminderProjection, specificReminderProjection } from './reminderProjection'
import { resolveReminderInState, setReminderDeliveryState } from './reminderWorkflow'

const target = (): ThoughtObject => ({ id: 'idea:target', kind: 'idea', originalContent: 'Launch concept', source: 'text', createdAt: '2026-09-27T08:00:00Z', confidence: .9, status: 'confirmed', interpretation: { summary: 'Launch concept', suggestedKind: 'idea', rationale: 'Confirmed idea' }, metadata: {}, relationships: [], history: [] })
const reminder = (): ThoughtObject => ({ id: 'capture:reminder', kind: 'reminder', originalContent: 'Remind me about launch', source: 'text', createdAt: '2026-09-27T08:01:00Z', confidence: .5, status: 'review', interpretation: { summary: 'Launch reminder', suggestedKind: 'reminder', rationale: 'Timing needs review' }, metadata: {}, relationships: [], history: [] })
const state = () => legacyUiProjection(migrateLegacyState({ objects: [target(), reminder()], canvas: [] }))

describe('Reminder workflow', () => {
  it('records Specific from Review with source/target evidence and makes it visibly due after reload', () => {
    const resolved = resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'specific', dueAt: '2026-09-27T09:00:00.000Z' }, '2026-09-27T08:02:00.000Z')
    expect(resolved.objects.find(item => item.id === 'capture:reminder')?.status).toBe('confirmed')
    const reloaded = legacyUiProjection(resolved.model!)
    const due = specificReminderProjection(reloaded.model!, new Date('2026-09-27T10:00:00Z'))
    expect(due).toMatchObject([{ due: true, fallback: 'in-app-only', target: { id: 'idea:target' }, instruction: { captureIds: ['capture:capture:reminder'], mode: 'specific', deliveryState: 'active' } }])
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
    const dismissed = setReminderDeliveryState(resolveReminderInState(state(), 'capture:reminder', { targetId: 'idea:target', mode: 'daily-log' }), 'reminder:capture:reminder', 'dismissed', '2026-09-27T08:04:00.000Z')
    expect(dailyLogReminderProjection(dismissed.model!)).toEqual([])
    expect(dismissed.model!.reminderInstructions?.[0]).toMatchObject({ deliveryState: 'dismissed', dismissedAt: '2026-09-27T08:04:00.000Z' })
  })
})
