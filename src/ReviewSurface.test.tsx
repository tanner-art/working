import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ObjectPanel, Review, focusPendingReviewChoice } from './App'
import type { ThoughtObject } from './domain'

const thought = (status: ThoughtObject['status'] = 'review', method?: ThoughtObject['interpretation']['method']): ThoughtObject => ({
  id: `thought:${status}`,
  kind: 'idea',
  originalContent: 'Explore a calmer launch plan',
  source: 'text',
  confidence: .72,
  status,
  createdAt: '2026-09-26T08:00:00.000Z',
  interpretation: { summary: 'Explore a calmer launch plan', suggestedKind: 'idea', rationale: 'An idea to consider.', method },
  metadata: {},
  relationships: [],
  history: status === 'confirmed' ? [{ at: '2026-09-26T08:01:00.000Z', event: 'Confirmed as idea', confirmation: { objectId: `thought:${status}`, transition: 'idea', summary: 'Explore a calmer launch plan', source: 'review-confirmation' } }] : [],
})

afterEach(() => vi.unstubAllGlobals())

describe('mounted Review surface', () => {
  it('opens Review and focuses its first available classification choice for a Search handoff', () => {
    const focus = vi.fn()
    const disclosure = { open: false } as HTMLDetailsElement
    const card = { querySelector: vi.fn(() => ({ focus })) } as unknown as HTMLElement
    expect(focusPendingReviewChoice(disclosure, card)).toBe(true)
    expect(disclosure.open).toBe(true)
    expect(card.querySelector).toHaveBeenCalledWith('.review-actions button:not(:disabled)')
    expect(focus).toHaveBeenCalledOnce()
    expect(focusPendingReviewChoice(null, card)).toBe(false)
    expect(focusPendingReviewChoice(disclosure, undefined)).toBe(false)
  })

  it('renders the one resolution control with exactly the four required choices', () => {
    const markup = renderToStaticMarkup(<Review objects={[thought()]} onResolve={() => undefined} onReject={() => undefined} onOpen={() => undefined} />)
    expect(markup).toContain('aria-label="Resolve capture"')
    for (const label of ['Action', 'Commitment', 'Reminder', 'Idea']) expect(markup).toContain(`>${label}</button>`)
    expect(markup.match(/Resolve this capture as:/g)).toHaveLength(1)
    expect(markup).toContain('Edit thought')
  })

  it('keeps pending Review text and meaning edits without a second classification or metadata form', () => {
    vi.stubGlobal('document', { activeElement: null })
    vi.stubGlobal('HTMLElement', class {})
    const object = thought()
    const markup = renderToStaticMarkup(<ObjectPanel object={object} history={{ immutableSource: object.originalContent,
      currentText: object.originalContent, revisions: [], corrections: [], progression: [] }}
      onClose={() => undefined} onSave={() => undefined} onRevise={() => undefined}
      onCorrect={() => undefined} onReverse={() => undefined} />)
    expect(markup).toContain('Thought text<textarea')
    expect(markup).toContain('Organized meaning<textarea')
    expect(markup).not.toContain('class="form-grid"')
    expect(markup).not.toContain('Save changes')
  })

  it('shows a resolved Idea in the Ideas destination', () => {
    const markup = renderToStaticMarkup(<Review objects={[thought('confirmed')]} onResolve={() => undefined} onReject={() => undefined} onOpen={() => undefined} />)
    expect(markup).toContain('id="ideas-heading"')
    expect(markup).toContain('Explore a calmer launch plan')
    expect(markup).not.toContain('No resolved ideas yet.')
  })

  it.each([
    ['provider', 'Interpreted by AI'],
    ['built-in', 'Interpreted by built-in rules'],
    ['built-in-fallback', 'Built-in interpretation used because AI was unavailable'],
    [undefined, 'Interpretation source was not recorded'],
  ] as const)('shows trustworthy per-capture provenance for %s', (method, label) => {
    const markup = renderToStaticMarkup(<Review objects={[thought('review', method)]} onResolve={() => undefined} onReject={() => undefined} onOpen={() => undefined} />)
    expect(markup).toContain(label)
  })

  it('distinguishes a user-edited AI interpretation from untouched AI wording', () => {
    const item = thought('review', 'provider')
    item.history.push({ at: '2026-09-26T08:02:00.000Z', event: 'Revised interpretation', reviewRevision: { from: item.interpretation.summary, to: 'My wording' } })
    item.interpretation.summary = 'My wording'
    const markup = renderToStaticMarkup(<Review objects={[item]} onResolve={() => undefined} onReject={() => undefined} onOpen={() => undefined} />)
    expect(markup).toContain('Initially interpreted by AI; edited by you')
    expect(markup).not.toContain('>Interpreted by AI<')
  })
})
