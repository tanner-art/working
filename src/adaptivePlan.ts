import type { ActionPriority, AppState, ThoughtObject } from './domain'
import { unresolvedDependencies } from './dependencies'
import { reconcileLegacyUi } from './migration'

export interface PlanRecommendation {
  objectId: string
  title: string
  priority: ActionPriority
  explanation: string
}

export interface AdaptivePlanResult {
  recommendations: PlanRecommendation[]
  blockedCount: number
}

const compareText = (left: string, right: string) => left < right ? -1 : left > right ? 1 : 0

/** Only the latest dedicated gesture changes eligibility; a staged Action is not eligible by default. */
export function isPlanEligible(action: ThoughtObject): boolean {
  return action.history.filter(entry => entry.planEligibility !== undefined).at(-1)?.planEligibility?.eligible === true
}

export function setActionPlanEligibility(state: AppState, objectId: string, eligible: boolean): AppState {
  const model = reconcileLegacyUi(state)
  const stage = model.stagedActions?.find(item => item.objectId === objectId)
  const action = state.objects.find(item => item.id === objectId)
  if (!stage || stage.status !== 'staged' || !action || action.kind !== 'action' || action.status !== 'confirmed') {
    throw new Error('This Action is no longer staged. Refresh Schedule and try again.')
  }
  if (isPlanEligible(action) === eligible) return state
  const event = eligible ? 'Added Action to Adaptive Plan' : 'Removed Action from Adaptive Plan'
  return { ...state, objects: state.objects.map(item => item.id !== objectId ? item : {
    ...item, history: [...item.history, { at: new Date().toISOString(), event,
      planEligibility: { objectId, eligible, source: 'schedule-plan-eligibility' as const } }]
  }) }
}

/** Recomputed from confirmed staged Actions and current dependency state; never persisted as semantic truth. */
export function calculateAdaptivePlan(state: AppState): AdaptivePlanResult {
  const model = reconcileLegacyUi(state)
  const actions = new Map(state.objects.map(item => [item.id, item]))
  let blockedCount = 0
  const recommendations = (model.stagedActions ?? []).flatMap(stage => {
    if (stage.status !== 'staged') return []
    const action = actions.get(stage.objectId)
    if (!action || action.kind !== 'action' || action.status !== 'confirmed' || !isPlanEligible(action)) return []
    if (unresolvedDependencies(action, model.relationships, state.objects).length) {
      blockedCount += 1
      return []
    }
    return [{ objectId: action.id, title: action.interpretation.summary, priority: stage.priority,
      explanation: `Priority ${stage.priority} of 5 · ready to plan; no time has been booked.` }]
  }).sort((left, right) => right.priority - left.priority || compareText(left.title, right.title) || compareText(left.objectId, right.objectId))
  return { recommendations, blockedCount }
}
