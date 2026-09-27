import type { ReviewContinuation } from '../reviewResolution'

/** Reminder details are collected by the Review continuation owner before mutation. */
export const reminderResolution: ReviewContinuation = async () => ({
  status: 'needs-input',
  message: 'Choose a reminder target and either Specific or Daily log in Reminder setup. This capture remains in Review until those details are confirmed.',
})
