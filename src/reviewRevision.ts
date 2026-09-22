import type { AppState, SourceCorrection, ThoughtObject } from './domain'
import { reconcileLegacyUi } from './migration'

export interface ReviewTextSnapshot {
  immutableSource: string
  currentText: string
  revisions: { at: string; from: string; to: string }[]
  corrections: SourceCorrection[]
  progression: ReviewProgressionEntry[]
}

export interface ReviewProgressionEntry {
  id: string
  at: string
  kind: 'capture' | 'correction' | 'interpretation'
  label: string
  text: string
  previousText?: string
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
  const revisions = object.history.flatMap((entry, index) => entry.reviewRevision ? [{ id: `interpretation-${index}`, at: entry.at, ...entry.reviewRevision }] : [])
  const corrections = (model.sourceCorrections ?? []).filter(value => value.captureId === captureId)
  const progression: ReviewProgressionEntry[] = [
    { id: captureId, at: object.createdAt, kind: 'capture' as const, label: 'Original capture', text: object.originalContent },
    ...corrections.map(value => ({ id: value.id, at: value.correctedAt, kind: 'correction' as const,
      label: 'Thought text revised', text: value.correctedContent,
      previousText: object.history.find(entry => entry.sourceCorrection?.correctionId === value.id)?.sourceCorrection?.from })),
    ...revisions.map(value => ({ id: value.id, at: value.at, kind: 'interpretation' as const,
      label: 'Organized meaning revised', text: value.to, previousText: value.from })),
  ].sort((left, right) => Date.parse(left.at) - Date.parse(right.at))
  return {
    immutableSource: object.originalContent,
    currentText: object.currentContent ?? object.originalContent,
    revisions: revisions.map(({ at, from, to }) => ({ at, from, to })),
    corrections,
    progression,
  }
}

/** Every status that carries a live confirmation: the persisted projection drops it when the summary changes. */
export const revisionNeedsReconfirmation = (object: ThoughtObject) =>
  (object.status === 'confirmed' || object.status === 'complete' || object.status === 'archived') &&
  (object.kind === 'action' || object.kind === 'commitment')

export const revisionReviewNotice = (object: ThoughtObject) => {
  if (!revisionNeedsReconfirmation(object)) return undefined
  const lead = `Revising this ${object.status} ${object.kind} returns it to Review`
  if (object.status === 'complete') return `${lead}. It is no longer marked complete until you confirm the new wording; its history is kept.`
  if (object.status === 'archived') return `${lead}. It leaves the archive until you confirm the new wording; its history is kept.`
  return `${lead}. It leaves your confirmed list until you confirm the new wording.`
}

export const hasUnsavedReviewDrafts = (object: ThoughtObject, currentText: string, correction: string, revision: string) =>
  (object.source === 'text' && correction.trim() !== currentText) || revision.trim() !== object.interpretation.summary

export function reviseInterpretation(state: AppState, objectId: string, summary: string, at = new Date().toISOString()): AppState {
  const object = find(state, objectId)
  const next = summary.trim()
  if (!next || next === object.interpretation.summary) throw new Error('Revision must provide different non-empty text.')
  // D-009: a confirmation authorizes one summary, so revising a confirmed, complete or archived consequential object returns it to Review now, not on reload.
  const status = revisionNeedsReconfirmation(object) ? 'review' : object.status
  const changed: ThoughtObject = { ...object, status, interpretation: { ...object.interpretation, summary: next },
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
