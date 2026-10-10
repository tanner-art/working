import type { AppState, TemporalDecision, ThoughtObject } from './domain'
import { confirmObject } from './objectWorkflow'
import { advanceModelProjection, makeObject } from './store'
import { reconcileLegacyUi } from './migration'
import { activeTemporalDecisions, deadlineProposal, eventProposal, recordTemporalDecision, validTemporalDate } from './temporalConfirmation'

/** One explicit Calendar save confirms an unlinked event, never an obligation. */
export function createDirectCalendarEvent(state: AppState, input: { title: string; date: string; time: string }): AppState {
  const title = input.title.trim()
  const temporalContext = Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'
  if (!title || !validTemporalDate(input.date) || !/^\d{2}:\d{2}$/.test(input.time) ||
      Number(input.time.slice(0, 2)) >= 24 || Number(input.time.slice(3, 5)) >= 60 || !temporalContext.trim()) {
    throw new Error('Enter an event title, valid date and start time.')
  }
  const [year, month, day] = input.date.split('-').map(Number)
  const [hour, minute] = input.time.split(':').map(Number)
  const local = new Date(year, month - 1, day, hour, minute)
  if (local.getFullYear() !== year || local.getMonth() !== month - 1 || local.getDate() !== day ||
      local.getHours() !== hour || local.getMinutes() !== minute) throw new Error('That local time does not exist. Choose another start time.')
  const model = reconcileLegacyUi(state)
  const eventId = crypto.randomUUID()
  const entry: TemporalDecision = { id: crypto.randomUUID(), at: new Date().toISOString(), source: 'calendar-direct-confirmation',
    decision: 'confirmed', target: { kind: 'direct-calendar-event', eventId, title, startsAt: local.toISOString(), temporalContext } }
  const next = { ...state, temporalHistory: [...(model.temporalHistory ?? []), entry] }
  reconcileLegacyUi(next) // fail closed before a caller can publish or save the event
  return next
}

/**
 * Calendar entry is an explicit confirmation of an obligation. It deliberately
 * does not create a CalendarEvent, deadline, or time; scheduling remains a
 * separate, later confirmation.
 */
export function createCalendarCommitment(content: string): ThoughtObject {
  const summary = content.trim()
  if (!summary) throw new Error('A commitment needs a description.')
  const draft = makeObject({
    kind: 'commitment',
    originalContent: summary,
    source: 'text',
    confidence: 1,
    interpretation: { summary, suggestedKind: 'commitment', rationale: 'Explicitly created as an obligation from Calendar.' }
  })
  return confirmObject(draft)
}

/** Scheduling is an explicit second gesture; Review time never creates an event by itself. */
export function scheduleCommitment(state: AppState, objectId: string, temporalContext = Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'): AppState {
  const object = state.objects.find(item => item.id === objectId)
  if (!object || object.kind !== 'commitment' || object.status !== 'confirmed') throw new Error('This commitment is no longer available for scheduling. Refresh Calendar and try again.')
  const setup = object.history.find(entry => entry.commitmentSetup)?.commitmentSetup
  if (!setup?.date || !setup.time) throw new Error('Choose and save both a date and time in Commitment setup before scheduling.')
  if (object.history.some(entry => entry.commitmentSchedule)) throw new Error('This commitment already has a CalendarEvent. Refresh Calendar and try again.')
  const startsAt = new Date(`${setup.date}T${setup.time}`).toISOString()
  if (!Number.isFinite(Date.parse(startsAt))) throw new Error('The selected commitment date and time are invalid.')
  const eventId = crypto.randomUUID()
  const candidate: AppState = { ...state, objects: state.objects.map(item => item.id !== objectId ? item : { ...item, history: [...item.history, { at: new Date().toISOString(), event: 'Scheduled Commitment CalendarEvent', commitmentSchedule: { eventId, startsAt, temporalContext, source: 'commitment-calendar-scheduling' } }] }) }
  const model = reconcileLegacyUi(candidate), target = eventProposal(model, eventId)
  if (!target) throw new Error('The CalendarEvent could not be prepared safely. This commitment remains unscheduled.')
  return advanceModelProjection(recordTemporalDecision(candidate, model, target))
}

/** A fixed deadline is explicit temporal evidence, distinct from event scheduling. */
export function confirmCommitmentDeadline(state: AppState, objectId: string): AppState {
  const model = reconcileLegacyUi(state), object = model.semanticObjects.find(item => item.id === objectId && item.kind === 'commitment')
  if (!object) throw new Error('This commitment is no longer available. Refresh Calendar and try again.')
  const target = deadlineProposal(model, objectId)
  if (!target) throw new Error('This commitment has no valid proposed deadline to confirm.')
  if (activeTemporalDecisions(model).some(entry => entry.target.kind === 'fixed-deadline' && entry.target.objectId === objectId)) throw new Error('This commitment deadline is already confirmed.')
  return advanceModelProjection(recordTemporalDecision(state, model, target))
}
