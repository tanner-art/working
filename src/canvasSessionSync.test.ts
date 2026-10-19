import { describe, expect, it } from 'vitest'
import { createCanvasSession } from './canvasSession'
import { DEFAULT_CANVAS_VIEWPORT, type CanvasDocument } from './canvasDocument'

describe('canvas session across account refresh', () => {
  it('replaces stale undo/redo and text history before reopening a remotely changed canvas', () => {
    let document: CanvasDocument = { elements: [{ id: 'text', type: 'text', x: 0, y: 0, text: 'Original' }], viewport: { ...DEFAULT_CANVAS_VIEWPORT } }
    const session = createCanvasSession({ read: () => structuredClone(document), write: next => { document = structuredClone(next) } })
    session.editText('text', 'Local saved edit')
    expect(session.canUndo).toBe(true)
    // Another device's committed snapshot arrives while this canvas is closed.
    document.elements = [{ id: 'text', type: 'text', x: 50, y: 70, text: 'Remote saved edit' }]
    session.synchronize()
    expect(session.canUndo).toBe(false)
    expect(session.canRedo).toBe(false)
    session.editText('text', 'Next local edit')
    expect(document.elements[0]).toMatchObject({ x: 50, y: 70, text: 'Next local edit' })
    session.undo()
    expect(document.elements[0]).toMatchObject({ x: 50, y: 70, text: 'Remote saved edit' })
  })
  it('keeps normal local undo history when the persisted canvas has not changed', () => {
    let document: CanvasDocument = { elements: [{ id: 'text', type: 'text', x: 0, y: 0, text: 'Original' }], viewport: { ...DEFAULT_CANVAS_VIEWPORT } }
    const session = createCanvasSession({ read: () => structuredClone(document), write: next => { document = structuredClone(next) } })
    session.editText('text', 'Local saved edit'); session.synchronize()
    expect(session.canUndo).toBe(true)
    session.undo(); expect(document.elements[0].text).toBe('Original')
  })
})
