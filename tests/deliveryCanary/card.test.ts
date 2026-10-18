import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CapturedThoughtCard, EMPTY_THOUGHT_LABEL } from './card'

const renderCard = (thought: string) => renderToStaticMarkup(
  createElement(CapturedThoughtCard, { thought }),
)

describe('CapturedThoughtCard', () => {
  it('renders a nonempty thought with surrounding whitespace trimmed', () => {
    expect(renderCard('  Outline the launch plan  ')).toContain('>Outline the launch plan</article>')
  })

  it('renders an empty-state label for whitespace-only input', () => {
    expect(renderCard(' \n\t ')).toContain(`>${EMPTY_THOUGHT_LABEL}</article>`)
  })

  it('renders HTML-like input as escaped literal text', () => {
    const markup = renderCard('  <em>Keep this literal</em>  ')

    expect(markup).toContain('&lt;em&gt;Keep this literal&lt;/em&gt;')
    expect(markup).not.toContain('<em>')
    expect(markup).not.toContain('</em>')
  })
})
