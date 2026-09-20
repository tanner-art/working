import type { AppState } from './domain'
import { DEFAULT_CANVAS_VIEWPORT, isCanvasElements, isCanvasViewport, type CanvasDocument } from './canvasDocument'

/** One current canvas. The host owns atomic aggregate persistence and save errors. */
export interface CanvasRepository {
  read(): CanvasDocument
  write(document: CanvasDocument): void
}

/** Adapt the existing local/account workspace; never create a competing storage key. */
export function createCanvasRepository(
  readState: () => AppState,
  updateState: (change: (state: AppState) => AppState) => void,
): CanvasRepository {
  return {
    read() {
      const state = readState()
      return structuredClone({ elements: state.canvas, viewport: state.canvasViewport ?? DEFAULT_CANVAS_VIEWPORT })
    },
    write(document) {
      if (!isCanvasElements(document.elements) || !isCanvasViewport(document.viewport)) {
        throw Error('Invalid canvas changes. Saved work has been left untouched.')
      }
      const snapshot = structuredClone(document)
      updateState(state => ({ ...state, canvas: snapshot.elements, canvasViewport: snapshot.viewport }))
    },
  }
}
