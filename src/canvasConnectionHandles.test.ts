import { describe, expect, it } from 'vitest'
import type { CanvasElement } from './domain'
import { isCanvasElements } from './canvasDocument'
import { canvasConnectorPath, connectionEndpoints, connectionPathData, didMoveCanvasConnectionHandle, normalizeCurveHandle, normalizePerimeterAnchor, perimeterAnchorAtPoint, projectPerimeterAnchor, resizeCanvasNode, updateCanvasConnection, updateCanvasConnectionAnchors } from './canvasGeometry'
import { commitCanvas, emptyCanvasHistory, redoCanvas, undoCanvas } from './canvasHistory'

const source: CanvasElement = { id: 'source', type: 'text', x: 20, y: 40, width: 240, height: 160 }
const target: CanvasElement = { id: 'target', type: 'text', x: 520, y: 120, width: 180, height: 140 }
const arrow: CanvasElement = { id: 'edge', type: 'arrow', x: 0, y: 0, fromId: source.id, toId: target.id, connectionPath: 'curved' }
const elements = [source, target, arrow]

function normalized(node: CanvasElement, point: { x: number; y: number }) {
  const width = node.width!, height = node.height!
  return { x: (point.x - node.x - width / 2) / (width / 2), y: (point.y - node.y - height / 2) / (height / 2) }
}

