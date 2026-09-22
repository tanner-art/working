import type { CanvasElement, CanvasViewport } from './domain'
import type { CanvasRepository } from './canvasRepository'
import type { CanvasHistory } from './canvasHistory'
import { canRedoCanvas, canUndoCanvas, commitCanvas, emptyCanvasHistory, redoCanvas, sameCanvas, undoCanvas } from './canvasHistory'

/** Editing lifetime is the workspace lifetime, independent of the visible Canvas. */
export function createCanvasSession(repository: CanvasRepository) {
  let history = emptyCanvasHistory(repository.read().elements)
  let textEdit: string | undefined
  const writeElements = (next: CanvasHistory) => {
    repository.write({ ...repository.read(), elements: next.present })
    history = next
  }
  return {
    get canUndo() { return canUndoCanvas(history) },
    get canRedo() { return canRedoCanvas(history) },
    finishText() { textEdit = undefined },
    editText(id: string, text: string) {
      const next = history.present.map(item => item.id === id ? { ...item, text } : item)
      if (sameCanvas(history.present, next)) return
      // Persist current expression on every change, without adding per-key undo steps.
      writeElements(textEdit === id ? { ...history, present: next } : commitCanvas(history, next))
      textEdit = id
    },
    commit(elements: CanvasElement[]) {
      writeElements(commitCanvas(history, elements))
      textEdit = undefined
    },
    undo() {
      writeElements(undoCanvas(history))
      textEdit = undefined
    },
    redo() {
      writeElements(redoCanvas(history))
      textEdit = undefined
    },
    setViewport(viewport: CanvasViewport) {
      repository.write({ ...repository.read(), viewport })
    },
  }
}
