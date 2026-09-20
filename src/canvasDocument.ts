import type { CanvasElement, CanvasViewport } from './domain'

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
      (item.type === 'text' && value.some(group => group.id === item.groupId && group.type === 'container')))
}

const canvasTypes: CanvasElement['type'][] = ['text', 'container', 'arrow']
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
    (item.fromId === undefined || typeof item.fromId === 'string') &&
    (item.toId === undefined || typeof item.toId === 'string') &&
    (item.groupId === undefined || typeof item.groupId === 'string') &&
    (item.connectionPath === undefined || ['straight', 'curved'].includes(item.connectionPath)) &&
    (item.connectionPattern === undefined || ['solid', 'dashed', 'dotted'].includes(item.connectionPattern)) &&
    (item.connectionWeight === undefined || ['light', 'regular', 'bold'].includes(item.connectionWeight)) &&
    (item.type === 'arrow' || (item.connectionPath === undefined && item.connectionPattern === undefined && item.connectionWeight === undefined)) &&
    (item.type !== 'arrow' || (typeof item.fromId === 'string' && typeof item.toId === 'string'))
}

export function newCanvasElement(type: CanvasElement['type'], x: number, y: number): CanvasElement {
  return { id: crypto.randomUUID(), type, x, y, width: type === 'container' ? 320 : 190, height: type === 'container' ? 210 : undefined, text: type === 'container' ? 'Untitled group' : 'New thought' }
}
