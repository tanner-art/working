import { normalizeCanvasStrokePoints, type CanvasStrokePoint } from './canvasStrokes'

export type CanvasRecognizedShapeKind = 'line' | 'rectangle' | 'ellipse' | 'triangle'

export interface CanvasLineGeometry { start: CanvasStrokePoint; end: CanvasStrokePoint }
export interface CanvasRectangleGeometry { x: number; y: number; width: number; height: number }
export interface CanvasEllipseGeometry { center: CanvasStrokePoint; radiusX: number; radiusY: number }
export interface CanvasTriangleGeometry { points: [CanvasStrokePoint, CanvasStrokePoint, CanvasStrokePoint] }

/**
 * A local, deliberately conservative suggestion. `sourcePoints` is an
 * independent copy of the supplied stroke projection; callers retain the
 * authoritative raw stroke separately when applying a refinement.
 */
interface CanvasShapeRecognitionBase<TKind extends CanvasRecognizedShapeKind, TGeometry> {
  kind: TKind
  confidence: number
  geometry: TGeometry
  sourcePoints: CanvasStrokePoint[]
}

export type CanvasShapeRecognition =
  | CanvasShapeRecognitionBase<'line', CanvasLineGeometry>
  | CanvasShapeRecognitionBase<'rectangle', CanvasRectangleGeometry>
  | CanvasShapeRecognitionBase<'ellipse', CanvasEllipseGeometry>
  | CanvasShapeRecognitionBase<'triangle', CanvasTriangleGeometry>

export const CANVAS_SHAPE_RECOGNITION_VERSION = 'deterministic-v1' as const

const MIN_SHAPE_SPAN = 12
const closureDistance = (length: number) => Math.max(4, Math.min(18, length * .14))
const copyPoint = (point: CanvasStrokePoint): CanvasStrokePoint => ({ x: point.x, y: point.y })
const distance = (a: CanvasStrokePoint, b: CanvasStrokePoint) => Math.hypot(a.x - b.x, a.y - b.y)
const clampConfidence = (value: number) => Math.max(0, Math.min(1, Math.round(value * 10_000) / 10_000))

const pathLength = (points: readonly CanvasStrokePoint[]) => points.reduce((total, point, index) => index === 0 ? 0 : total + distance(points[index - 1], point), 0)
const boundsOf = (points: readonly CanvasStrokePoint[]) => {
  const xs = points.map(point => point.x), ys = points.map(point => point.y)
  const x = Math.min(...xs), y = Math.min(...ys)
  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y }
}
const distanceToSegment = (point: CanvasStrokePoint, a: CanvasStrokePoint, b: CanvasStrokePoint) => {
  const dx = b.x - a.x, dy = b.y - a.y, denominator = dx * dx + dy * dy
  if (denominator === 0) return distance(point, a)
  const ratio = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / denominator))
  return Math.hypot(point.x - (a.x + ratio * dx), point.y - (a.y + ratio * dy))
}
const polygonArea = (points: readonly CanvasStrokePoint[]) => Math.abs(points.reduce((area, point, index) => {
  const next = points[(index + 1) % points.length]
  return area + point.x * next.y - next.x * point.y
}, 0) / 2)

const isClosed = (points: readonly CanvasStrokePoint[], length: number) => distance(points[0], points[points.length - 1]) <= closureDistance(length)
const closedOutline = (points: readonly CanvasStrokePoint[]) => points.slice(0, -1)

function recognizeLine(points: CanvasStrokePoint[], length: number): CanvasShapeRecognition | null {
  const start = points[0], end = points[points.length - 1], direct = distance(start, end)
  if (direct < MIN_SHAPE_SPAN || length / direct > 1.12) return null
  const deviation = Math.max(...points.map(point => distanceToSegment(point, start, end)))
  const tolerance = Math.max(1.5, direct * .055)
  if (deviation > tolerance) return null
  return {
    kind: 'line',
    confidence: clampConfidence(.99 - deviation / Math.max(direct, 1) - (length / direct - 1)),
    geometry: { start: copyPoint(start), end: copyPoint(end) },
    sourcePoints: points.map(copyPoint),
  }
}

function recognizeRectangle(points: CanvasStrokePoint[], length: number): CanvasShapeRecognition | null {
  if (!isClosed(points, length)) return null
  const outline = closedOutline(points), box = boundsOf(outline)
  if (box.width < MIN_SHAPE_SPAN || box.height < MIN_SHAPE_SPAN) return null
  const diagonal = Math.hypot(box.width, box.height), tolerance = Math.max(2.5, diagonal * .065)
  const corners = [
    { x: box.x, y: box.y }, { x: box.x + box.width, y: box.y },
    { x: box.x + box.width, y: box.y + box.height }, { x: box.x, y: box.y + box.height },
  ]
  const nearestCorner = corners.map(corner => Math.min(...outline.map(point => distance(point, corner))))
  if (nearestCorner.some(value => value > tolerance * 1.35)) return null
  const edgeDistances = outline.map(point => Math.min(
    Math.abs(point.x - box.x), Math.abs(point.x - (box.x + box.width)),
    Math.abs(point.y - box.y), Math.abs(point.y - (box.y + box.height)),
  ))
  const meanDistance = edgeDistances.reduce((sum, value) => sum + value, 0) / edgeDistances.length
  if (meanDistance > tolerance || Math.max(...edgeDistances) > tolerance * 2) return null
  return {
    kind: 'rectangle',
    confidence: clampConfidence(.98 - (meanDistance + Math.max(...nearestCorner)) / diagonal),
    geometry: { ...box },
    sourcePoints: points.map(copyPoint),
  }
}

