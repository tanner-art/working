import type { ReviewContinuation } from '../reviewResolution'

/** WP-04 replaces this adapter without changing Review's continuation contract. */
export const commitmentResolution: ReviewContinuation = async () => ({
  status: 'needs-input',
  message: 'Set the commitment title, date, time, and dependencies. This capture remains in Review until you save the obligation.',
})
