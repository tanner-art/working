import type { CanvasRecord } from './domain'

export function filterCanvasesByTitle(canvases: readonly CanvasRecord[], query: string): CanvasRecord[] {
  const normalizedQuery = query.trim().toLowerCase()
  return normalizedQuery
    ? canvases.filter(canvas => canvas.title.toLowerCase().includes(normalizedQuery))
    : [...canvases]
}
