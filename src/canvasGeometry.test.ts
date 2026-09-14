import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CanvasElement } from './domain'
import { canvasSize, canvasConnector, convertCanvasNode, resizeCanvasNode } from './canvasGeometry'
import { commitCanvas, emptyCanvasHistory, redoCanvas, undoCanvas } from './canvasHistory'
import { loadStateResult, saveState } from './store'

const nodes: CanvasElement[] = [
  { id: 'a', type: 'text', x: -30, y: 25, text: 'Original thought\nwith content', width: 190, height: 100 },
  { id: 'b', type: 'container', x: 500, y: 400, text: 'Group', width: 320, height: 210 },
  { id: 'link', type: 'arrow', x: 0, y: 0, fromId: 'a', toId: 'b' },
]
afterEach(() => vi.unstubAllGlobals())
describe('canvas size and conversion', () => {
  it('resizes only the target geometry without mutating original expression or connector IDs', () => {
    const before = structuredClone(nodes)
    const resized = resizeCanvasNode(nodes, 'a', 340, 230)
    expect(resized[0]).toEqual({ ...nodes[0], width: 340, height: 230 })
    expect(resized[1]).toBe(nodes[1])
    expect(resized[2]).toBe(nodes[2])
    expect(nodes).toEqual(before)
    expect(canvasConnector(resized[0], resized[1])).toEqual({ x1: 140, y1: 255, x2: 660, y2: 400 })
  })
  it('converts both supported forms while preserving text, position, dimensions and ports', () => {
    const converted = convertCanvasNode(nodes, 'a', 'container')
    expect(converted[0]).toEqual({ ...nodes[0], type: 'container' })
    expect(canvasConnector(converted[0], converted[1])).toEqual(canvasConnector(nodes[0], nodes[1]))
    expect(convertCanvasNode(converted, 'a', 'text')).toEqual(nodes)
    expect(convertCanvasNode(nodes, 'b', 'text')[1]).toEqual({ ...nodes[1], type: 'text' })
    expect(converted[2]).toBe(nodes[2])
  })
  it('keeps legacy implicit dimensions stable across conversion', () => {
    const legacy: CanvasElement = { id: 'legacy', type: 'text', x: 10, y: 30, text: 'Keep me' }
    const converted = convertCanvasNode([legacy], legacy.id, 'container')[0]
    expect(canvasSize(converted)).toEqual(canvasSize(legacy))
    expect(converted.text).toBe(legacy.text)
  })
  it('clamps both axes, rounds pixels, rejects non-finite requests and never resizes arrows', () => {
    expect(resizeCanvasNode(nodes, 'a', -5, 99999)[0]).toMatchObject({ width: 120, height: 900 })
    expect(resizeCanvasNode(nodes, 'a', 99999, -5)[0]).toMatchObject({ width: 1200, height: 100 })
    expect(resizeCanvasNode(nodes, 'a', 150.3, 160.8)[0]).toMatchObject({ width: 150, height: 161 })
    for (const value of [NaN, Infinity, -Infinity]) {
      expect(resizeCanvasNode(nodes, 'a', value, 200)).toBe(nodes)
      expect(resizeCanvasNode(nodes, 'a', 200, value)).toBe(nodes)
    }
    expect(resizeCanvasNode(nodes, 'link', 400, 400)).toEqual(nodes)
    expect(convertCanvasNode(nodes, 'link', 'text')).toEqual(nodes)
  })
  it('undoes and redoes atomic resize and conversion with exact connector restoration', () => {
    const resized = resizeCanvasNode(nodes, 'a', 400, 300)
    const converted = convertCanvasNode(resized, 'a', 'container')
    const first = commitCanvas(emptyCanvasHistory(nodes), resized)
    const second = commitCanvas(first, converted)
    expect(second.past).toHaveLength(2)
    expect(undoCanvas(second).present).toEqual(resized)
    expect(undoCanvas(undoCanvas(second)).present).toEqual(nodes)
    expect(redoCanvas(redoCanvas(undoCanvas(undoCanvas(second)))).present).toEqual(converted)
    expect(canvasConnector(undoCanvas(undoCanvas(second)).present[0], nodes[1])).toEqual(canvasConnector(nodes[0], nodes[1]))
    expect(commitCanvas(first, resizeCanvasNode(resized, 'a', 400, 300))).toBe(first)
    expect(commitCanvas(first, convertCanvasNode(resized, 'a', 'text'))).toBe(first)
    expect(commitCanvas(undoCanvas(second), resizeCanvasNode(resized, 'a', 500, 300)).future).toEqual([])
  })
  it('persists edits and undo/redo without changing capture or semantic evidence; reload starts fresh history', () => {
    let raw: string | null = null
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const initial = loadStateResult().state
    const evidence = structuredClone(initial.model!)
    let history = emptyCanvasHistory(initial.canvas)
    history = commitCanvas(history, resizeCanvasNode(initial.canvas, 'canvas-idea', 420, 240))
    history = commitCanvas(history, convertCanvasNode(history.present, 'canvas-idea', 'container'))
    for (const snapshot of [history, undoCanvas(history), redoCanvas(undoCanvas(history))]) {
      expect(saveState({ ...initial, canvas: snapshot.present })).toBeUndefined()
      const loaded = loadStateResult()
      expect(loaded.error).toBeUndefined()
      expect(loaded.state.canvas).toEqual(snapshot.present)
      expect(loaded.state.model).toEqual({ ...evidence, canvas: snapshot.present })
      expect(emptyCanvasHistory(loaded.state.canvas).past).toEqual([])
    }
  })
})
