import type { AppState, SourceCorrection, ThoughtObject } from './domain'
import { reconcileLegacyUi } from './migration'

export interface ReviewTextSnapshot {
  immutableSource: string
  currentText: string
  revisions: { at: string; from: string; to: string }[]
  corrections: SourceCorrection[]
}

const find = (state: AppState, objectId: string): ThoughtObject => {
  const object = state.objects.find(value => value.id === objectId)
  if (!object) throw new Error('Review text update requires an existing capture.')
  return object
}
const textCapture = (state: AppState, objectId: string) => {
  const object = find(state, objectId)
  if (object.source !== 'text') throw new Error('Review text update requires an existing text capture.')
  return object
}

/** Keeps the loaded model identity so the store can serialize against its saved baseline. */
const updateOne = (state: AppState, changed: ThoughtObject): AppState => {
  const next = { ...state, objects: state.objects.map(value => value.id === changed.id ? changed : value) }
  reconcileLegacyUi(next) // validates the transition; persistence re-derives the model from this state
  return next
}

export function reviewTextSnapshot(state: AppState, objectId: string): ReviewTextSnapshot {
  const object = find(state, objectId)
  const model = reconcileLegacyUi(state)
  const captureId = `capture:${objectId}`
  return {
    immutableSource: object.originalContent,
    currentText: object.currentContent ?? object.originalContent,
    revisions: object.history.flatMap(entry => entry.reviewRevision ? [{ at: entry.at, ...entry.reviewRevision }] : []),
    corrections: (model.sourceCorrections ?? []).filter(value => value.captureId === captureId),
  }
}

export function reviseInterpretation(state: AppState, objectId: string, summary: string, at = new Date().toISOString()): AppState {
  const object = textCapture(state, objectId)
  const next = summary.trim()
  if (!next || next === object.interpretation.summary) throw new Error('Revision must provide different non-empty text.')
  const changed: ThoughtObject = { ...object, interpretation: { ...object.interpretation, summary: next },
    history: [...object.history, { at, event: 'Revised interpretation', reviewRevision: { from: object.interpretation.summary, to: next } }] }
  return updateOne(state, changed)
}

export function correctOriginal(state: AppState, objectId: string, correctedContent: string, confirmed: boolean, at = new Date().toISOString()): AppState {
  if (!confirmed) throw new Error('Correcting source text requires explicit confirmation.')
  const object = textCapture(state, objectId)
  const next = correctedContent.trim()
  const current = object.currentContent ?? object.originalContent
  if (!next || next === current) throw new Error('Correction must provide different non-empty text.')
  const correctionId = crypto.randomUUID()
  const changed: ThoughtObject = { ...object, currentContent: next, history: [...object.history, { at, event: 'Corrected source rendering',
    sourceCorrection: { correctionId, from: current, to: next } }] }
  return updateOne(state, changed)
}
