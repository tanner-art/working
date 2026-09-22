/**
 * A canvas-space point captured from a pen or lasso gesture. It deliberately
 * contains only JSON numbers: pressure, screen coordinates, and timestamps are
 * outside the first stroke format so saved raw expression is portable.
 */
export interface CanvasStrokePoint { x: number; y: number }

export type CanvasStrokeProjection =
  | { kind: 'raw' }
  | { kind: 'smoothed'; algorithm: 'moving-average-v1'; iterations?: 1 | 2 | 3 }

export const STROKE_SMOOTHING_ALGORITHM = 'moving-average-v1' as const

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const normalizeNumber = (value: number) => Object.is(value, -0) ? 0 : value

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
  if (projection.kind !== 'smoothed' || projection.algorithm !== STROKE_SMOOTHING_ALGORITHM) return null
  return smoothCanvasStrokePoints(rawPoints, projection.iterations ?? 1)
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
