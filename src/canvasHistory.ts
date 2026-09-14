import type { CanvasElement } from './domain'

// Session-only undo/redo for the canvas. See docs/DECISIONS.md D-010 (resolves OD-002):
// this stack is intentionally not persisted across reload and only ever touches
// AppState.canvas, never AppState.objects.
//
// Ported from the archived wip/pre-orchestration src/canvasHistory.ts (see
// docs/ARCHIVE_SALVAGE_AUDIT.md item 1): a pure past/present/future stack capped at
// CANVAS_HISTORY_LIMIT steps, with sameCanvas no-op dedupe so committing an unchanged
// canvas never creates a spurious undo step.
//
// One narrow integration adaptation versus the archived module: `present` here is a
// second, in-memory copy of the current canvas, not the sole source of truth — D-010
// requires AppState.canvas to remain the single localStorage-backed current-canvas
// value. App.tsx writes AppState.canvas and this history's `present` together, from
// the same returned CanvasHistory, in the same handler, so the two can never drift.
export const CANVAS_HISTORY_LIMIT = 25

export interface CanvasHistory {
  past: CanvasElement[][]
  present: CanvasElement[]
  future: CanvasElement[][]
}

export function emptyCanvasHistory(initial: CanvasElement[]): CanvasHistory {
  return { past: [], present: initial, future: [] }
}

export function sameCanvas(a: CanvasElement[], b: CanvasElement[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function bounded<T>(items: T[]): T[] {
  return items.length > CANVAS_HISTORY_LIMIT ? items.slice(items.length - CANVAS_HISTORY_LIMIT) : items
}

export function canUndoCanvas(history: CanvasHistory): boolean {
  return history.past.length > 0
}

export function canRedoCanvas(history: CanvasHistory): boolean {
  return history.future.length > 0
}

// Record one committed, atomic canvas edit (add/connect/delete/a completed drag/a
// text-edit commit), never a fine-grained log of every pointer-move or keystroke. A
// no-op commit (next is deep-equal to present) is dropped instead of pushed onto the
// stack. Any pending redo is discarded, matching standard editor undo/redo semantics.
export function commitCanvas(history: CanvasHistory, next: CanvasElement[]): CanvasHistory {
  if (sameCanvas(history.present, next)) return history
  return { past: bounded([...history.past, history.present]), present: next, future: [] }
}

export function undoCanvas(history: CanvasHistory): CanvasHistory {
  if (history.past.length === 0) return history
  const previous = history.past[history.past.length - 1]
  return { past: history.past.slice(0, -1), present: previous, future: bounded([history.present, ...history.future]) }
}

export function redoCanvas(history: CanvasHistory): CanvasHistory {
  if (history.future.length === 0) return history
  const [next, ...rest] = history.future
  return { past: bounded([...history.past, history.present]), present: next, future: rest }
}
