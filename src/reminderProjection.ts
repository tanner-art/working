import type { PersistedState, ResolvedReminderInstruction, SemanticObject } from './domain'

export type ActiveReminderProjection = Readonly<{
  instruction: ResolvedReminderInstruction
  target: SemanticObject
  due: boolean
  fallback: 'in-app-only'
}>

function active(model: PersistedState, mode: ResolvedReminderInstruction['mode'], now: Date): ActiveReminderProjection[] {
  return (model.reminderInstructions ?? []).flatMap(instruction => {
    if (instruction.mode !== mode || instruction.deliveryState !== 'active') return []
    const target = model.semanticObjects.find(value => value.id === instruction.targetId)
    if (!target) return []
    return [{ instruction, target, due: mode === 'specific' && Date.parse(instruction.dueAt!) <= now.getTime(), fallback: 'in-app-only' as const }]
  })
}

/** Specific reminders remain visible in-app when browser/system delivery is unavailable. */
export function specificReminderProjection(model: PersistedState, now = new Date()): ActiveReminderProjection[] {
  return active(model, 'specific', now).sort((left, right) => left.instruction.dueAt!.localeCompare(right.instruction.dueAt!))
}

/** Daily-log reminders intentionally stay visible until explicitly handled or dismissed. */
export function dailyLogReminderProjection(model: PersistedState, now = new Date()): ActiveReminderProjection[] {
  return active(model, 'daily-log', now).sort((left, right) => left.instruction.createdAt.localeCompare(right.instruction.createdAt))
}
