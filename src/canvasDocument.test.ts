import { describe, expect, it } from 'vitest'
import type { CanvasElement } from './domain'
import { isCanvasElements, toggleCanvasNodeVariant } from './canvasDocument'
import { commitCanvas, emptyCanvasHistory, redoCanvas, undoCanvas } from './canvasHistory'

const textNode: CanvasElement = { id: 'note', type: 'text', x: 10, y: 20, text: 'First item\n\nThird item' }

describe('canvas bulleted-list variant', () => {
  it('toggles only a text node and keeps its original text intact', () => {
    const container: CanvasElement = { id: 'group', type: 'container', x: 0, y: 0, text: 'Group' }
    const listed = toggleCanvasNodeVariant([textNode, container], textNode.id)
    expect(listed).toEqual([{ ...textNode, nodeVariant: 'bulleted-list' }, container])
    expect(toggleCanvasNodeVariant(listed, textNode.id)).toEqual([textNode, container])
    expect(toggleCanvasNodeVariant([textNode, container], container.id)).toEqual([textNode, container])
  })

  it('keeps the variant through undo and redo as one canvas edit', () => {
    const listed = toggleCanvasNodeVariant([textNode], textNode.id)
    const history = commitCanvas(emptyCanvasHistory([textNode]), listed)
    expect(undoCanvas(history).present).toEqual([textNode])
    expect(redoCanvas(undoCanvas(history)).present).toEqual(listed)
  })

  it('accepts legacy text nodes but fails closed for invalid or misplaced variants', () => {
    expect(isCanvasElements([textNode])).toBe(true)
    expect(isCanvasElements([{ ...textNode, nodeVariant: 'bulleted-list' }])).toBe(true)
    expect(isCanvasElements([{ ...textNode, nodeVariant: 'numbered-list' }])).toBe(false)
    expect(isCanvasElements([{ ...textNode, type: 'container', nodeVariant: 'bulleted-list' }])).toBe(false)
    expect(isCanvasElements([{ id: 'edge', type: 'arrow', x: 0, y: 0, fromId: 'a', toId: 'b', nodeVariant: 'bulleted-list' }])).toBe(false)
  })
})

describe('freehand canvas elements', () => {
  const stroke: CanvasElement = { id: 'stroke', type: 'freehand', x: 10, y: 20, rawPoints: [{ x: 10, y: 20 }, { x: 15, y: 24 }, { x: 22, y: 21 }] }

  it('accepts only a raw, finite non-degenerate stroke payload', () => {
    expect(isCanvasElements([stroke])).toBe(true)
    expect(isCanvasElements([{ ...stroke, rawPoints: [{ x: 10, y: 20 }] }])).toBe(false)
    expect(isCanvasElements([{ ...stroke, rawPoints: [{ x: 10, y: 20 }, { x: Infinity, y: 24 }] }])).toBe(false)
    expect(isCanvasElements([{ ...stroke, rawPoints: [{ x: 10, y: 20 }, { x: 10, y: 20 }] }])).toBe(false)
    expect(isCanvasElements([{ ...stroke, text: 'not a stroke' }])).toBe(false)
    expect(isCanvasElements([{ ...stroke, pressure: .5 }])).toBe(false)
  })
})
