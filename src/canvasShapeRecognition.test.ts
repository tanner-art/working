import { describe, expect, it } from 'vitest'
import { recognizeCanvasStrokeShape } from './canvasShapeRecognition'

describe('canvas shape recognition', () => {
  it('recognizes a straight stroke and preserves an independent source copy', () => {
    const raw = [{ x: 0, y: 0 }, { x: 15, y: .4 }, { x: 30, y: -.2 }, { x: 50, y: 0 }]
    const result = recognizeCanvasStrokeShape(raw)
    expect(result).toMatchObject({ kind: 'line', geometry: { start: { x: 0, y: 0 }, end: { x: 50, y: 0 } } })
    expect(result!.confidence).toBeGreaterThan(.9)
    raw[1].x = 999
    expect(result!.sourcePoints[1].x).toBe(15)
  })

  it('recognizes closed, axis-aligned rectangles only when the outline follows their edges', () => {
    const result = recognizeCanvasStrokeShape([
      { x: 0, y: 0 }, { x: 20, y: 0 }, { x: 40, y: 0 }, { x: 40, y: 15 }, { x: 40, y: 30 }, { x: 20, y: 30 }, { x: 0, y: 30 }, { x: 0, y: 15 }, { x: 0, y: 0 },
    ])
    expect(result).toMatchObject({ kind: 'rectangle', geometry: { x: 0, y: 0, width: 40, height: 30 } })
  })

  it('recognizes ellipse and triangle geometry with finite JSON-safe numbers', () => {
    const ellipse = recognizeCanvasStrokeShape([
      { x: 40, y: 10 }, { x: 54, y: 13 }, { x: 60, y: 25 }, { x: 54, y: 37 }, { x: 40, y: 40 }, { x: 26, y: 37 }, { x: 20, y: 25 }, { x: 26, y: 13 }, { x: 40, y: 10 },
    ])
    const triangle = recognizeCanvasStrokeShape([
      { x: 20, y: 0 }, { x: 30, y: 20 }, { x: 40, y: 40 }, { x: 20, y: 40 }, { x: 0, y: 40 }, { x: 10, y: 20 }, { x: 20, y: 0 },
    ])
    expect(ellipse).toMatchObject({ kind: 'ellipse', geometry: { center: { x: 40, y: 25 }, radiusX: 20, radiusY: 15 } })
    expect(triangle?.kind).toBe('triangle')
    expect(JSON.stringify([ellipse, triangle])).not.toMatch(/NaN|Infinity/)
  })

  it('recognizes a minimally sampled closed triangle', () => {
    const result = recognizeCanvasStrokeShape([{ x: 20, y: 0 }, { x: 40, y: 40 }, { x: 0, y: 40 }, { x: 20, y: 0 }])
    expect(result?.kind).toBe('triangle')
    if (result?.kind === 'triangle') expect(result.geometry.points).toHaveLength(3)
  })

  it('fails closed for degenerate data, noisy marks, and ambiguous near-shapes', () => {
    expect(recognizeCanvasStrokeShape([{ x: 0, y: 0 }, { x: 0, y: 0 }])).toBeNull()
    expect(recognizeCanvasStrokeShape([{ x: 0, y: 0 }, { x: Infinity, y: 2 }])).toBeNull()
    expect(recognizeCanvasStrokeShape([{ x: 0, y: 0 }, { x: 20, y: 20 }, { x: 0, y: 20 }, { x: 20, y: 0 }])).toBeNull()
    expect(recognizeCanvasStrokeShape([{ x: 0, y: 0 }, { x: 12, y: 18 }, { x: 24, y: -12 }, { x: 36, y: 18 }, { x: 48, y: 0 }])).toBeNull()
    expect(recognizeCanvasStrokeShape([{ x: 0, y: 0 }, { x: 30, y: 2 }, { x: 31, y: 30 }, { x: 2, y: 28 }, { x: 10, y: 12 }, { x: 0, y: 0 }])).toBeNull()
  })
})