describe('editable canvas connection geometry', () => {
  it.each(['rectangle', 'rounded-rectangle', 'ellipse', 'diamond'] as const)('projects full-circle anchors to the %s boundary and keeps them responsive to resize', shape => {
    const node = { ...source, shape, width: 300, height: 180 }
    for (const anchor of [{ x: 0, y: .25 }, { x: 1, y: .75 }, { x: .3, y: 0 }, { x: .7, y: 1 }]) {
      const projected = projectPerimeterAnchor(node, anchor), point = normalized(node, projected)
      if (shape === 'ellipse') expect(point.x * point.x + point.y * point.y).toBeCloseTo(1, 8)
      else if (shape === 'diamond') expect(Math.abs(point.x) + Math.abs(point.y)).toBeCloseTo(1, 8)
      else if (shape === 'rounded-rectangle') expect(Math.abs(point.x) <= 1 && Math.abs(point.y) <= 1).toBe(true)
      else expect(Math.max(Math.abs(point.x), Math.abs(point.y))).toBeCloseTo(1, 8)
    }
    const first = projectPerimeterAnchor(node, { x: 1, y: .5 })
    const resized = resizeCanvasNode([node], node.id, 600, 300)[0]
    const second = projectPerimeterAnchor(resized, { x: 1, y: .5 })
    expect(second.x - resized.x).toBeGreaterThan(first.x - node.x)
  })

  it('supports containers, clamps finite input, and fails closed for non-finite input', () => {
    const container: CanvasElement = { ...source, type: 'container', width: 320, height: 210 }
    const point = projectPerimeterAnchor(container, { x: -3, y: 2 })
    expect(point.y).toBe(container.y + container.height!)
    expect(point.x).toBeGreaterThan(container.x)
    expect(normalizePerimeterAnchor({ x: -3, y: 2 })).toEqual({ x: 0, y: 1 })
    expect(normalizePerimeterAnchor({ x: NaN, y: .5 })).toBeUndefined()
    expect(normalizePerimeterAnchor({ x: Infinity, y: .5 })).toBeUndefined()
    expect(normalizeCurveHandle({ x: -4, y: 3 })).toEqual({ x: -1.5, y: 1.5 })
    expect(normalizeCurveHandle({ x: 0, y: -Infinity })).toBeUndefined()
  })

  it('retains byte-for-byte legacy paths until an anchor or handle is supplied', () => {
    expect(canvasConnectorPath(source, target)).toBe('M 140 200 L 610 120')
    expect(canvasConnectorPath(source, target, 'curved')).toBe('M 140 200 C 140 248, 610 72, 610 120')
    const endpoints = connectionEndpoints(source, target, { sourceAnchor: { x: 1, y: .5 }, targetAnchor: { x: 0, y: .5 } })
    expect(endpoints).toEqual({ x1: 260, y1: 120, x2: 520, y2: 190 })
    const path = connectionPathData(source, target, { connectionPath: 'curved', sourceAnchor: { x: 1, y: .5 }, targetAnchor: { x: 0, y: .5 }, curveHandle: { x: 0, y: .5 } })
    expect(path).toBe('M 260 120 Q 390 190, 520 190')
  })

  it('updates anchors and curved handles atomically, while rejecting invalid routes', () => {
    const sourceMoved = updateCanvasConnectionAnchors(elements, arrow.id, { sourceAnchor: { x: 1, y: .5 }, targetAnchor: { x: 0, y: .5 } })
    expect(sourceMoved).not.toBe(elements)
    expect(sourceMoved[2]).toMatchObject({ sourceAnchor: { x: 1, y: .5 }, targetAnchor: { x: 0, y: .5 } })
    const curved = updateCanvasConnectionAnchors(sourceMoved, arrow.id, { curveHandle: { x: .1, y: -.3 } })
    expect(curved[2]).toMatchObject({ curveHandle: { x: .1, y: -.3 } })
    const history = commitCanvas(commitCanvas(emptyCanvasHistory(elements), sourceMoved), curved)
    expect(history.past).toHaveLength(2)
    expect(undoCanvas(history).present).toEqual(sourceMoved)
    expect(undoCanvas(undoCanvas(history)).present).toEqual(elements)
    expect(redoCanvas(redoCanvas(undoCanvas(undoCanvas(history)))).present).toEqual(curved)
    const overlapping = [{ ...source, width: 500 }, { ...target, x: 300 }, arrow]
    expect(updateCanvasConnectionAnchors(overlapping, arrow.id, { targetAnchor: { x: 0, y: .5 } })).toBe(overlapping)
    const inwardSource = updateCanvasConnectionAnchors(elements, arrow.id, { sourceAnchor: { x: 0, y: .5 } })
    expect(updateCanvasConnectionAnchors(inwardSource, arrow.id, { targetAnchor: { x: 0, y: .5 } })).toBe(inwardSource)
  })

  it('does not create an anchor or history entry for a pointer down/up that never moves', () => {
    expect(didMoveCanvasConnectionHandle({ x: 100, y: 200 }, { x: 100, y: 200 })).toBe(false)
    expect(didMoveCanvasConnectionHandle({ x: 100, y: 200 }, { x: 100.4, y: 200 })).toBe(false)
    expect(didMoveCanvasConnectionHandle({ x: 100, y: 200 }, { x: 100.5, y: 200 })).toBe(true)
    const noAnchor = updateCanvasConnectionAnchors(elements, arrow.id, { sourceAnchor: { x: .5, y: 1 } })
    expect(noAnchor).toBe(elements)
    const history = emptyCanvasHistory(elements)
    expect(commitCanvas(history, noAnchor)).toBe(history)
  })

  it('derives a perimeter ray from a pointer and clears curve data when returned to straight', () => {
    expect(perimeterAnchorAtPoint(source, { x: 1000, y: 120 })).toEqual({ x: 1, y: .5 })
    const curved = updateCanvasConnectionAnchors(elements, arrow.id, { curveHandle: { x: .4, y: -.2 } })
    const straight = updateCanvasConnection(curved, arrow.id, { connectionPath: 'straight' })
    expect(straight[2]).not.toHaveProperty('curveHandle')
    expect(commitCanvas(emptyCanvasHistory(straight), straight)).toEqual(emptyCanvasHistory(straight))
  })

  it('accepts legacy arrows and valid new fields while rejecting malformed, self, and missing endpoint data', () => {
    expect(isCanvasElements([source, target, { ...arrow, sourceAnchor: { x: 1, y: .5 }, targetAnchor: { x: 0, y: .5 }, curveHandle: { x: 1.5, y: -1.5 } }])).toBe(true)
    expect(isCanvasElements([source, target, { ...arrow, sourceAnchor: { x: NaN, y: .5 } }])).toBe(false)
    expect(isCanvasElements([source, target, { ...arrow, targetAnchor: { x: 1.1, y: .5 } }])).toBe(false)
    expect(isCanvasElements([source, target, { ...arrow, connectionPath: 'straight', curveHandle: { x: 0, y: 0 } }])).toBe(false)
    expect(isCanvasElements([source, target, { ...arrow, sourceAnchor: { x: 1, y: .5 }, toId: source.id }])).toBe(false)
    expect(isCanvasElements([source, { ...arrow, sourceAnchor: { x: 1, y: .5 }, toId: 'missing' }])).toBe(false)
  })
})
