import type { ReviewContinuation } from '../reviewResolution'

/** WP-03 replaces this adapter without changing Review's continuation contract. */
export const reminderResolution: ReviewContinuation = async () => ({
  status: 'unavailable',
  message: 'Reminder resolution is not available yet. This capture is still in Review; try again after Reminder setup is available.',
})
