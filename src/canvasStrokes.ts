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
