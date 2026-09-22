/**
 * A canvas-space point captured from a pen or lasso gesture. It deliberately
 * contains only JSON numbers: pressure, screen coordinates, and timestamps are
 * outside the first stroke format so saved raw expression is portable.
 */
export interface CanvasStrokePoint { x: number; y: number }
import { CANVAS_SHAPE_RECOGNITION_VERSION, recognizeCanvasStrokeShape, type CanvasEllipseGeometry, type CanvasLineGeometry, type CanvasRecognizedShapeKind, type CanvasRectangleGeometry, type CanvasTriangleGeometry } from './canvasShapeRecognition'

export type CanvasStrokeProjection =
  | { kind: 'raw' }
  | { kind: 'smoothed'; algorithm: 'moving-average-v1'; iterations?: 1 | 2 | 3 }
  | { kind: 'shape'; algorithm: typeof CANVAS_SHAPE_RECOGNITION_VERSION; shape: 'line'; geometry: CanvasLineGeometry }
  | { kind: 'shape'; algorithm: typeof CANVAS_SHAPE_RECOGNITION_VERSION; shape: 'rectangle'; geometry: CanvasRectangleGeometry }
  | { kind: 'shape'; algorithm: typeof CANVAS_SHAPE_RECOGNITION_VERSION; shape: 'ellipse'; geometry: CanvasEllipseGeometry }
  | { kind: 'shape'; algorithm: typeof CANVAS_SHAPE_RECOGNITION_VERSION; shape: 'triangle'; geometry: CanvasTriangleGeometry }

export const STROKE_SMOOTHING_ALGORITHM = 'moving-average-v1' as const
export const STROKE_SMOOTHING_VERSION = 1 as const

/**
 * An accepted local projection. The source stroke remains the element's
 * `rawPoints`; this record explains the active, reversible presentation.
 */
