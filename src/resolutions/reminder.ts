import type { ReviewContinuation } from '../reviewResolution'

/**
 * The fixed WP-01 continuation intentionally has no target, mode, or time
 * parameters. It must therefore fail closed until its owner mounts
 * ReminderResolution and supplies that explicit user input.
 */
export const reminderResolution: ReviewContinuation = async () => ({
  status: 'unavailable',
  message: 'Choose a reminder target and either Specific or Daily log in Reminder setup. This capture remains in Review until those details are confirmed.',
})
