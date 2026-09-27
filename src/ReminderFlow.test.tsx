import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Review } from './App'
import { ReminderResolution } from './ReminderResolution'
import { resolveReviewCapture } from './reviewResolution'
import type { SemanticObject, ThoughtObject } from './domain'

const reminder: ThoughtObject = { id: 'review-reminder', kind: 'reminder', status: 'review', originalContent: 'Remind me about this', source: 'text', createdAt: '2026-09-27T08:00:00Z', confidence: .5, interpretation: { summary: 'Reminder', suggestedKind: 'reminder', rationale: 'Requires timing' }, metadata: {}, relationships: [], history: [] }
const target: SemanticObject = { id: 'idea', kind: 'idea', captureIds: ['capture:idea'], interpretationIds: ['interpretation:idea:1'], summary: 'Idea target', status: 'confirmed', metadata: {}, reminders: [] }

describe('Review to Reminder flow', () => {
  it('uses the registered Review continuation to enter the mounted accessible form with exactly Specific and Daily log', async () => {
    expect(await resolveReviewCapture(reminder, 'reminder')).toMatchObject({ status: 'needs-input' })
    const review = renderToStaticMarkup(<Review objects={[reminder]} targets={[target]} onResolve={() => undefined} onResolveReminder={() => undefined} onReject={() => undefined} onOpen={() => undefined} />)
    expect(review).toContain('>Reminder</button>')
    const form = renderToStaticMarkup(<ReminderResolution object={reminder} targets={[target]} onResolve={() => undefined} />)
    expect(form).toContain('aria-label="Set reminder details"')
    expect(form).toContain(' Specific</label>')
    expect(form).toContain(' Daily log</label>')
    expect(form).toContain('Notification delivery is not available')
  })
})
