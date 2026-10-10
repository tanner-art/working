import { describe, expect, it, vi } from 'vitest'
import { handleCanvasShortcut } from './useCanvasWorkspace'

describe('Canvas shortcuts behind Search', () => {
  it('does not undo or redo a hidden Canvas, then resumes after Search closes', () => {
    const session = { undo: vi.fn(), redo: vi.fn() }
    const event = (key: string, shiftKey = false) => ({
      key, shiftKey, metaKey: true, ctrlKey: false, target: null, preventDefault: vi.fn(),
    }) as unknown as KeyboardEvent
    const undo = event('z')
    const redo = event('z', true)
    handleCanvasShortcut(undo, session, false)
    handleCanvasShortcut(redo, session, false)
    expect(session.undo).not.toHaveBeenCalled()
    expect(session.redo).not.toHaveBeenCalled()
    expect(undo.preventDefault).not.toHaveBeenCalled()
    handleCanvasShortcut(undo, session, true)
    handleCanvasShortcut(redo, session, true)
    expect(session.undo).toHaveBeenCalledOnce()
    expect(session.redo).toHaveBeenCalledOnce()
    expect(undo.preventDefault).toHaveBeenCalledOnce()
  })
})
