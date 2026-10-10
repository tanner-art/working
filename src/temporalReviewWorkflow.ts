import type { AppState, PersistedState, TemporalDecision, TemporalTarget } from './domain'
import { reconcileLegacyUi } from './migration'
import { advanceModelProjection, reconcileCurrentSession } from './store'
import { recordTemporalDecision } from './temporalConfirmation'

/** Review must use the latest saved interpretation, not the model loaded before autosaves. */
export function decideTemporalReview(state: AppState, target: TemporalTarget, reverse?: TemporalDecision, accountModel?: PersistedState): AppState {
  const model = accountModel ?? reconcileCurrentSession(state)
  const decided = recordTemporalDecision(state, model, target, reverse)
  // Account storage owns its current model independently of the local-storage
  // session. Carry that exact base forward; never register it as a local CAS token.
  return accountModel ? { ...decided, model: reconcileLegacyUi({ ...decided, model }) } : advanceModelProjection(decided)
}
