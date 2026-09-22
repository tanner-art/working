import type { CanvasCurveHandle, CanvasElement, CanvasPerimeterAnchor } from './domain'

export type CanvasShape = Exclude<CanvasElement['type'], 'arrow'> | NonNullable<CanvasElement['shape']>
export const canvasShapeLabels: Record<CanvasShape, string> = { text: 'Text block', rectangle: 'Rectangle', 'rounded-rectangle': 'Rounded rectangle', ellipse: 'Ellipse', diamond: 'Diamond', container: 'Group container' }
export const canvasNodeShape = (node: CanvasElement): CanvasShape => node.type === 'container' ? 'container' : node.shape ?? 'text'
export type ConnectionPath = NonNullable<CanvasElement['connectionPath']>
export type ConnectionPattern = NonNullable<CanvasElement['connectionPattern']>
export type ConnectionWeight = NonNullable<CanvasElement['connectionWeight']>
export const CANVAS_SIZE = { minWidth: 120, minHeight: 100, maxWidth: 1200, maxHeight: 900 } as const
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, Math.round(value)))
const clampNumber = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
export const CURVE_HANDLE_LIMIT = 1.5
export interface CanvasPoint { x: number; y: number }
export interface CanvasConnectionEndpoints { x1: number; y1: number; x2: number; y2: number }

/** Returns a finite normalized anchor; finite out-of-range input is safely clamped. */
export function normalizePerimeterAnchor(anchor: unknown): CanvasPerimeterAnchor | undefined {
  if (!anchor || typeof anchor !== 'object') return undefined
  const { x, y } = anchor as Partial<CanvasPerimeterAnchor>
  if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) return undefined
  return { x: clampNumber(x, 0, 1), y: clampNumber(y, 0, 1) }
}

export function normalizeCurveHandle(handle: unknown): CanvasCurveHandle | undefined {
  if (!handle || typeof handle !== 'object') return undefined
  const { x, y } = handle as Partial<CanvasCurveHandle>
  if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) return undefined
  return { x: clampNumber(x, -CURVE_HANDLE_LIMIT, CURVE_HANDLE_LIMIT), y: clampNumber(y, -CURVE_HANDLE_LIMIT, CURVE_HANDLE_LIMIT) }
}

// Explicit fallbacks keep legacy nodes, rendered bounds and connector anchors aligned.
export function canvasSize(node: CanvasElement) {
  return {
    width: clamp(Number.isFinite(node.width) ? node.width! : node.type === 'container' ? 320 : 190, CANVAS_SIZE.minWidth, CANVAS_SIZE.maxWidth),
    height: clamp(Number.isFinite(node.height) ? node.height! : node.type === 'container' ? 210 : 100, CANVAS_SIZE.minHeight, CANVAS_SIZE.maxHeight),
  }
}
export function resizeCanvasNode(elements: CanvasElement[], id: string, width: number, height: number): CanvasElement[] {
  if (!Number.isFinite(width) || !Number.isFinite(height)) return elements
  return elements.map(node => {
    if (node.id !== id || node.type === 'arrow') return node
    const before = canvasSize(node), next = canvasSize({ ...node, width, height })
    return before.width === next.width && before.height === next.height ? node : { ...node, ...next }
  })
}
export function convertCanvasNode(elements: CanvasElement[], id: string, shape: CanvasShape): CanvasElement[] {
  const target = elements.find(node => node.id === id)
  if (!target || target.type === 'arrow' || canvasNodeShape(target) === shape) return elements
  const type = shape === 'container' ? 'container' : 'text'
  return elements.map(node => {
    if (target.type === 'container' && node.groupId === id && type !== 'container') return { ...node, groupId: undefined }
    return node.id === id
      ? { ...node, ...canvasSize(node), type, shape: shape === 'text' || shape === 'container' ? undefined : shape,
        groupId: type === 'container' ? undefined : node.groupId } : node
  })
}
function legacyConnector(from: CanvasElement, to: CanvasElement): CanvasConnectionEndpoints {
  const a = canvasSize(from), b = canvasSize(to)
  return { x1: from.x + a.width / 2, y1: from.y + a.height, x2: to.x + b.width / 2, y2: to.y }
}

function roundedRadius(node: CanvasElement, width: number, height: number) {
  return Math.min(width / 2, height / 2, canvasNodeShape(node) === 'rounded-rectangle' ? 20 : canvasNodeShape(node) === 'container' ? 10 : 0)
}

