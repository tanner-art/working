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
  it.each([true, false])('keeps the legacy editor only after Review resolution (%s)', created => {
    vi.stubGlobal('document', { activeElement: null })
    vi.stubGlobal('HTMLElement', class {})
    const object = reminder(created)
    const markup = renderToStaticMarkup(<ObjectPanel object={object} history={{ immutableSource: object.originalContent,
      currentText: object.originalContent, revisions: [], corrections: [], progression: [] }}
      onClose={() => undefined} onSave={() => undefined} onRevise={() => undefined}
      onCorrect={() => undefined} onReverse={() => undefined} />)
    if (created) expect(markup).toMatch(/Type<select[^>]*disabled=""[^>]*aria-describedby="reminder-type-note"/)
    else {
      expect(markup).not.toContain('Type<select')
      expect(markup).not.toContain('>Folder<select')
      expect(markup).not.toContain('>Proposed date<input')
      expect(markup).not.toContain('>Time<input')
      expect(markup).not.toContain('>Effort<select')
      expect(markup).toContain('Thought text<textarea')
      expect(markup).toContain('Organized meaning<textarea')
      expect(markup).toContain('Choose Action, Commitment, Reminder, or Idea in Review')
    }
    expect(markup.includes('Type is fixed after a Reminder is created.')).toBe(created)
    expect(markup.includes('<option value="review" disabled=""')).toBe(created)
    expect(markup.includes('<option value="inbox" disabled=""')).toBe(created)
    if (created) expect(markup).toContain('>Context<select')
  })

  it.each(['complete', 'archived'] as const)('keeps Confirmed selectable for a %s created Reminder', status => {
    vi.stubGlobal('document', { activeElement: null })
    vi.stubGlobal('HTMLElement', class {})
    const object = { ...reminder(true), status }
    const markup = renderToStaticMarkup(<ObjectPanel object={object} history={{ immutableSource: object.originalContent,
      currentText: object.originalContent, revisions: [], corrections: [], progression: [] }}
      onClose={() => undefined} onSave={() => undefined} onRevise={() => undefined}
      onCorrect={() => undefined} onReverse={() => undefined} />)
    expect(markup).toContain('<option value="confirmed">confirmed</option>')
    expect(markup).toContain(`<option value="${status}" selected="">${status}</option>`)
    expect(markup).toContain('<option value="review" disabled="">review</option>')
  })
})
