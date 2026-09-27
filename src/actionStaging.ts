import type { ActionPriority, AppState, ThoughtObject } from './domain'
import { eventProposal, recordTemporalDecision } from './temporalConfirmation'
import { reconcileLegacyUi } from './migration'

const validPriorities: ActionPriority[] = [1, 2, 3, 4, 5]

/** The Review click is the discrete confirmation that creates a staged, non-executable Action. */
export function stageAction(object: ThoughtObject, priority: ActionPriority = 3): ThoughtObject {
  if (object.kind !== 'action' || object.status !== 'review') throw new Error('Only an Action awaiting Review can be staged.')
  if (!validPriorities.includes(priority)) throw new Error('Action priority must be between 1 and 5.')
  const at = new Date().toISOString()
  return { ...object, status: 'confirmed', history: [...object.history, {
    at, event: 'Staged as Action', actionStage: { priority, source: 'review-action-staging' },
  }] }
}

/** Scheduling is a second, user-authored confirmation and never plan-enables the Action. */
export function scheduleStagedAction(state: AppState, objectId: string, startsAt: string, temporalContext: string): AppState {
  if (!Number.isFinite(Date.parse(startsAt)) || !temporalContext.trim()) throw new Error('Choose a valid date, time, and temporal context.')
  const current = state.objects.find(object => object.id === objectId)
  if (!current) throw new Error('This staged Action is no longer available. Refresh Schedule and try again.')
  const model = reconcileLegacyUi(state)
  const stage = model.stagedActions?.find(value => value.objectId === objectId)
  if (!stage || stage.status !== 'staged') throw new Error('This Action is no longer awaiting scheduling. Refresh Schedule and try again.')
  const eventId = crypto.randomUUID()
  const candidate: AppState = {
    ...state,
    objects: state.objects.map(object => object.id !== objectId ? object : {
      ...object,
      history: [...object.history, { at: new Date().toISOString(), event: 'Scheduled staged Action', actionSchedule: { eventId, startsAt, temporalContext } }],
    }),
  }
  const scheduledModel = reconcileLegacyUi(candidate)
  const target = eventProposal(scheduledModel, eventId)
  if (!target) throw new Error('The CalendarEvent could not be prepared safely. This Action remains staged.')
  return recordTemporalDecision(candidate, scheduledModel, target)
}
