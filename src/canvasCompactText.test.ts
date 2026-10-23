import { describe, expect, it } from 'vitest'
import { isCanvasElements, isCanvasViewport, newCanvasElement } from './canvasDocument'
import { canvasSize, fitCanvasText, resizeCanvasNode, convertCanvasNode } from './canvasGeometry'
import { commitCanvas, emptyCanvasHistory, undoCanvas } from './canvasHistory'

describe('compact Canvas text without rewriting historical geometry', () => {
  it('sizes new plain text around words and grows for multiline text', () => {
    const node = { ...newCanvasElement('text', 10, 20), text: 'Dad' }
    expect(node.autoSize).toBe(true)
    expect(canvasSize(node)).toEqual({ width: 58, height: 42 })
    expect(canvasSize({ ...node, text: 'Dad\nRepair Foreman' }).height).toBe(66)
    expect(canvasSize({ ...node, text: 'Long '.repeat(500) }).width).toBe(320)
    expect(isCanvasElements([node])).toBe(true)
  })
  it('keeps legacy dimensions and only fits existing text on explicit request', () => {
    const node = { id: 'old', type: 'text' as const, x: 3, y: 4, text: 'Dad' }
    expect(canvasSize(node)).toEqual({ width: 190, height: 100 })
    const fitted = fitCanvasText([node], 'old')
    expect(canvasSize(fitted[0])).toEqual({ width: 58, height: 42 })
    expect(fitted[0]).toMatchObject({ id: 'old', x: 3, y: 4, text: 'Dad' })
    expect(undoCanvas(commitCanvas(emptyCanvasHistory([node]), fitted)).present).toEqual([node])
  })
  it('switches to manual size on resize and clears text-only sizing on shape conversion', () => {
    const node = newCanvasElement('text', 10, 20)
    const resized = resizeCanvasNode([node], node.id, 80, 60)[0]
    expect(resized.autoSize).toBe(false)
    expect(canvasSize({ ...resized, text: 'Long text'.repeat(100) })).toEqual({ width: 80, height: 60 })
    expect(convertCanvasNode([node], node.id, 'text')[0].autoSize).toBe(true)
    const converted = convertCanvasNode([node], node.id, 'ellipse')
    expect(converted[0].autoSize).toBeUndefined()
    expect(isCanvasElements(converted)).toBe(true)
  })
  it('validates the expanded zoom range and rejects malformed sizing', () => {
    for (const scale of [.2, .55, 1, 1.6, 4]) expect(isCanvasViewport({ x: 3, y: -4, scale })).toBe(true)
    for (const scale of [0, .19, 4.01, Infinity]) expect(isCanvasViewport({ x: 3, y: -4, scale })).toBe(false)
    expect(isCanvasElements([{ ...newCanvasElement('text', 0, 0), autoSize: 'yes' }])).toBe(false)
  })
})