export interface CanvasStrokeRefinement {
  sourceId: string
  gesture: 'explicit-smoothing' | 'explicit-shape-conversion'
  appliedAt: string
  algorithm: typeof STROKE_SMOOTHING_ALGORITHM | typeof CANVAS_SHAPE_RECOGNITION_VERSION
  version: typeof STROKE_SMOOTHING_VERSION | typeof CANVAS_SHAPE_RECOGNITION_VERSION
  result: Exclude<CanvasStrokeProjection, { kind: 'raw' }>
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const normalizeNumber = (value: number) => Object.is(value, -0) ? 0 : value

export function isCanvasStrokeProjection(value: unknown): value is CanvasStrokeProjection {
  if (!isRecord(value)) return false
  if (value.kind === 'raw') return Object.keys(value).length === 1
  return value.kind === 'smoothed' &&
    Object.keys(value).every(key => ['kind', 'algorithm', 'iterations'].includes(key)) &&
    value.algorithm === STROKE_SMOOTHING_ALGORITHM &&
    (value.iterations === undefined || value.iterations === 1 || value.iterations === 2 || value.iterations === 3)
    || value.kind === 'shape' && value.algorithm === CANVAS_SHAPE_RECOGNITION_VERSION && isShapeProjection(value)
}

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const isPoint = (value: unknown): value is CanvasStrokePoint => isRecord(value) && Object.keys(value).length === 2 && isFiniteNumber(value.x) && isFiniteNumber(value.y)
const isShapeProjection = (value: Record<string, unknown>) => {
  if (!Object.keys(value).every(key => ['kind', 'algorithm', 'shape', 'geometry'].includes(key))) return false
  const geometry = value.geometry
  if (!isRecord(geometry)) return false
  if (value.shape === 'line') return Object.keys(geometry).length === 2 && isPoint(geometry.start) && isPoint(geometry.end) && Math.hypot(geometry.start.x - geometry.end.x, geometry.start.y - geometry.end.y) > 0
  if (value.shape === 'rectangle') return Object.keys(geometry).length === 4 && isFiniteNumber(geometry.x) && isFiniteNumber(geometry.y) && isFiniteNumber(geometry.width) && isFiniteNumber(geometry.height) && geometry.width > 0 && geometry.height > 0
  if (value.shape === 'ellipse') return Object.keys(geometry).length === 3 && isPoint(geometry.center) && isFiniteNumber(geometry.radiusX) && isFiniteNumber(geometry.radiusY) && geometry.radiusX > 0 && geometry.radiusY > 0
  return value.shape === 'triangle' && Object.keys(geometry).length === 1 && Array.isArray(geometry.points) && geometry.points.length === 3 && geometry.points.every(isPoint) && Math.abs(polygonArea(geometry.points)) > 1e-9
}

export function isCanvasStrokeRefinement(value: unknown): value is CanvasStrokeRefinement {
  if (!isRecord(value) || !Object.keys(value).every(key => ['sourceId', 'gesture', 'appliedAt', 'algorithm', 'version', 'result'].includes(key))) return false
  if (typeof value.sourceId !== 'string' || !value.sourceId || typeof value.appliedAt !== 'string' || !Number.isFinite(Date.parse(value.appliedAt)) || !isCanvasStrokeProjection(value.result) || value.result.kind === 'raw') return false
  return value.gesture === 'explicit-smoothing'
    ? value.algorithm === STROKE_SMOOTHING_ALGORITHM && value.version === STROKE_SMOOTHING_VERSION && value.result.kind === 'smoothed'
    : value.gesture === 'explicit-shape-conversion' && value.algorithm === CANVAS_SHAPE_RECOGNITION_VERSION && value.version === CANVAS_SHAPE_RECOGNITION_VERSION && value.result.kind === 'shape'
}

/** The active render projection must be exactly the latest recorded result. */
export function isActiveCanvasStrokeRefinement(refinement: unknown, projection: unknown): boolean {
  return isCanvasStrokeRefinement(refinement) && isCanvasStrokeProjection(projection) && projection.kind !== 'raw' && JSON.stringify(refinement.result) === JSON.stringify(projection)
}

/** Creates validated, JSON-safe metadata for one user-accepted smoothing action. */
export function createCanvasStrokeSmoothingRefinement(sourceId: unknown, rawPoints: unknown, appliedAt: unknown): CanvasStrokeRefinement | null {
  if (typeof sourceId !== 'string' || !sourceId || typeof appliedAt !== 'string' || !Number.isFinite(Date.parse(appliedAt)) || !normalizeCanvasStrokePoints(rawPoints)) return null
  return {
    sourceId,
    gesture: 'explicit-smoothing',
    appliedAt,
    algorithm: STROKE_SMOOTHING_ALGORITHM,
    version: STROKE_SMOOTHING_VERSION,
    result: { kind: 'smoothed', algorithm: STROKE_SMOOTHING_ALGORITHM },
  }
}

/**
 * Produces a new element-shaped value for one accepted refinement. It never
 * edits or replaces raw points, and refuses to stack a stale second preview.
 */
export function applyCanvasStrokeSmoothing<T extends { id: string; rawPoints?: unknown; projection?: CanvasStrokeProjection; refinements?: CanvasStrokeRefinement[] }>(stroke: T, appliedAt: unknown): (T & { projection: Extract<CanvasStrokeProjection, { kind: 'smoothed' }>; refinements: CanvasStrokeRefinement[] }) | null {
  if (stroke.projection !== undefined) return null
  const refinement = createCanvasStrokeSmoothingRefinement(stroke.id, stroke.rawPoints, appliedAt)
  if (!refinement || refinement.result.kind !== 'smoothed') return null
  return { ...stroke, projection: refinement.result, refinements: [...(stroke.refinements ?? []), refinement] }
}

/** Returns a shape proposal from the same deterministic smoothing preview. */
export function previewCanvasStrokeShape(rawPoints: unknown): Extract<CanvasStrokeProjection, { kind: 'shape' }> | null {
  const smoothed = smoothCanvasStrokePoints(rawPoints)
  const recognition = smoothed && recognizeCanvasStrokeShape(smoothed)
  if (!recognition) return null
  return { kind: 'shape', algorithm: CANVAS_SHAPE_RECOGNITION_VERSION, shape: recognition.kind, geometry: recognition.geometry } as Extract<CanvasStrokeProjection, { kind: 'shape' }>
}

/** Rejects persisted shape metadata that cannot be reproduced from raw samples. */
export function isCanvasStrokeShapeProjectionForRaw(rawPoints: unknown, projection: unknown): boolean {
  if (!isCanvasStrokeProjection(projection) || projection.kind !== 'shape') return false
  const proposal = previewCanvasStrokeShape(rawPoints)
  return proposal !== null && JSON.stringify(proposal) === JSON.stringify(projection)
}

export function createCanvasStrokeShapeRefinement(sourceId: unknown, rawPoints: unknown, appliedAt: unknown): CanvasStrokeRefinement | null {
  if (typeof sourceId !== 'string' || !sourceId || typeof appliedAt !== 'string' || !Number.isFinite(Date.parse(appliedAt))) return null
  const result = previewCanvasStrokeShape(rawPoints)
  if (!result) return null
  return { sourceId, gesture: 'explicit-shape-conversion', appliedAt, algorithm: CANVAS_SHAPE_RECOGNITION_VERSION, version: CANVAS_SHAPE_RECOGNITION_VERSION, result }
}

export function applyCanvasStrokeShape<T extends { id: string; rawPoints?: unknown; projection?: CanvasStrokeProjection; refinements?: CanvasStrokeRefinement[] }>(stroke: T, appliedAt: unknown): (T & { projection: Extract<CanvasStrokeProjection, { kind: 'shape' }>; refinements: CanvasStrokeRefinement[] }) | null {
  if (stroke.projection !== undefined) return null
  const refinement = createCanvasStrokeShapeRefinement(stroke.id, stroke.rawPoints, appliedAt)
  if (!refinement || refinement.result.kind !== 'shape') return null
  return { ...stroke, projection: refinement.result, refinements: [...(stroke.refinements ?? []), refinement] }
}

/**
 * Validates and copies raw canvas-space samples without resampling or removing
 * repeated samples. A valid stroke needs at least two points and non-zero path
 * length, which rejects taps while preserving every meaningful raw sample.
 */
export function normalizeCanvasStrokePoints(value: unknown): CanvasStrokePoint[] | null {
  if (!Array.isArray(value) || value.length < 2) return null
  const points: CanvasStrokePoint[] = []

  for (const valuePoint of value) {
    if (!isRecord(valuePoint) || Object.keys(valuePoint).length !== 2 ||
      !Object.prototype.hasOwnProperty.call(valuePoint, 'x') ||
      !Object.prototype.hasOwnProperty.call(valuePoint, 'y') ||
      typeof valuePoint.x !== 'number' || typeof valuePoint.y !== 'number' ||
      !Number.isFinite(valuePoint.x) || !Number.isFinite(valuePoint.y)) return null
    points.push({ x: normalizeNumber(valuePoint.x), y: normalizeNumber(valuePoint.y) })
  }

  return canvasStrokeLength(points) > 0 ? points : null
}

/** Returns the accumulated distance between consecutive samples. */
export function canvasStrokeLength(points: readonly CanvasStrokePoint[]): number {
  let length = 0
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1], point = points[index]
    length += Math.hypot(point.x - previous.x, point.y - previous.y)
  }
  return length
}