/** Projects an anchor's center-relative ray to the actual boundary of a supported node. */
export function projectPerimeterAnchor(node: CanvasElement, anchor: unknown): CanvasPoint {
  const hint = normalizePerimeterAnchor(anchor) ?? { x: .5, y: 1 }
  const { width, height } = canvasSize(node)
  const halfWidth = width / 2, halfHeight = height / 2
  let dx = hint.x * 2 - 1, dy = hint.y * 2 - 1
  if (dx === 0 && dy === 0) dy = 1
  const shape = canvasNodeShape(node)
  let t: number
  if (shape === 'ellipse') t = 1 / Math.hypot(dx / halfWidth, dy / halfHeight)
  else if (shape === 'diamond') t = 1 / (Math.abs(dx) / halfWidth + Math.abs(dy) / halfHeight)
  else {
    t = Math.min(halfWidth / Math.abs(dx || Number.EPSILON), halfHeight / Math.abs(dy || Number.EPSILON))
    const radius = roundedRadius(node, width, height)
    if (radius > 0) {
      const x = dx * t, y = dy * t
      if (Math.abs(x) > halfWidth - radius && Math.abs(y) > halfHeight - radius) {
        const cornerX = Math.sign(dx) * (halfWidth - radius), cornerY = Math.sign(dy) * (halfHeight - radius)
        const a = dx * dx + dy * dy, b = -2 * (dx * cornerX + dy * cornerY), c = cornerX * cornerX + cornerY * cornerY - radius * radius
        const discriminant = b * b - 4 * a * c
        if (discriminant >= 0) {
          const roots = [(-b - Math.sqrt(discriminant)) / (2 * a), (-b + Math.sqrt(discriminant)) / (2 * a)].filter(root => root >= 0)
          if (roots.length) t = Math.max(...roots)
        }
      }
    }
  }
  return { x: node.x + halfWidth + dx * t, y: node.y + halfHeight + dy * t }
}

/** Derives a clamped local ray hint from a world-space pointer location. */
export function perimeterAnchorAtPoint(node: CanvasElement, point: CanvasPoint): CanvasPerimeterAnchor | undefined {
  if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) return undefined
  const { width, height } = canvasSize(node), centerX = node.x + width / 2, centerY = node.y + height / 2
  const dx = (point.x - centerX) / (width / 2), dy = (point.y - centerY) / (height / 2)
  const length = Math.max(Math.abs(dx), Math.abs(dy))
  if (length === 0) return { x: .5, y: 1 }
  return { x: clampNumber(.5 + dx / length / 2, 0, 1), y: clampNumber(.5 + dy / length / 2, 0, 1) }
}

/** Uses fixed legacy ports until an explicit perimeter hint is saved. */
export function connectionEndpoints(from: CanvasElement, to: CanvasElement, connection?: Pick<CanvasElement, 'sourceAnchor' | 'targetAnchor'>): CanvasConnectionEndpoints {
  const legacy = legacyConnector(from, to)
  const source = normalizePerimeterAnchor(connection?.sourceAnchor)
  const target = normalizePerimeterAnchor(connection?.targetAnchor)
  const start = source ? projectPerimeterAnchor(from, source) : { x: legacy.x1, y: legacy.y1 }
  const end = target ? projectPerimeterAnchor(to, target) : { x: legacy.x2, y: legacy.y2 }
  return { x1: start.x, y1: start.y, x2: end.x, y2: end.y }
}

// Bottom/top extrema lie on every supported shape boundary, including ellipse and diamond.
// Keep these fixed ports for both straight and curved legacy connections.
export function canvasConnector(from: CanvasElement, to: CanvasElement, connection?: Pick<CanvasElement, 'sourceAnchor' | 'targetAnchor'>) {
  return connectionEndpoints(from, to, connection)
}

export function connectionPathData(from: CanvasElement, to: CanvasElement, connection?: Pick<CanvasElement, 'connectionPath' | 'sourceAnchor' | 'targetAnchor' | 'curveHandle'>) {
  const { x1, y1, x2, y2 } = connectionEndpoints(from, to, connection)
  const path = connection?.connectionPath ?? 'straight'
  if (path === 'straight') return `M ${x1} ${y1} L ${x2} ${y2}`
  const curve = normalizeCurveHandle(connection?.curveHandle)
  if (curve) {
    const spanX = x2 - x1, spanY = y2 - y1
    const midpointX = (x1 + x2) / 2, midpointY = (y1 + y2) / 2
    const controlX = midpointX + curve.x * Math.max(Math.abs(spanX), 1)
    const controlY = midpointY + curve.y * Math.max(Math.abs(spanY), 1)
    return `M ${x1} ${y1} Q ${controlX} ${controlY}, ${x2} ${y2}`
  }
  const bend = Math.max(48, Math.abs(y2 - y1) * .45)
  return `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`
}

