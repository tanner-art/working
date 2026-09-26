import { describe, expect, it, vi } from 'vitest'
import { CanvasExitControl } from './Canvas'

describe('Canvas exit control', () => {
  it('returns to the Canvas Bank when activated', () => {
    const onExit = vi.fn()
    const control = CanvasExitControl({ onExit })
    expect(control.props['aria-label']).toBe('Close canvas and return to Canvas Bank')
    control.props.onClick()
    expect(onExit).toHaveBeenCalledOnce()
  })
})
