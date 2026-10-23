import type { CanvasElement, CanvasStrokePoint } from './domain'
import { normalizeCanvasStrokePoints } from './canvasStrokes'

export interface CanvasInkAppearance { color: string; width: number }

export const DEFAULT_CANVAS_INK: CanvasInkAppearance = { color: '#344d41', width: 3 }
export const CANVAS_INK_COLORS = ['#344d41', '#316b8a', '#9a5d2e', '#9b3f4e', '#6c4a91', '#111111'] as const
export const CANVAS_INK_WIDTHS = [2, 3, 6, 10] as const

export function isCanvasInkColor(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)
}

export function isCanvasInkWidth(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 1 && value <= 24
}

export function canvasInkAppearance(stroke: Pick<CanvasElement, 'strokeColor' | 'strokeWidth'>): CanvasInkAppearance {
  return { color: stroke.strokeColor ?? DEFAULT_CANVAS_INK.color, width: stroke.strokeWidth ?? DEFAULT_CANVAS_INK.width }
}

/** Appearance is a canvas-only presentation choice; raw points are never rewritten. */
export function createCanvasInkStroke(id: string, rawPoints: CanvasStrokePoint[], appearance: CanvasInkAppearance): CanvasElement {
  if (!id || !isCanvasInkColor(appearance.color) || !isCanvasInkWidth(appearance.width) ||
    normalizeCanvasStrokePoints(rawPoints) === null) {
    throw Error('Ink appearance or drawing is invalid.')
  }
  return { id, type: 'freehand', x: rawPoints[0].x, y: rawPoints[0].y, rawPoints,
    strokeColor: appearance.color, strokeWidth: appearance.width }
}
