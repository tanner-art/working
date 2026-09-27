import type { AppState, ReminderInstructionAudit, ResolvedReminderInstruction, SemanticObject, ThoughtObject } from './domain'
import { legacyUiProjection, reconcileLegacyUi } from './migration'

export type ReminderMode = 'specific' | 'daily-log'
export type ReminderChoice = Readonly<{ targetId: string; mode: ReminderMode; dueAt?: string }>

const isIsoInstant = (value: string) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value))

function requireChoice(object: ThoughtObject, targets: readonly SemanticObject[], choice: ReminderChoice) {
  if (object.kind !== 'reminder' || object.status !== 'review') throw new Error('Only a Reminder awaiting Review can be resolved.')
  if (!targets.some(target => target.id === choice.targetId)) throw new Error('Choose an available semantic target for this reminder.')
  if (choice.mode !== 'specific' && choice.mode !== 'daily-log') throw new Error('Choose either Specific or Daily log.')
  if (choice.mode === 'specific' && (!choice.dueAt || !isIsoInstant(choice.dueAt))) throw new Error('Choose a confirmed date and time for this Specific reminder.')
  if (choice.mode === 'daily-log' && choice.dueAt !== undefined) throw new Error('Daily log reminders do not have a scheduled date or time.')
}

/**
 * Records the user's explicit Reminder choice on the preserved capture. The
 * migration layer derives the attached instruction and source interpretation
 * identity from this immutable audit event.
 */
export function resolveReminder(object: ThoughtObject, targets: readonly SemanticObject[], choice: ReminderChoice, at = new Date().toISOString()): ThoughtObject {
  requireChoice(object, targets, choice)
  const audit: ReminderInstructionAudit = {
    instructionId: `reminder:${object.id}`,
    action: 'created', targetId: choice.targetId, mode: choice.mode,
    ...(choice.mode === 'specific' ? { dueAt: choice.dueAt } : {}),
  }
  return { ...object, status: 'confirmed', history: [...object.history, { at, event: `Created ${choice.mode === 'specific' ? 'Specific' : 'Daily log'} reminder`, reminderInstruction: audit }] }
}

function sourceObjectId(instruction: ResolvedReminderInstruction): string {
  const captureId = instruction.captureIds[0]
  if (!captureId?.startsWith('capture:')) throw new Error('This reminder has no recoverable source capture.')
  return captureId.slice('capture:'.length)
}

/** Handle or dismiss an active instruction without removing its source evidence. */
export function setReminderDeliveryState(state: AppState, instructionId: string, deliveryState: 'handled' | 'dismissed', at = new Date().toISOString()): AppState {
  const model = reconcileLegacyUi(state)
  const instruction = model.reminderInstructions?.find(value => value.id === instructionId)
  if (!instruction || instruction.deliveryState !== 'active') throw new Error('This reminder is no longer active. Refresh and try again.')
  const objectId = sourceObjectId(instruction)
  const object = state.objects.find(value => value.id === objectId)
  if (!object) throw new Error('This reminder source is no longer available. Its evidence was left unchanged.')
  const audit: ReminderInstructionAudit = { instructionId, action: deliveryState }
  return { ...state, objects: state.objects.map(value => value.id === objectId
    ? { ...value, history: [...value.history, { at, event: deliveryState === 'handled' ? 'Handled reminder' : 'Dismissed reminder', reminderInstruction: audit }] }
    : value) }
}

/** Convenience boundary for a mounted Reminder form: it returns a fresh projection with the instruction attached. */
export function resolveReminderInState(state: AppState, objectId: string, choice: ReminderChoice, at = new Date().toISOString()): AppState {
  const model = reconcileLegacyUi(state)
  const object = state.objects.find(value => value.id === objectId)
  if (!object) throw new Error('This capture is no longer available. Refresh Review and try again.')
  const resolved = resolveReminder(object, model.semanticObjects, choice, at)
  return legacyUiProjection(reconcileLegacyUi({ ...state, objects: state.objects.map(value => value.id === objectId ? resolved : value) }))
}
