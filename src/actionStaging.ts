import type { ActionPriority, AppState, ThoughtObject } from './domain'
import { eventProposal, recordTemporalDecision } from './temporalConfirmation'
import { advanceModelProjection, reconcileCurrentSession } from './store'

const validPriorities: ActionPriority[] = [1, 2, 3, 4, 5]

export function stageAction(object: ThoughtObject, priority: ActionPriority = 3): ThoughtObject {
  if (object.kind !== 'action' || object.status !== 'review' || !validPriorities.includes(priority)) throw new Error('Only an Action awaiting Review can be staged with a priority from 1 to 5.')
  return { ...object, status: 'confirmed', history: [...object.history, { at: new Date().toISOString(), event: 'Staged as Action', actionStage: { priority, source: 'review-action-staging' } }] }
}

export function setStagedActionPriority(state: AppState, objectId: string, priority: ActionPriority): AppState {
  if (!validPriorities.includes(priority)) throw new Error('Action priority must be between 1 and 5.')
  const model = reconcileCurrentSession(state)
  const action = state.objects.find(object => object.id === objectId)
  const stage = model.stagedActions?.find(value => value.objectId === objectId)
  if (!action || action.kind !== 'action' || action.status !== 'confirmed' || !stage || stage.status !== 'staged') throw new Error('This Action is no longer available for priority changes. Refresh Schedule and try again.')
  if (stage.priority === priority) return state
  return { ...state, objects: state.objects.map(object => object.id !== objectId ? object : { ...object, history: [...object.history, { at: new Date().toISOString(), event: `Set staged Action priority to ${priority}`, actionPriority: { priority, source: 'schedule-priority-selection' } }] }) }
}

export function scheduleStagedAction(state: AppState, objectId: string, startsAt: string, temporalContext: string): AppState {
  if (!Number.isFinite(Date.parse(startsAt)) || !temporalContext.trim()) throw new Error('Choose a valid date, time, and temporal context.')
  const current = state.objects.find(object => object.id === objectId)
  const model = reconcileCurrentSession(state)
  const stage = model.stagedActions?.find(value => value.objectId === objectId)
  if (!current || current.kind !== 'action' || current.status !== 'confirmed' || !stage || stage.status !== 'staged') throw new Error('This Action is no longer awaiting scheduling. Refresh Schedule and try again.')
  const eventId = crypto.randomUUID()
  const candidate: AppState = { ...state, objects: state.objects.map(object => object.id !== objectId ? object : { ...object, history: [...object.history, { at: new Date().toISOString(), event: 'Scheduled staged Action', actionSchedule: { eventId, startsAt, temporalContext } }] }) }
  const scheduled = reconcileCurrentSession(candidate)
  const target = eventProposal(scheduled, eventId)
  if (!target) throw new Error('The CalendarEvent could not be prepared safely. This Action remains staged.')
  return advanceModelProjection(recordTemporalDecision(candidate, scheduled, target))
}
