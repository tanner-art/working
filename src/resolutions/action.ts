import type { ReviewContinuation } from '../reviewResolution'

/**
 * WP-02 replaces this adapter while retaining this exact continuation boundary.
 * Until then, no inferred work is allowed to leave Review.
 */
export const actionResolution: ReviewContinuation = async () => ({
  status: 'unavailable',
  message: 'Action resolution is not available yet. This capture is still in Review; try again after Action setup is available.',
})
