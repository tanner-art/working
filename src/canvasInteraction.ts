import type { CanvasViewport } from './domain'
import { reduceCanvasGesture, type GestureResult, type GestureState, type PointerSample } from './canvasGestures'
import { zoomCanvasViewport, type CanvasPoint } from './canvasViewport'

export const CANVAS_RESIZE_TARGET_SIZE = 44

export interface PinchInteraction {
  start: { viewport: CanvasViewport; midpoint: CanvasPoint; distance: number } | null
  preview: CanvasViewport | null
}

// Pointer events use viewport coordinates; canvas transforms use coordinates local
// to the rendered canvas. Account for the toolbar/sidebar offset at each sample.
const midpoint = (a: PointerSample, b: PointerSample, canvasOrigin: CanvasPoint): CanvasPoint => ({
  x: (a.x + b.x) / 2 - canvasOrigin.x,
  y: (a.y + b.y) / 2 - canvasOrigin.y,
})
const distance = (a: PointerSample, b: PointerSample) => Math.max(1, Math.hypot(a.x - b.x, a.y - b.y))

/** Keeps the latest pinch preview synchronously available until it is committed. */
export function createPinchInteraction(): PinchInteraction {
  return { start: null, preview: null }
}

export function beginPinchInteraction(interaction: PinchInteraction, viewport: CanvasViewport, first: PointerSample, second: PointerSample, canvasOrigin: CanvasPoint) {
  interaction.preview = null
  interaction.start = { viewport, midpoint: midpoint(first, second, canvasOrigin), distance: distance(first, second) }
}

export function previewPinchInteraction(interaction: PinchInteraction, first: PointerSample, second: PointerSample, canvasOrigin: CanvasPoint) {
  const start = interaction.start
  if (!start) return null
  const currentMidpoint = midpoint(first, second, canvasOrigin)
  const anchored = zoomCanvasViewport(start.viewport, start.midpoint, start.viewport.scale * distance(first, second) / start.distance)
  const preview = { ...anchored, x: anchored.x + currentMidpoint.x - start.midpoint.x, y: anchored.y + currentMidpoint.y - start.midpoint.y }
  interaction.preview = preview
  return preview
}

export function commitPinchInteraction(interaction: PinchInteraction) {
  const preview = interaction.preview
  interaction.preview = null
  interaction.start = null
  return preview
}

export function clearPinchInteraction(interaction: PinchInteraction) {
  interaction.preview = null
  interaction.start = null
}

/** Mirrors the visible edit state into the reducer before a resize pointer-down. */
export function reduceResizePointerDown(state: GestureState, sample: PointerSample, id: string, editMode: boolean): GestureResult {
  const prepared = editMode ? reduceCanvasGesture(state, { type: 'enter-edit-mode' }) : { state, effects: [] }
  const result = reduceCanvasGesture(prepared.state, { type: 'pointer-down', sample, target: { kind: 'resize', id } })
  return { state: result.state, effects: [...prepared.effects, ...result.effects] }
}