export function canvasConnectorPath(from: CanvasElement, to: CanvasElement, path: ConnectionPath = 'straight', connection?: Pick<CanvasElement, 'sourceAnchor' | 'targetAnchor' | 'curveHandle'>) {
  return connectionPathData(from, to, { ...connection, connectionPath: path })
}

export function connectionAppearance(connection: CanvasElement) {
  const weight = connection.connectionWeight ?? 'regular'
  const pattern = connection.connectionPattern ?? 'solid'
  return {
    strokeWidth: weight === 'light' ? 1 : weight === 'bold' ? 5 : 2,
    strokeDasharray: pattern === 'dashed' ? '12 8' : pattern === 'dotted' ? '2 7' : undefined,
    strokeLinecap: pattern === 'dotted' ? 'round' as const : 'butt' as const,
  }
}

export function updateCanvasConnection(elements: CanvasElement[], id: string, patch: Pick<CanvasElement, 'connectionPath' | 'connectionPattern' | 'connectionWeight'>) {
  return elements.map(element => {
    if (element.id !== id || element.type !== 'arrow') return element
    if (patch.connectionPath !== 'straight') return { ...element, ...patch }
    const { curveHandle: _curveHandle, ...withoutCurveHandle } = element
    return { ...withoutCurveHandle, ...patch }
  })
}

function pointInsideNode(node: CanvasElement, point: CanvasPoint) {
  const { width, height } = canvasSize(node), centerX = node.x + width / 2, centerY = node.y + height / 2
  const dx = (point.x - centerX) / (width / 2), dy = (point.y - centerY) / (height / 2)
  const shape = canvasNodeShape(node)
  if (shape === 'ellipse') return dx * dx + dy * dy < 1 - 1e-6
  if (shape === 'diamond') return Math.abs(dx) + Math.abs(dy) < 1 - 1e-6
  return Math.abs(dx) < 1 - 1e-6 && Math.abs(dy) < 1 - 1e-6
}

/** Updates one arrow without mutating the input array. Invalid endpoint updates are rejected. */
export function updateCanvasConnectionAnchors(elements: CanvasElement[], id: string, patch: Pick<CanvasElement, 'sourceAnchor' | 'targetAnchor' | 'curveHandle'>) {
  const arrow = elements.find(item => item.id === id && item.type === 'arrow')
  if (!arrow || !arrow.fromId || !arrow.toId || arrow.fromId === arrow.toId) return elements
  const from = elements.find(item => item.id === arrow.fromId && item.type !== 'arrow')
  const to = elements.find(item => item.id === arrow.toId && item.type !== 'arrow')
  if (!from || !to) return elements
  const sourceAnchor = patch.sourceAnchor === undefined ? arrow.sourceAnchor : normalizePerimeterAnchor(patch.sourceAnchor)
  const targetAnchor = patch.targetAnchor === undefined ? arrow.targetAnchor : normalizePerimeterAnchor(patch.targetAnchor)
  const curveHandle = patch.curveHandle === undefined ? arrow.curveHandle : normalizeCurveHandle(patch.curveHandle)
  if ((patch.sourceAnchor !== undefined && !sourceAnchor) || (patch.targetAnchor !== undefined && !targetAnchor) || (patch.curveHandle !== undefined && !curveHandle)) return elements
  const endpoints = connectionEndpoints(from, to, { sourceAnchor, targetAnchor })
  // Legacy fixed ports are retained even where a historical layout crosses a source
  // box. Explicit endpoint movement cannot place the target boundary inside its source.
  if ((patch.sourceAnchor !== undefined || patch.targetAnchor !== undefined) &&
    pointInsideNode(from, { x: endpoints.x2, y: endpoints.y2 })) return elements
  const next = { ...arrow, sourceAnchor, targetAnchor, curveHandle: arrow.connectionPath === 'curved' ? curveHandle : undefined }
  return elements.map(item => item.id === id ? next : item)
}