/**
 * Applies an endpoint-preserving moving average. The operation is local,
 * deterministic, and leaves the source array and its points untouched.
 */
export function smoothCanvasStrokePoints(value: unknown, iterations: 1 | 2 | 3 = 1): CanvasStrokePoint[] | null {
  const normalized = normalizeCanvasStrokePoints(value)
  if (!normalized) return null

  let result = normalized
  for (let pass = 0; pass < iterations; pass += 1) {
    result = result.map((point, index, points) => {
      if (index === 0 || index === points.length - 1) return { ...point }
      const previous = points[index - 1], next = points[index + 1]
      return { x: (previous.x + point.x + next.x) / 3, y: (previous.y + point.y + next.y) / 3 }
    })
  }
  return result
}

/**
 * Produces the active render projection from preserved raw points. Consumers
 * store the raw points separately and can always return to `kind: 'raw'`.
 */
export function projectCanvasStroke(rawPoints: unknown, projection: CanvasStrokeProjection): CanvasStrokePoint[] | null {
  if (projection.kind === 'raw') return normalizeCanvasStrokePoints(rawPoints)
  if (projection.kind === 'smoothed') return projection.algorithm === STROKE_SMOOTHING_ALGORITHM ? smoothCanvasStrokePoints(rawPoints, projection.iterations ?? 1) : null
  if (!isCanvasStrokeProjection(projection)) return null
  if (projection.shape === 'line') return [projection.geometry.start, projection.geometry.end].map(point => ({ ...point }))
  if (projection.shape === 'rectangle') { const { x, y, width, height } = projection.geometry; return [{ x, y }, { x: x + width, y }, { x: x + width, y: y + height }, { x, y: y + height }, { x, y }] }
  if (projection.shape === 'triangle') return [...projection.geometry.points.map(point => ({ ...point })), { ...projection.geometry.points[0] }]
  return Array.from({ length: 25 }, (_, index) => { const angle = index / 24 * Math.PI * 2; return { x: projection.geometry.center.x + Math.cos(angle) * projection.geometry.radiusX, y: projection.geometry.center.y + Math.sin(angle) * projection.geometry.radiusY } })
}

