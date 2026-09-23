import type { AppState } from './domain'
import { reconcileLegacyUi } from './migration'
import { currentInterpretations, confirmedSemanticObjects } from './morningDigest'

export interface HomeBetaModel {
  captureCount: number
  confirmationCount: number
  commitmentCount: number
  actionCount: number
  canvasElementCount: number
  canvasBankDocCount: number
}

export function buildHomeBeta(state: AppState): HomeBetaModel {
  const model = reconcileLegacyUi(state)

  const captures = model.captures.length
  const interpretations = currentInterpretations(model)
  const confirmations = interpretations.filter(i => i.confirmation).length
  const confirmed = confirmedSemanticObjects(model)
  const commitments = confirmed.filter(o => o.kind === 'commitment').length
  const actions = confirmed.filter(o => o.kind === 'action').length
  const canvasElements = model.canvas.length
  const canvasDocuments = model.canvasBank?.canvases.length ?? 0

  return {
    captureCount: captures,
    confirmationCount: confirmations,
    commitmentCount: commitments,
    actionCount: actions,
    canvasElementCount: canvasElements,
    canvasBankDocCount: canvasDocuments
  }
}
