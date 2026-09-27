import type { ReviewContinuation } from '../reviewResolution'
import { stageAction } from '../actionStaging'

/**
 * The fixed WP-01 continuation boundary remains intact; WP-02 owns the
 * durable staging transition behind it.
 */
export const actionResolution: ReviewContinuation = async object => ({ status: 'completed', object: stageAction(object) })
