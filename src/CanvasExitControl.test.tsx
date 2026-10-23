import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Canvas, CanvasExitControl } from './Canvas'

describe('Canvas exit control', () => {
  it('returns to the Canvas Bank when activated', () => {
    const onExit = vi.fn()
    const control = CanvasExitControl({ onExit })
    expect(control.props['aria-label']).toBe('Close canvas and return to Canvas Bank')
    control.props.onClick()
    expect(onExit).toHaveBeenCalledOnce()
  })

  it('mounts the accessible exit control in the complete Canvas shell', () => {
    const noop = () => undefined
    const markup = renderToStaticMarkup(<Canvas title="Map" autoFocusTitle={false} elements={[]} viewport={{ x: 0, y: 0, scale: 1 }}
      onTitle={noop} onViewport={noop} onCommit={noop} onText={noop} onFinishText={noop}
      canUndo={false} canRedo={false} onUndo={noop} onRedo={noop} onCaptureObject={noop} onExit={noop} saveStatus="Saved" />)
    expect(markup).toContain('aria-label="Close canvas and return to Canvas Bank"')
    expect(markup).toContain('Back to Bank')
    expect(markup).toContain('aria-label="More canvas tools"')
    expect(markup).toContain('<summary>Ink</summary>')
    expect(markup).toContain('aria-label="Ink color: #344d41"')
    expect(markup).toContain('aria-label="3 pixel ink width" aria-pressed="true"')
  })

  it('renders saved strokes with their own ink appearance while preserving the legacy default', () => {
    const noop = () => undefined
    const markup = renderToStaticMarkup(<Canvas title="Map" autoFocusTitle={false} elements={[
      { id: 'legacy', type: 'freehand', x: 0, y: 0, rawPoints: [{ x: 0, y: 0 }, { x: 10, y: 10 }] },
      { id: 'colored', type: 'freehand', x: 0, y: 20, rawPoints: [{ x: 0, y: 20 }, { x: 10, y: 30 }], strokeColor: '#9b3f4e', strokeWidth: 6 },
    ]} viewport={{ x: 0, y: 0, scale: 1 }} onTitle={noop} onViewport={noop} onCommit={noop} onText={noop}
      onFinishText={noop} canUndo={false} canRedo={false} onUndo={noop} onRedo={noop}
      onCaptureObject={noop} onExit={noop} saveStatus="Saved" />)
    expect(markup).toContain('style="stroke:#344d41;stroke-width:3"')
    expect(markup).toContain('style="stroke:#9b3f4e;stroke-width:6"')
  })
})
