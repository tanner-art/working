import { describe, expect, it } from 'vitest'
import { applyCanvasStrokeShape, applyCanvasStrokeSmoothing, canvasStrokeIntersectsLasso, canvasStrokeLength, createCanvasStrokeShapeRefinement, createCanvasStrokeSmoothingRefinement, isCanvasPointInLasso, isCanvasStrokeRefinement, normalizeCanvasLassoPoints, normalizeCanvasStrokePoints, previewCanvasStrokeShape, projectCanvasStroke, smoothCanvasStrokePoints } from './canvasStrokes'

describe('canvas stroke foundation', () => {
  it('copies finite, ordered canvas-space samples without resampling them', () => {
    const raw = [{ x: -0, y: 4 }, { x: 6, y: 13 }, { x: 15, y: 5 }]
    const normalized = normalizeCanvasStrokePoints(raw)
    expect(normalized).toEqual([{ x: 0, y: 4 }, { x: 6, y: 13 }, { x: 15, y: 5 }])
    expect(normalized).not.toBe(raw)
    expect(canvasStrokeLength(normalized!)).toBeCloseTo(Math.hypot(6, 9) + Math.hypot(9, -8))

    raw[1].x = 999
    expect(normalized![1].x).toBe(6)
  })

  it('fails closed for malformed, non-finite, and degenerate raw strokes', () => {
    expect(normalizeCanvasStrokePoints([{ x: 1, y: 2 }])).toBeNull()
    expect(normalizeCanvasStrokePoints([{ x: 1, y: 2 }, { x: 1, y: 2 }])).toBeNull()
    expect(normalizeCanvasStrokePoints([{ x: 1, y: 2 }, { x: Infinity, y: 3 }])).toBeNull()
    expect(normalizeCanvasStrokePoints([{ x: 1, y: 2, pressure: .5 }, { x: 3, y: 4 }])).toBeNull()
    expect(normalizeCanvasStrokePoints([{ x: '1', y: 2 }, { x: 3, y: 4 }])).toBeNull()
  })

  it('smooths deterministically while retaining endpoints and source samples', () => {
    const jagged = [{ x: 0, y: 0 }, { x: 3, y: 12 }, { x: 9, y: 0 }, { x: 12, y: 9 }]
    expect(smoothCanvasStrokePoints(jagged)).toEqual([
      { x: 0, y: 0 }, { x: 4, y: 4 }, { x: 8, y: 7 }, { x: 12, y: 9 },
    ])
    expect(smoothCanvasStrokePoints(jagged, 2)).toEqual([
      { x: 0, y: 0 }, { x: 4, y: 11 / 3 }, { x: 8, y: 20 / 3 }, { x: 12, y: 9 },
    ])
    expect(jagged).toEqual([{ x: 0, y: 0 }, { x: 3, y: 12 }, { x: 9, y: 0 }, { x: 12, y: 9 }])
  })

  it('projects raw or declared local smoothing without discarding raw expression', () => {
    const source = [{ x: 0, y: 0 }, { x: 6, y: 9 }, { x: 12, y: 0 }]
    const rawProjection = projectCanvasStroke(source, { kind: 'raw' })
    const smoothedProjection = projectCanvasStroke(source, { kind: 'smoothed', algorithm: 'moving-average-v1' })

    expect(rawProjection).toEqual(source)
    expect(rawProjection).not.toBe(source)
    expect(smoothedProjection).toEqual([{ x: 0, y: 0 }, { x: 6, y: 3 }, { x: 12, y: 0 }])
    expect(source).toEqual([{ x: 0, y: 0 }, { x: 6, y: 9 }, { x: 12, y: 0 }])
  })

  it('refuses malformed source data and unknown refinement algorithms', () => {
    expect(smoothCanvasStrokePoints([{ x: 0, y: 0 }, { x: NaN, y: 1 }])).toBeNull()
    expect(projectCanvasStroke([{ x: 0, y: 0 }, { x: 1, y: 1 }], { kind: 'smoothed', algorithm: 'unknown-v1' as 'moving-average-v1' })).toBeNull()
  })

  it('creates only JSON-safe smoothing metadata that leaves source samples unchanged', () => {
    const raw = [{ x: 0, y: 0 }, { x: 5, y: 11 }, { x: 10, y: 0 }]
    const refinement = createCanvasStrokeSmoothingRefinement('stroke-1', raw, '2026-09-22T12:00:00.000Z')
    expect(refinement).toEqual({
      sourceId: 'stroke-1', gesture: 'explicit-smoothing', appliedAt: '2026-09-22T12:00:00.000Z',
      algorithm: 'moving-average-v1', version: 1, result: { kind: 'smoothed', algorithm: 'moving-average-v1' },
    })
    expect(JSON.parse(JSON.stringify(refinement))).toEqual(refinement)
    expect(isCanvasStrokeRefinement(refinement)).toBe(true)
    expect(raw).toEqual([{ x: 0, y: 0 }, { x: 5, y: 11 }, { x: 10, y: 0 }])
    expect(createCanvasStrokeSmoothingRefinement('', raw, '2026-09-22T12:00:00.000Z')).toBeNull()
    expect(createCanvasStrokeSmoothingRefinement('stroke-1', raw, 'not-a-date')).toBeNull()
    expect(isCanvasStrokeRefinement({ ...refinement!, version: 2 })).toBe(false)
  })

  it('applies one reversible smoothing projection without accepting a stale second preview', () => {
    const stroke = { id: 'stroke-1', rawPoints: [{ x: 0, y: 0 }, { x: 5, y: 11 }, { x: 10, y: 0 }] }
    const smoothed = applyCanvasStrokeSmoothing(stroke, '2026-09-22T12:00:00.000Z')!
    expect(smoothed.rawPoints).toEqual(stroke.rawPoints)
    expect(smoothed.rawPoints).toBe(stroke.rawPoints)
    expect(smoothed.projection).toEqual({ kind: 'smoothed', algorithm: 'moving-average-v1' })
    expect(smoothed.refinements).toHaveLength(1)
    expect(applyCanvasStrokeSmoothing(smoothed, '2026-09-22T12:01:00.000Z')).toBeNull()
  })

  it('offers and applies a recognized shape projection without changing raw points', () => {
    const raw = [{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 40, y: 0 }]
    const preview = previewCanvasStrokeShape(raw)
    expect(preview).toMatchObject({ kind: 'shape', shape: 'line', geometry: { start: { x: 0, y: 0 }, end: { x: 40, y: 0 } } })
    const refinement = createCanvasStrokeShapeRefinement('stroke-1', raw, '2026-09-22T12:00:00.000Z')!
    expect(refinement).toMatchObject({ gesture: 'explicit-shape-conversion', sourceId: 'stroke-1', result: preview })
    expect(isCanvasStrokeRefinement(refinement)).toBe(true)
    const shaped = applyCanvasStrokeShape({ id: 'stroke-1', rawPoints: raw }, '2026-09-22T12:00:00.000Z')!
    expect(shaped.rawPoints).toBe(raw)
    expect(projectCanvasStroke(shaped.rawPoints, shaped.projection)).toEqual([{ x: 0, y: 0 }, { x: 40, y: 0 }])
    expect(applyCanvasStrokeShape(shaped, '2026-09-22T12:01:00.000Z')).toBeNull()
  })

  it('omits shape conversion when the smoothed stroke has no confident match', () => {
    const raw = [{ x: 0, y: 0 }, { x: 12, y: 18 }, { x: 24, y: -12 }, { x: 36, y: 18 }, { x: 48, y: 0 }]
    expect(previewCanvasStrokeShape(raw)).toBeNull()
    expect(createCanvasStrokeShapeRefinement('stroke-1', raw, '2026-09-22T12:00:00.000Z')).toBeNull()
  })

  it('selects strokes contained in, crossing, or touching a closed lasso', () => {
    const lasso = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }]
    expect(canvasStrokeIntersectsLasso([{ x: 2, y: 2 }, { x: 8, y: 8 }], lasso)).toBe(true)
    expect(canvasStrokeIntersectsLasso([{ x: -2, y: 5 }, { x: 12, y: 5 }], lasso)).toBe(true)
    expect(canvasStrokeIntersectsLasso([{ x: -2, y: 0 }, { x: 0, y: 0 }], lasso)).toBe(true)
    expect(canvasStrokeIntersectsLasso([{ x: -4, y: -2 }, { x: -1, y: -2 }], lasso)).toBe(false)
    expect(isCanvasPointInLasso({ x: 0, y: 7 }, lasso)).toBe(true)
  })

  it('rejects tap-like, collinear, and malformed lasso paths', () => {
    expect(normalizeCanvasLassoPoints([{ x: 0, y: 0 }, { x: 4, y: 0 }])).toBeNull()
    expect(normalizeCanvasLassoPoints([{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 8, y: 0 }])).toBeNull()
    expect(normalizeCanvasLassoPoints([{ x: 0, y: 0 }, { x: Infinity, y: 1 }, { x: 1, y: 2 }])).toBeNull()
    expect(canvasStrokeIntersectsLasso([{ x: 1, y: 1 }, { x: 2, y: 2 }], [{ x: 0, y: 0 }, { x: 1, y: 0 }])).toBe(false)
  })
})
