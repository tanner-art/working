import type { CanvasElement } from './domain'

export type CanvasShape = Exclude<CanvasElement['type'], 'arrow'>
export const CANVAS_SIZE = { minWidth: 120, minHeight: 100, maxWidth: 1200, maxHeight: 900 } as const
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, Math.round(value)))

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
export function convertCanvasNode(elements: CanvasElement[], id: string, type: CanvasShape): CanvasElement[] {
  return elements.map(node => {
    if (node.groupId === id && type === 'text') return { ...node, groupId: undefined }
    return node.id === id && node.type !== 'arrow' && node.type !== type
      ? { ...node, ...canvasSize(node), type, groupId: undefined } : node
  })
}
// Fixed bottom/top center ports follow live geometry without changing endpoint IDs.
export function canvasConnector(from: CanvasElement, to: CanvasElement) {
  const a = canvasSize(from), b = canvasSize(to)
  return { x1: from.x + a.width / 2, y1: from.y + a.height, x2: to.x + b.width / 2, y2: to.y }
}
