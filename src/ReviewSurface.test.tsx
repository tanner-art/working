import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Review } from './App'
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

describe('mounted Review surface', () => {
  it('renders the one resolution control with exactly the four required choices', () => {
    const markup = renderToStaticMarkup(<Review objects={[thought()]} onResolve={() => undefined} onReject={() => undefined} onOpen={() => undefined} />)
    expect(markup).toContain('aria-label="Resolve capture"')
    for (const label of ['Action', 'Commitment', 'Reminder', 'Idea']) expect(markup).toContain(`>${label}</button>`)
    expect(markup.match(/Resolve this capture as:/g)).toHaveLength(1)
    expect(markup).toContain('Edit thought')
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
})
