/** Selecting a canvas object replaces, rather than combines with, a lasso selection. */
export function canvasObjectSelection(id: string) {
  return { selectedId: id, selectedStrokeIds: new Set<string>(), refinementCandidateId: null }
}
