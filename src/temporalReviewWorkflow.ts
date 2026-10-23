import type { AppState, PersistedState, TemporalDecision, TemporalTarget } from './domain'
import { advanceModelProjection, reconcileCurrentSession } from './store'
import { recordTemporalDecision } from './temporalConfirmation'

/** Review must use the latest saved interpretation, not the model loaded before autosaves. */
export function decideTemporalReview(state: AppState, target: TemporalTarget, reverse?: TemporalDecision, accountModel?: PersistedState): AppState {
  const model = reconcileCurrentSession(state, accountModel)
  const decided = recordTemporalDecision(state, model, target, reverse)
  // Account storage owns its current model independently of local CAS lineage.
  return advanceModelProjection(decided, accountModel)
}
