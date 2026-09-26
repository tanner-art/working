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
  })
})
