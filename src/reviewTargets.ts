import type { AppState, PersistedState, SemanticObject } from './domain'

export type ReviewTargets = { targets: readonly SemanticObject[]; error?: string }

/** Read the same current evidence used for persistence, without taking Review down on failure. */
export function readReviewTargets(state: AppState, readModel: (current: AppState) => PersistedState): ReviewTargets {
  try { return { targets: readModel(state).semanticObjects } }
  catch { return { targets: [], error: 'Dependencies and reminder targets are unavailable. Retry saving or download a backup before resolving them.' } }
}