function recognizeEllipse(points: CanvasStrokePoint[], length: number): CanvasShapeRecognition | null {
  if (!isClosed(points, length)) return null
  const outline = closedOutline(points), box = boundsOf(outline)
  if (box.width < MIN_SHAPE_SPAN || box.height < MIN_SHAPE_SPAN) return null
  const center = { x: box.x + box.width / 2, y: box.y + box.height / 2 }, radiusX = box.width / 2, radiusY = box.height / 2
  const residuals = outline.map(point => Math.abs(((point.x - center.x) / radiusX) ** 2 + ((point.y - center.y) / radiusY) ** 2 - 1))
  const meanResidual = residuals.reduce((sum, value) => sum + value, 0) / residuals.length
  const maxResidual = Math.max(...residuals)
  const quadrants = new Set(outline.map(point => `${point.x >= center.x ? 1 : 0}${point.y >= center.y ? 1 : 0}`))
  if (meanResidual > .14 || maxResidual > .34 || quadrants.size < 4) return null
  return {
    kind: 'ellipse',
    confidence: clampConfidence(.97 - meanResidual * .8 - maxResidual * .15),
    geometry: { center, radiusX, radiusY },
    sourcePoints: points.map(copyPoint),
  }
}

const cornerScore = (points: readonly CanvasStrokePoint[], index: number) => {
  const previous = points[(index - 1 + points.length) % points.length], current = points[index], next = points[(index + 1) % points.length]
  const before = distance(previous, current), after = distance(current, next)
  if (before === 0 || after === 0) return 0
  const cosine = ((previous.x - current.x) * (next.x - current.x) + (previous.y - current.y) * (next.y - current.y)) / (before * after)
  // The two vectors point away from the candidate. Straight path samples have
  // a cosine near -1; a vertex bends them toward one another.
  return 1 + Math.max(-1, Math.min(1, cosine))
}

function recognizeTriangle(points: CanvasStrokePoint[], length: number): CanvasShapeRecognition | null {
  if (!isClosed(points, length)) return null
  const outline = closedOutline(points), box = boundsOf(outline)
  if (outline.length < 3 || box.width < MIN_SHAPE_SPAN || box.height < MIN_SHAPE_SPAN) return null
  const diagonal = Math.hypot(box.width, box.height), candidates = outline.map((_, index) => ({ index, score: cornerScore(outline, index) })).sort((a, b) => b.score - a.score)
  const chosen: number[] = []
  for (const candidate of candidates) {
    if (candidate.score < .45 || (outline.length > 3 && chosen.some(index => Math.abs(index - candidate.index) <= 1 || Math.abs(index - candidate.index) >= outline.length - 1))) continue
    chosen.push(candidate.index)
    if (chosen.length === 3) break
  }
  if (chosen.length !== 3) return null
  chosen.sort((a, b) => a - b)
  const vertices = chosen.map(index => copyPoint(outline[index])) as CanvasTriangleGeometry['points']
  if (polygonArea(vertices) < diagonal * diagonal * .08) return null
  const distances = outline.map(point => Math.min(
    distanceToSegment(point, vertices[0], vertices[1]), distanceToSegment(point, vertices[1], vertices[2]), distanceToSegment(point, vertices[2], vertices[0]),
  ))
  const meanDistance = distances.reduce((sum, value) => sum + value, 0) / distances.length
  if (meanDistance > diagonal * .055 || Math.max(...distances) > diagonal * .13) return null
  return {
    kind: 'triangle',
    confidence: clampConfidence(.96 - meanDistance / diagonal),
    geometry: { points: vertices },
    sourcePoints: points.map(copyPoint),
  }
}

/**
 * Recognizes one simple stroke after callers have chosen its active projection.
 * It never mutates the input, makes no network request, and returns null for
 * invalid, ambiguous, noisy, or unsupported marks.
 */
export function recognizeCanvasStrokeShape(value: unknown): CanvasShapeRecognition | null {
  const points = normalizeCanvasStrokePoints(value)
  if (!points) return null
  const length = pathLength(points)
  if (!Number.isFinite(length) || length === 0) return null
  return recognizeLine(points, length) ?? recognizeRectangle(points, length) ?? recognizeEllipse(points, length) ?? recognizeTriangle(points, length)
}
