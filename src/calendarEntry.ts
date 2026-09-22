import type { ThoughtObject } from './domain'
import { confirmObject } from './objectWorkflow'
import { makeObject } from './store'

/**
 * Calendar entry is an explicit confirmation of an obligation. It deliberately
 * does not create a CalendarEvent, deadline, or time; scheduling remains a
 * separate, later confirmation.
 */
export function createCalendarCommitment(content: string): ThoughtObject {
  const summary = content.trim()
  if (!summary) throw new Error('A commitment needs a description.')
  const draft = makeObject({
    kind: 'commitment',
    originalContent: summary,
    source: 'text',
    confidence: 1,
    interpretation: { summary, suggestedKind: 'commitment', rationale: 'Explicitly created as an obligation from Calendar.' }
  })
  return confirmObject(draft)
}
