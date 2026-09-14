import { describe, expect, it } from 'vitest'
import type { CanvasElement } from './domain'
import {
  CANVAS_HISTORY_LIMIT,
  canRedoCanvas,
  canUndoCanvas,
  commitCanvas,
  emptyCanvasHistory,
  redoCanvas,
  sameCanvas,
  undoCanvas,
} from './canvasHistory'

const node = (id: string, x: number, text = 'thought'): CanvasElement => ({ id, type: 'text', x, y: 0, text })
const arrow = (id: string, fromId: string, toId: string): CanvasElement => ({ id, type: 'arrow', x: 0, y: 0, fromId, toId })

describe('canvasHistory', () => {
  it('starts with nothing to undo or redo', () => {
    const history = emptyCanvasHistory([node('a', 0)])
    expect(canUndoCanvas(history)).toBe(false)
    expect(canRedoCanvas(history)).toBe(false)
    expect(undoCanvas(history)).toBe(history)
    expect(redoCanvas(history)).toBe(history)
  })

  it('undoes an add back to the pre-add snapshot', () => {
    const before: CanvasElement[] = [node('a', 0)]
    const after: CanvasElement[] = [...before, node('b', 100)]
    const history = commitCanvas(emptyCanvasHistory(before), after)
    expect(canUndoCanvas(history)).toBe(true)
    const undone = undoCanvas(history)
    expect(undone.present).toEqual(before)
    expect(canRedoCanvas(undone)).toBe(true)
  })

  it('redoes back to the post-edit snapshot after an undo', () => {
    const before: CanvasElement[] = [node('a', 0)]
    const after: CanvasElement[] = [...before, node('b', 100)]
    const history = commitCanvas(emptyCanvasHistory(before), after)
    const undone = undoCanvas(history)
    const redone = redoCanvas(undone)
    expect(redone.present).toEqual(after)
    expect(canRedoCanvas(redone)).toBe(false)
  })

  it('clears redo history when a new edit is recorded after an undo', () => {
    const v1: CanvasElement[] = [node('a', 0)]
    const v2: CanvasElement[] = [...v1, node('b', 100)]
    const v3: CanvasElement[] = [...v1, node('c', 200)]
    let history = commitCanvas(emptyCanvasHistory(v1), v2) // present=v2, past=[v1]
    history = undoCanvas(history) // present=v1, future=[v2]
    expect(canRedoCanvas(history)).toBe(true)
    history = commitCanvas(history, v3) // present=v1 -> v3
    expect(canRedoCanvas(history)).toBe(false)
    expect(redoCanvas(history)).toBe(history)
  })

  it('groups a drag into a single undo step regardless of intermediate positions', () => {
    const before: CanvasElement[] = [node('a', 0)]
    // Only the final dragged position is ever recorded — intermediate pointer-move
    // positions never call commitCanvas, so one drag == one history entry.
    const draggedFinal: CanvasElement[] = [node('a', 240)]
    const history = commitCanvas(emptyCanvasHistory(before), draggedFinal)
    expect(history.past).toHaveLength(1)
    const undone = undoCanvas(history)
    expect(undone.present).toEqual(before)
    expect(undone.past).toHaveLength(0)
  })

  it('restores connector endpoints exactly on undo/redo', () => {
    const before: CanvasElement[] = [node('a', 0), node('b', 200)]
    const after: CanvasElement[] = [...before, arrow('e1', 'a', 'b')]
    const history = commitCanvas(emptyCanvasHistory(before), after)
    const undone = undoCanvas(history)
    expect(undone.present.find(item => item.type === 'arrow')).toBeUndefined()
    const redone = redoCanvas(undone)
    const restoredArrow = redone.present.find(item => item.type === 'arrow')
    expect(restoredArrow).toEqual(arrow('e1', 'a', 'b'))
  })

  it('restores a removed connector on undo of the deletion', () => {
    const before: CanvasElement[] = [node('a', 0), node('b', 200), arrow('e1', 'a', 'b')]
    const afterDelete: CanvasElement[] = before.filter(item => item.id !== 'e1')
    const history = commitCanvas(emptyCanvasHistory(before), afterDelete)
    expect(history.present.some(item => item.type === 'arrow')).toBe(false)
    const undone = undoCanvas(history)
    expect(undone.present.find(item => item.id === 'e1')).toEqual(arrow('e1', 'a', 'b'))
  })

  it('never touches anything outside the canvas array it is given', () => {
    const before: CanvasElement[] = [node('a', 0)]
    const after: CanvasElement[] = [node('a', 50)]
    const history = commitCanvas(emptyCanvasHistory(before), after)
    const undone = undoCanvas(history)
    expect(undone.present).not.toBe(after)
    expect(after).toEqual([node('a', 50)])
  })

  it('bounds past and future history so it cannot grow without limit', () => {
    let history = emptyCanvasHistory([node('a', 0)])
    for (let i = 1; i <= CANVAS_HISTORY_LIMIT + 10; i++) {
      const next = [node('a', i)]
      history = commitCanvas(history, next)
    }
    expect(history.past.length).toBeLessThanOrEqual(CANVAS_HISTORY_LIMIT)

    for (let i = 0; i < CANVAS_HISTORY_LIMIT + 10; i++) {
      const before = history
      history = undoCanvas(history)
      if (history === before) break
    }
    expect(history.future.length).toBeLessThanOrEqual(CANVAS_HISTORY_LIMIT)
  })

  describe('sameCanvas no-op dedupe', () => {
    it('treats deep-equal canvases as the same, regardless of array/object identity', () => {
      const a: CanvasElement[] = [node('a', 0)]
      const b: CanvasElement[] = [node('a', 0)]
      expect(a).not.toBe(b)
      expect(sameCanvas(a, b)).toBe(true)
    })

    it('does not push a history step when committing a deep-equal canvas', () => {
      const before: CanvasElement[] = [node('a', 0)]
      const history = emptyCanvasHistory(before)
      const noop = commitCanvas(history, [node('a', 0)])
      expect(noop).toBe(history)
      expect(noop.past).toHaveLength(0)
      expect(canUndoCanvas(noop)).toBe(false)
    })

    it('does not clear an existing redo stack on a no-op commit', () => {
      const v1: CanvasElement[] = [node('a', 0)]
      const v2: CanvasElement[] = [...v1, node('b', 100)]
      let history = commitCanvas(emptyCanvasHistory(v1), v2)
      history = undoCanvas(history) // present=v1, future=[v2]
      const noop = commitCanvas(history, [node('a', 0)]) // deep-equal to present
      expect(noop).toBe(history)
      expect(canRedoCanvas(noop)).toBe(true)
    })
  })
})
