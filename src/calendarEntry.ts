import type { AppState, ThoughtObject } from './domain'
import { confirmObject } from './objectWorkflow'
import { makeObject } from './store'
import { reconcileLegacyUi } from './migration'
import { activeTemporalDecisions, deadlineProposal, eventProposal, recordTemporalDecision } from './temporalConfirmation'

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
  return { ...recordTemporalDecision(candidate, model, target), model }
}

/** A fixed deadline is explicit temporal evidence, distinct from event scheduling. */
export function confirmCommitmentDeadline(state: AppState, objectId: string): AppState {
  const model = reconcileLegacyUi(state), object = model.semanticObjects.find(item => item.id === objectId && item.kind === 'commitment')
  if (!object) throw new Error('This commitment is no longer available. Refresh Calendar and try again.')
  const target = deadlineProposal(model, objectId)
  if (!target) throw new Error('This commitment has no valid proposed deadline to confirm.')
  if (activeTemporalDecisions(model).some(entry => entry.target.kind === 'fixed-deadline' && entry.target.objectId === objectId)) throw new Error('This commitment deadline is already confirmed.')
  return { ...recordTemporalDecision(state, model, target), model }
}
