import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { createCanvasRecord } from './canvasBank'
import { CanvasBank } from './CanvasBankView'

const canvas = (id: string, title: string, updatedAt: string) => ({
  ...createCanvasRecord('2026-09-26T08:00:00.000Z', id),
  title,
  updatedAt,
})

describe('Canvas Bank search surface', () => {
  it('renders an accessible search input, result count, and original canvas card callbacks', () => {
    const productMap = canvas('canvas:product', 'Product map', '2026-09-26T10:00:00.000Z')
    const launchPlan = canvas('canvas:launch', 'Launch plan', '2026-09-26T09:00:00.000Z')
    const onOpen = vi.fn()
    const markup = renderToStaticMarkup(<CanvasBank bank={{ canvases: [launchPlan, productMap] }} focusTarget={null} onCreate={() => undefined} onOpen={onOpen} />)

    expect(markup).toContain('<label for="canvas-bank-search">Search canvases</label>')
    expect(markup).toContain('type="search"')
    expect(markup).toContain('2 canvases saved')
    expect(markup.indexOf('Product map')).toBeLessThan(markup.indexOf('Launch plan'))
    expect(markup).toContain('aria-label="Open Product map"')
    expect(markup).toContain('aria-label="Open Launch plan"')
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('keeps the existing empty-bank state instead of showing search controls', () => {
    const markup = renderToStaticMarkup(<CanvasBank bank={{ canvases: [] }} focusTarget={null} onCreate={() => undefined} onOpen={() => undefined} />)

    expect(markup).toContain('Your canvases will live here.')
    expect(markup).not.toContain('canvas-bank-search')
  })
})
