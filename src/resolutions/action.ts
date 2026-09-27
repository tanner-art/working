import type { ReviewContinuation } from '../reviewResolution'
import { stageAction } from '../actionStaging'

/**
 * WP-02 replaces this adapter while retaining this exact continuation boundary.
 * Until then, no inferred work is allowed to leave Review.
 */
export const actionResolution: ReviewContinuation = async object => ({ status: 'completed', object: stageAction(object) })
