import type { AppState } from './domain'
import { isCanvasElements, isCanvasViewport, type CanvasDocument } from './canvasDocument'
import { canvasBankForState } from './canvasBank'

/** One current canvas. The host owns atomic aggregate persistence and save errors. */
export interface CanvasRepository {
  read(): CanvasDocument
  write(document: CanvasDocument): void
}

/** Adapt the existing local/account workspace; never create a competing storage key. */
export function createCanvasRepository(
  canvasId: string,
  readState: () => AppState,
  updateState: (change: (state: AppState) => AppState) => void,
): CanvasRepository {
  return {
    read() {
      const state = readState()
      const record = canvasBankForState(state).canvases.find(item => item.id === canvasId)
      if (!record) throw Error('Canvas no longer exists. Return to the Bank and reopen it.')
      return structuredClone({ elements: record.elements, viewport: record.viewport })
    },
    write(document) {
      if (!isCanvasElements(document.elements) || !isCanvasViewport(document.viewport)) {
        throw Error('Invalid canvas changes. Saved work has been left untouched.')
      }
      const snapshot = structuredClone(document)
      updateState(state => {
        const bank = canvasBankForState(state)
        let found = false
        const canvases = bank.canvases.map(item => {
          if (item.id !== canvasId) return item
          found = true
          const now = new Date().toISOString()
          return { ...item, elements: snapshot.elements, viewport: snapshot.viewport,
            updatedAt: Date.parse(now) >= Date.parse(item.updatedAt) ? now : item.updatedAt }
        })
        if (!found) throw Error('Canvas no longer exists. Return to the Bank and reopen it.')
        return { ...state, canvasBank: { canvases } }
      })
    },
  }
}
