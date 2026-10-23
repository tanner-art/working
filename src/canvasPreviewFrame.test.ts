import { describe, expect, it, vi } from 'vitest'
import { createCanvasPreviewFrame } from './canvasPreviewFrame'

describe('Canvas preview frame budget', () => {
  it('coalesces 200 move samples into one render of the newest preview', () => {
    let draw: (() => void) | undefined
    const request = vi.fn((callback: () => void) => { draw = callback; return 1 })
    const frame = createCanvasPreviewFrame(request, vi.fn()), render = vi.fn()
    for (let i = 0; i < 200; i++) frame.schedule(() => render(i))
    expect(request).toHaveBeenCalledOnce()
    expect(render).not.toHaveBeenCalled()
    draw!()
    expect(render).toHaveBeenCalledExactlyOnceWith(199)
    frame.schedule(() => render(200))
    expect(request).toHaveBeenCalledTimes(2)
  })
  it('discards queued previews on commit, cancel or unmount', () => {
    let draw: (() => void) | undefined
    const cancel = vi.fn(), render = vi.fn()
    const frame = createCanvasPreviewFrame(callback => { draw = callback; return 4 }, cancel)
    frame.schedule(render); frame.cancel()
    expect(cancel).toHaveBeenCalledExactlyOnceWith(4)
    draw!()
    expect(render).not.toHaveBeenCalled()
  })
})
