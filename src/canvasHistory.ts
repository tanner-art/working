import type { CanvasElement } from './domain'

export interface CanvasHistory {
  past: CanvasElement[][]
  present: CanvasElement[]
  future: CanvasElement[][]
}

const LIMIT = 25

export function commitCanvas(history: CanvasHistory, next: CanvasElement[]): CanvasHistory {
  if (sameCanvas(history.present, next)) return history
  return {
    past: [...history.past.slice(-(LIMIT - 1)), history.present],
    present: next,
    future: []
  }
}

export function undoCanvas(history: CanvasHistory): CanvasHistory {
  const previous = history.past.at(-1)
  if (!previous) return history
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future].slice(0, LIMIT)
  }
}

export function redoCanvas(history: CanvasHistory): CanvasHistory {
  const next = history.future[0]
  if (!next) return history
  return {
    past: [...history.past.slice(-(LIMIT - 1)), history.present],
    present: next,
    future: history.future.slice(1)
  }
}

export function sameCanvas(left: CanvasElement[], right: CanvasElement[]) {
  return JSON.stringify(left) === JSON.stringify(right)
}
