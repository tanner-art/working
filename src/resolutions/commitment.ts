import type { ReviewContinuation } from '../reviewResolution'

/** WP-04 replaces this adapter without changing Review's continuation contract. */
export const commitmentResolution: ReviewContinuation = async () => ({
  status: 'unavailable',
  message: 'Commitment resolution is not available yet. This capture is still in Review; try again after Commitment setup is available.',
})
