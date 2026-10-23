import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { WorkspaceHub } from './WorkspaceHub'
import { GlobalSearchView } from './GlobalSearchView'

describe('segmented workspace destinations', () => {
  it('offers captures and canvases together without mounting their full screens', () => {
    const html = renderToStaticMarkup(<WorkspaceHub kind="organize" onOpen={() => {}} />)
    expect(html).toContain('Captures</strong>')
    expect(html).toContain('Canvases</strong>')
    expect(html.match(/<button/g)).toHaveLength(2)
    expect(html).not.toContain('textarea')
  })
  it('places Schedule before Calendar with separate accessible buttons', () => {
    const html = renderToStaticMarkup(<WorkspaceHub kind="plan" onOpen={() => {}} />)
    expect(html.indexOf('Schedule</strong>')).toBeLessThan(html.indexOf('Calendar</strong>'))
    expect(html.match(/<button/g)).toHaveLength(2)
  })
  it('labels AI native search as coming soon, not an active AI capability', () => {
    const html = renderToStaticMarkup(<GlobalSearchView state={{ objects: [], canvas: [] }} snapshotToken="test" navigate={() => ({ ok: true })} />)
    expect(html).toContain('AI native</h2>')
    expect(html).toContain('Coming soon</p>')
    expect(html).toContain('Search your thoughts')
  })
})
