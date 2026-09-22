import type { CanvasElement, CanvasViewport } from './domain'
import { canvasSize } from './canvasGeometry'

export const CANVAS_MIN_SCALE = 0.55
export const CANVAS_MAX_SCALE = 1.6
export const DEFAULT_CANVAS_VIEWPORT: CanvasViewport = { x: 0, y: 0, scale: 1 }

export interface CanvasPoint { x: number; y: number }
export interface CanvasViewportSize { width: number; height: number }

const finite = (value: number, fallback: number) => Number.isFinite(value) ? value : fallback
export const clampCanvasScale = (scale: number) => Math.min(CANVAS_MAX_SCALE, Math.max(CANVAS_MIN_SCALE, finite(scale, DEFAULT_CANVAS_VIEWPORT.scale)))

export function worldPointAtScreen(viewport: CanvasViewport, point: CanvasPoint): CanvasPoint {
  const scale = clampCanvasScale(viewport.scale)
  return { x: (point.x - finite(viewport.x, 0)) / scale, y: (point.y - finite(viewport.y, 0)) / scale }
}

export function screenPointAtWorld(viewport: CanvasViewport, point: CanvasPoint): CanvasPoint {
  const scale = clampCanvasScale(viewport.scale)
  return { x: finite(viewport.x, 0) + point.x * scale, y: finite(viewport.y, 0) + point.y * scale }
}

/** Changes scale while keeping the world point under `focal` under that screen point. */
export function zoomCanvasViewport(viewport: CanvasViewport, focal: CanvasPoint, scale: number): CanvasViewport {
  const nextScale = clampCanvasScale(scale)
  const world = worldPointAtScreen(viewport, focal)
  return { x: focal.x - world.x * nextScale, y: focal.y - world.y * nextScale, scale: nextScale }
}

export function panCanvasViewport(viewport: CanvasViewport, delta: CanvasPoint): CanvasViewport {
  return { x: finite(viewport.x, 0) + finite(delta.x, 0), y: finite(viewport.y, 0) + finite(delta.y, 0), scale: clampCanvasScale(viewport.scale) }
}

interface Bounds { minX: number; minY: number; maxX: number; maxY: number }

function boundsFor(elements: CanvasElement[], selectedIds?: ReadonlySet<string>): Bounds | undefined {
  const nodes = elements.filter(item => item.type !== 'arrow' && (!selectedIds || selectedIds.has(item.id)))
  if (nodes.length === 0) return undefined
  return nodes.reduce<Bounds | undefined>((bounds, node) => {
    const size = canvasSize(node)
    const next = { minX: node.x, minY: node.y, maxX: node.x + size.width, maxY: node.y + size.height }
    if (!bounds) return next
    return { minX: Math.min(bounds.minX, next.minX), minY: Math.min(bounds.minY, next.minY), maxX: Math.max(bounds.maxX, next.maxX), maxY: Math.max(bounds.maxY, next.maxY) }
  }, undefined)
}

/** Fits node bounds into a rendered viewport, ignoring arrows and preserving persisted scale limits. */
export function fitCanvasViewport(elements: CanvasElement[], viewportSize: CanvasViewportSize, padding = 32, selectedIds?: ReadonlySet<string>): CanvasViewport {
  const width = Math.max(1, finite(viewportSize.width, 1)), height = Math.max(1, finite(viewportSize.height, 1))
  const bounds = boundsFor(elements, selectedIds)
  if (!bounds) return { ...DEFAULT_CANVAS_VIEWPORT }
  const safePadding = Math.max(0, finite(padding, 0))
  const availableWidth = Math.max(1, width - safePadding * 2), availableHeight = Math.max(1, height - safePadding * 2)
  const scale = clampCanvasScale(Math.min(availableWidth / Math.max(1, bounds.maxX - bounds.minX), availableHeight / Math.max(1, bounds.maxY - bounds.minY)))
  return { x: (width - (bounds.minX + bounds.maxX) * scale) / 2, y: (height - (bounds.minY + bounds.maxY) * scale) / 2, scale }
}
