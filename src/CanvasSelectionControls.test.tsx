import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Canvas } from './Canvas'

const selection = vi.hoisted(() => ({ id: null as string | null, calls: 0 }))
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>()
  return { ...actual, useState: (initial: unknown) => {
    // Supply only Canvas's selected-object state. Advanced edit mode stays false.
    selection.calls += 1
    return actual.useState(selection.calls === 7 ? selection.id : initial)
  } }
})
beforeEach(() => { selection.id = null; selection.calls = 0 })

const noop = () => undefined
const render = (scale: number) => renderToStaticMarkup(<Canvas title="Synthetic canvas" autoFocusTitle={false}
  elements={[{ id: 'block', type: 'text', x: 10, y: 20, text: 'Select me' }]}
  viewport={{ x: 0, y: 0, scale }} onTitle={noop} onViewport={noop} onCommit={noop} onText={noop}
  onFinishText={noop} canUndo={false} canRedo={false} onUndo={noop} onRedo={noop}
  onCaptureObject={noop} onExit={noop} saveStatus="Saved" />)

describe('selected Canvas block controls', () => {
  it('does not show resize controls for an unselected block', () => {
    expect(render(1)).not.toContain('aria-label="Resize block"')
  })
  it.each([.55, 1, 1.6])('shows resize without advanced edit mode and compensates for scale %s', scale => {
    selection.id = 'block'
    const html = render(scale)
    expect(html).toContain('aria-label="Resize block"')
    expect(html).toContain(`transform:scale(${1 / scale});transform-origin:bottom right`)
    expect(html).toContain('--canvas-resize-target-size:44px')
    expect(html).not.toContain('aria-label="Block width"')
    expect(44 * (1 / scale) * scale).toBeCloseTo(44)
  })
})