/** Validates a closed lasso outline without requiring a duplicate end point. */
export function normalizeCanvasLassoPoints(value: unknown): CanvasStrokePoint[] | null {
  if (!Array.isArray(value) || value.length < 3) return null
  const points: CanvasStrokePoint[] = []
  for (const valuePoint of value) {
    if (!isRecord(valuePoint) || Object.keys(valuePoint).length !== 2 ||
      !Object.prototype.hasOwnProperty.call(valuePoint, 'x') || !Object.prototype.hasOwnProperty.call(valuePoint, 'y') ||
      typeof valuePoint.x !== 'number' || typeof valuePoint.y !== 'number' || !Number.isFinite(valuePoint.x) || !Number.isFinite(valuePoint.y)) return null
    points.push({ x: normalizeNumber(valuePoint.x), y: normalizeNumber(valuePoint.y) })
  }
  return Math.abs(polygonArea(points)) > 1e-9 ? points : null
}

const polygonArea = (points: readonly CanvasStrokePoint[]) => points.reduce((area, point, index) => {
  const next = points[(index + 1) % points.length]
  return area + point.x * next.y - next.x * point.y
}, 0) / 2
const orientation = (a: CanvasStrokePoint, b: CanvasStrokePoint, c: CanvasStrokePoint) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
const onSegment = (a: CanvasStrokePoint, b: CanvasStrokePoint, point: CanvasStrokePoint) => Math.abs(orientation(a, b, point)) <= 1e-9 && point.x >= Math.min(a.x, b.x) - 1e-9 && point.x <= Math.max(a.x, b.x) + 1e-9 && point.y >= Math.min(a.y, b.y) - 1e-9 && point.y <= Math.max(a.y, b.y) + 1e-9
const segmentsIntersect = (a: CanvasStrokePoint, b: CanvasStrokePoint, c: CanvasStrokePoint, d: CanvasStrokePoint) => {
  const abC = orientation(a, b, c), abD = orientation(a, b, d), cdA = orientation(c, d, a), cdB = orientation(c, d, b)
  if (((abC > 0 && abD < 0) || (abC < 0 && abD > 0)) && ((cdA > 0 && cdB < 0) || (cdA < 0 && cdB > 0))) return true
  return onSegment(a, b, c) || onSegment(a, b, d) || onSegment(c, d, a) || onSegment(c, d, b)
}

/** Includes the lasso outline, so a touching stroke is selected. */
export function isCanvasPointInLasso(point: CanvasStrokePoint, lasso: readonly CanvasStrokePoint[]): boolean {
  for (let index = 0; index < lasso.length; index += 1) if (onSegment(lasso[index], lasso[(index + 1) % lasso.length], point)) return true
  let inside = false
  for (let index = 0, previous = lasso.length - 1; index < lasso.length; previous = index++) {
    const a = lasso[index], b = lasso[previous]
    if ((a.y > point.y) !== (b.y > point.y) && point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x) inside = !inside
  }
  return inside
}

/** Selects only raw stroke geometry that is contained by, crosses, or touches a lasso. */
export function canvasStrokeIntersectsLasso(rawPoints: unknown, rawLasso: unknown): boolean {
  const stroke = normalizeCanvasStrokePoints(rawPoints), lasso = normalizeCanvasLassoPoints(rawLasso)
  if (!stroke || !lasso) return false
  if (stroke.some(point => isCanvasPointInLasso(point, lasso))) return true
  for (let strokeIndex = 1; strokeIndex < stroke.length; strokeIndex += 1) for (let lassoIndex = 0; lassoIndex < lasso.length; lassoIndex += 1) {
    if (segmentsIntersect(stroke[strokeIndex - 1], stroke[strokeIndex], lasso[lassoIndex], lasso[(lassoIndex + 1) % lasso.length])) return true
  }
  return false
}
