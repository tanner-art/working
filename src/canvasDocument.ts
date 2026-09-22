import type { CanvasElement, CanvasViewport } from './domain'
import { isActiveCanvasStrokeRefinement, isCanvasStrokeProjection, isCanvasStrokeRefinement, isCanvasStrokeShapeProjectionForRaw, normalizeCanvasStrokePoints } from './canvasStrokes'

export interface CanvasDocument { elements: CanvasElement[]; viewport: CanvasViewport }
export const DEFAULT_CANVAS_VIEWPORT: CanvasViewport = { x: 0, y: 0, scale: 1 }

export function isCanvasViewport(value: unknown): value is CanvasViewport {
  if (!value || typeof value !== 'object') return false
  const viewport = value as CanvasViewport
  return Object.keys(value).every(key => ['x', 'y', 'scale'].includes(key)) &&
    Number.isFinite(viewport.x) && Number.isFinite(viewport.y) &&
    Number.isFinite(viewport.scale) && viewport.scale >= .55 && viewport.scale <= 1.6
}

export function isCanvasElements(value: unknown): value is CanvasElement[] {
  return Array.isArray(value) && value.every(isCanvasElement) &&
    new Set(value.map(item => item.id)).size === value.length &&
    value.every(item => item.groupId === undefined ||
      (item.type === 'text' && value.some(group => group.id === item.groupId && group.type === 'container'))) &&
    // Older captures may contain a dangling visual arrow. Preserve that source
    // expression unchanged; arrows opting into editable perimeter geometry must have
    // two distinct, present node endpoints before their new fields are accepted.
    value.every(item => item.type !== 'arrow' || (!item.sourceAnchor && !item.targetAnchor && !item.curveHandle) ||
      (item.fromId !== item.toId && value.some(endpoint => endpoint.id === item.fromId && (endpoint.type === 'text' || endpoint.type === 'container')) &&
        value.some(endpoint => endpoint.id === item.toId && (endpoint.type === 'text' || endpoint.type === 'container'))))
}

const canvasTypes: CanvasElement['type'][] = ['text', 'container', 'arrow', 'freehand']
const freehandKeys = new Set(['id', 'type', 'x', 'y', 'rawPoints', 'projection', 'refinements'])
const isPerimeterAnchor = (value: unknown): boolean => Boolean(value) && typeof value === 'object' &&
  Number.isFinite((value as { x?: unknown }).x) && Number.isFinite((value as { y?: unknown }).y) &&
  (value as { x: number }).x >= 0 && (value as { x: number }).x <= 1 &&
  (value as { y: number }).y >= 0 && (value as { y: number }).y <= 1
// Curve offsets are measured in endpoint spans. Keeping them within 1.5 spans makes
// extreme drags expressive without allowing unbounded persisted geometry.
const isCurveHandle = (value: unknown): boolean => Boolean(value) && typeof value === 'object' &&
  Number.isFinite((value as { x?: unknown }).x) && Number.isFinite((value as { y?: unknown }).y) &&
  Math.abs((value as { x: number }).x) <= 1.5 && Math.abs((value as { y: number }).y) <= 1.5
const hasValidFreehandRefinement = (item: Partial<CanvasElement>) => {
  if (item.projection === undefined || item.refinements === undefined) return item.projection === undefined && item.refinements === undefined
  return item.refinements.every(refinement => refinement.sourceId === item.id) &&
    isActiveCanvasStrokeRefinement(item.refinements.at(-1), item.projection) &&
    (item.projection.kind !== 'shape' || isCanvasStrokeShapeProjectionForRaw(item.rawPoints, item.projection))
}
function isCanvasElement(value: unknown): value is CanvasElement {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<CanvasElement>
  return typeof item.id === 'string' &&
    canvasTypes.includes(item.type as CanvasElement['type']) &&
    Number.isFinite(item.x) &&
    Number.isFinite(item.y) &&
    (item.width === undefined || Number.isFinite(item.width)) &&
    (item.height === undefined || Number.isFinite(item.height)) &&
    (item.shape === undefined || (item.type === 'text' && ['rectangle', 'rounded-rectangle', 'ellipse', 'diamond'].includes(item.shape))) &&
    (item.text === undefined || typeof item.text === 'string') &&
    (item.nodeVariant === undefined || (item.type === 'text' && item.nodeVariant === 'bulleted-list')) &&
    (item.fromId === undefined || typeof item.fromId === 'string') &&
    (item.toId === undefined || typeof item.toId === 'string') &&
    (item.groupId === undefined || typeof item.groupId === 'string') &&
    (item.connectionPath === undefined || ['straight', 'curved'].includes(item.connectionPath)) &&
    (item.connectionPattern === undefined || ['solid', 'dashed', 'dotted'].includes(item.connectionPattern)) &&
    (item.connectionWeight === undefined || ['light', 'regular', 'bold'].includes(item.connectionWeight)) &&
    (item.sourceAnchor === undefined || isPerimeterAnchor(item.sourceAnchor)) &&
    (item.targetAnchor === undefined || isPerimeterAnchor(item.targetAnchor)) &&
    (item.curveHandle === undefined || isCurveHandle(item.curveHandle)) &&
    (item.rawPoints === undefined || normalizeCanvasStrokePoints(item.rawPoints) !== null) &&
    (item.projection === undefined || isCanvasStrokeProjection(item.projection)) &&
    (item.refinements === undefined || (Array.isArray(item.refinements) && item.refinements.length > 0 && item.refinements.every(isCanvasStrokeRefinement))) &&
    (item.type === 'freehand' || (item.rawPoints === undefined && item.projection === undefined && item.refinements === undefined)) &&
    (item.type !== 'freehand' || (
      Object.keys(value).every(key => freehandKeys.has(key)) && item.rawPoints !== undefined && item.shape === undefined && item.text === undefined && item.width === undefined && item.height === undefined && item.fromId === undefined && item.toId === undefined && item.groupId === undefined && item.connectionPath === undefined && item.connectionPattern === undefined && item.connectionWeight === undefined && item.sourceAnchor === undefined && item.targetAnchor === undefined && item.curveHandle === undefined &&
      hasValidFreehandRefinement(item))) &&
    (item.type === 'arrow' || item.type === 'freehand' || (item.connectionPath === undefined && item.connectionPattern === undefined && item.connectionWeight === undefined && item.sourceAnchor === undefined && item.targetAnchor === undefined && item.curveHandle === undefined)) &&
    (item.type !== 'arrow' || (typeof item.fromId === 'string' && typeof item.toId === 'string' &&
      (item.curveHandle === undefined || item.connectionPath === 'curved')))
}

/** Toggle a canvas-only presentation choice without rewriting the node's text. */
export function toggleCanvasNodeVariant(elements: CanvasElement[], id: string): CanvasElement[] {
  return elements.map(item => item.id === id && item.type === 'text'
    ? { ...item, ...(item.nodeVariant === 'bulleted-list' ? { nodeVariant: undefined } : { nodeVariant: 'bulleted-list' }) }
    : item)
}

export function newCanvasElement(type: CanvasElement['type'], x: number, y: number): CanvasElement {
  return { id: crypto.randomUUID(), type, x, y, width: type === 'container' ? 320 : 190, height: type === 'container' ? 210 : undefined, text: type === 'container' ? 'Untitled group' : 'New thought' }
}
