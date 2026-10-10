import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ObjectPanel } from './App'
import type { ThoughtObject } from './domain'

const reminder = (created: boolean): ThoughtObject => ({
  id: 'reminder-panel', kind: 'reminder', status: created ? 'confirmed' : 'review',
  originalContent: 'Remind me', source: 'text', createdAt: '2026-09-27T08:00:00Z', confidence: .5,
  interpretation: { summary: 'Reminder', suggestedKind: 'reminder', rationale: 'Review' },
  metadata: {}, relationships: [], history: created ? [{ at: '2026-09-27T08:02:00Z', event: 'Created Daily log reminder',
    reminderInstruction: { instructionId: 'reminder:reminder-panel', action: 'created', targetId: 'idea:target', mode: 'daily-log' } }] : [],
})

afterEach(() => vi.unstubAllGlobals())

describe('Reminder object detail Type affordance', () => {
  it.each([true, false])('is read-only exactly when a created instruction exists (%s)', created => {
    vi.stubGlobal('document', { activeElement: null })
    vi.stubGlobal('HTMLElement', class {})
    const object = reminder(created)
    const markup = renderToStaticMarkup(<ObjectPanel object={object} history={{ immutableSource: object.originalContent,
      currentText: object.originalContent, revisions: [], corrections: [], progression: [] }}
      onClose={() => undefined} onSave={() => undefined} onRevise={() => undefined}
      onCorrect={() => undefined} onReverse={() => undefined} />)
    expect(markup).toMatch(created ? /Type<select[^>]*disabled=""[^>]*aria-describedby="reminder-type-note"/
      : /Type<select[^>]*><option/)
    expect(markup.includes('Type is fixed after a Reminder is created.')).toBe(created)
    expect(markup.includes('<option value="review" disabled=""')).toBe(created)
    expect(markup.includes('<option value="inbox" disabled=""')).toBe(created)
    expect(markup).toContain('>Folder<select')
  })
})
