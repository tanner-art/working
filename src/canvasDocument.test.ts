import { describe, expect, it } from 'vitest'
import type { CanvasElement } from './domain'
import { isCanvasElements, toggleCanvasNodeVariant } from './canvasDocument'
import { commitCanvas, emptyCanvasHistory, redoCanvas, undoCanvas } from './canvasHistory'
import { createCanvasStrokeShapeRefinement, createCanvasStrokeSmoothingRefinement } from './canvasStrokes'

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

  it('accepts valid visual colors and rejects malformed or misplaced colors', () => {
    const arrow: CanvasElement = { id: 'edge', type: 'arrow', x: 0, y: 0, fromId: 'a', toId: 'b' }
    expect(isCanvasElements([{ ...textNode, fillColor: '#f3dcdf' }])).toBe(true)
    expect(isCanvasElements([{ ...textNode, fillColor: 'red' }])).toBe(false)
    expect(isCanvasElements([{ ...textNode, connectionColor: '#123456' }])).toBe(false)
    expect(isCanvasElements([{ ...arrow, connectionColor: '#316b8a' }])).toBe(true)
    expect(isCanvasElements([{ ...arrow, connectionColor: '#xyzxyz' }])).toBe(false)
    expect(isCanvasElements([{ ...arrow, fillColor: '#ffffff' }])).toBe(false)
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

  it('accepts a reversible smoothing projection only when it names the preserved source stroke', () => {
    const refinement = createCanvasStrokeSmoothingRefinement(stroke.id, stroke.rawPoints, '2026-09-22T12:00:00.000Z')!
    const smoothed: CanvasElement = { ...stroke, projection: refinement.result, refinements: [refinement] }
    expect(isCanvasElements([smoothed])).toBe(true)
    expect(isCanvasElements([{ ...smoothed, refinements: [{ ...refinement, sourceId: 'other-stroke' }] }])).toBe(false)
    expect(isCanvasElements([{ ...smoothed, projection: undefined }])).toBe(false)
    expect(isCanvasElements([{ ...smoothed, refinements: [{ ...refinement, appliedAt: 'not-a-date' }] }])).toBe(false)
    expect(isCanvasElements([{ ...smoothed, type: 'text' }])).toBe(false)
  })

  it('round-trips a recognized shape projection only with matching refinement metadata', () => {
    const refinement = createCanvasStrokeShapeRefinement(stroke.id, [{ x: 10, y: 20 }, { x: 22, y: 21 }], '2026-09-22T12:00:00.000Z')!
    const shaped: CanvasElement = { ...stroke, rawPoints: [{ x: 10, y: 20 }, { x: 22, y: 21 }], projection: refinement.result, refinements: [refinement] }
    expect(isCanvasElements([shaped])).toBe(true)
    expect(isCanvasElements([{ ...shaped, projection: { ...refinement.result, geometry: { start: { x: 10, y: 20 }, end: { x: 18, y: 21 } } } }])).toBe(false)
    expect(isCanvasElements([{ ...shaped, rawPoints: [{ x: 10, y: 20 }, { x: 30, y: 20 }, { x: 30, y: 40 }, { x: 10, y: 40 }, { x: 10, y: 20 }] }])).toBe(false)
  })
})
