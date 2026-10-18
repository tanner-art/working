import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { EMPTY_THOUGHT_LABEL } from './card'
import { createThoughtStatusFixture } from './status'

const renderFixture = (fixture: ReturnType<typeof createThoughtStatusFixture>) => (
  renderToStaticMarkup(fixture.render())
)

describe('thought status fixture', () => {
  it('renders a thought as open, complete, then open again without changing its card text', () => {
    const fixture = createThoughtStatusFixture('  <em>Keep this literal</em>  ')

    expect(renderFixture(fixture)).toContain('<p role="status">Open</p>')
    expect(renderFixture(fixture)).toContain('&lt;em&gt;Keep this literal&lt;/em&gt;')

    fixture.complete()

    expect(renderFixture(fixture)).toContain('<p role="status">Complete</p>')
    expect(renderFixture(fixture)).toContain('&lt;em&gt;Keep this literal&lt;/em&gt;')
    expect(renderFixture(fixture)).not.toContain('<em>')
    expect(renderFixture(fixture)).toContain('>Reopen</button>')

    fixture.reopen()

    expect(renderFixture(fixture)).toContain('<p role="status">Open</p>')
    expect(renderFixture(fixture)).toContain('&lt;em&gt;Keep this literal&lt;/em&gt;')
    expect(renderFixture(fixture)).toContain('>Complete</button>')
  })

  it('retains the predecessor empty-state behavior for whitespace-only input', () => {
    const fixture = createThoughtStatusFixture(' \n\t ')

    expect(renderFixture(fixture)).toContain(`>${EMPTY_THOUGHT_LABEL}</article>`)
  })
})
