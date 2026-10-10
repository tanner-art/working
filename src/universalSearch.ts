import type { AppState, CanvasElement, CanvasRecord, CaptureRecord, PersistedState, SemanticObject, SourceCorrection } from './domain'
import { bankFromLegacy, isCanvasRecord } from './canvasBank'
import { reconcileLegacyUi } from './migration'

export type SearchKind = 'capture' | 'action' | 'commitment' | 'reminder' | 'idea' | 'canvas'
export type SearchField = 'original' | 'corrected-source' | 'current-meaning' | 'reminder-source' | 'canvas-title' | 'canvas-element'
export interface SearchDocument {
  kind: SearchKind
  /** Stable source identity, never a position in a result list. */
  id: string
  captureIds: string[]
  interpretationIds: string[]
  targetId?: string
  fields: Partial<Record<SearchField, string>>
}
export interface SearchResult {
  document: SearchDocument
  matchedFields: SearchField[]
}

const fieldOrder: SearchField[] = ['original', 'corrected-source', 'current-meaning', 'reminder-source', 'canvas-title', 'canvas-element']
const kindOrder: SearchKind[] = ['capture', 'action', 'commitment', 'reminder', 'idea', 'canvas']
const kindSet = new Set<SearchKind>(kindOrder)
const validId = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 200
const validText = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
const stableIds = (value: unknown): value is string[] => Array.isArray(value) && value.every(validId) && new Set(value).size === value.length
const normalize = (value: string) => value.normalize('NFKC').toLocaleLowerCase('en-US')

function textFields(fields: Partial<Record<SearchField, string>>): Partial<Record<SearchField, string>> {
  const safe: Partial<Record<SearchField, string>> = {}
  for (const field of fieldOrder) if (validText(fields[field])) safe[field] = fields[field]!.trim()
  return safe
}

/** Invalid or ambiguous source identities are omitted, never guessed or merged. */
export function createUniversalSearchIndex(input: readonly SearchDocument[]) {
  let entries = compile(input)
  return {
    get size() { return entries.length },
    /** Replace from a fresh source projection after edits, merges, or account reloads. */
    replace(next: readonly SearchDocument[]) { entries = compile(next) },
    query(raw: string, limit = 100): SearchResult[] {
      const terms = normalize(raw.trim()).split(/\s+/).filter(Boolean)
      if (!terms.length || !Number.isFinite(limit) || limit <= 0) return []
      const results: SearchResult[] = []
      for (const entry of entries) {
        if (!terms.every(term => entry.fields.some(([, value]) => value.includes(term)))) continue
        const matchedFields = entry.fields.filter(([, value]) => value && terms.some(term => value.includes(term))).map(([field]) => field)
        if (!matchedFields.length) continue
        results.push({ document: { ...entry.document, captureIds: [...entry.document.captureIds],
          interpretationIds: [...entry.document.interpretationIds], fields: { ...entry.document.fields } }, matchedFields })
        if (results.length >= limit) break
      }
      return results
    },
  }
}

function compile(input: readonly SearchDocument[]) {
  const seen = new Map<string, SearchDocument>()
  const ambiguous = new Set<string>()
  for (const source of input) {
    if (!source || !kindSet.has(source.kind) || !validId(source.id) || !stableIds(source.captureIds) || !stableIds(source.interpretationIds)) continue
    const key = `${source.kind}\u0000${source.id}`
    if (seen.has(key)) { seen.delete(key); ambiguous.add(key); continue }
    if (ambiguous.has(key)) continue
    const fields = textFields(source.fields ?? {})
    if (!Object.keys(fields).length) continue
    seen.set(key, { kind: source.kind, id: source.id, captureIds: [...source.captureIds],
      interpretationIds: [...source.interpretationIds], ...(validId(source.targetId) ? { targetId: source.targetId } : {}), fields })
  }
  const entries = [...seen.values()].sort((a, b) => kindOrder.indexOf(a.kind) - kindOrder.indexOf(b.kind) || a.id.localeCompare(b.id))
    .map(document => ({ document, fields: fieldOrder.map(field => [field, document.fields[field] ? normalize(document.fields[field]) : ''] as const) }))
  return entries
}

function captureDocuments(captures: readonly CaptureRecord[], corrections: readonly SourceCorrection[]): SearchDocument[] {
  const latest = new Map<string, SourceCorrection>()
  for (const correction of corrections) if (validId(correction?.captureId) && validText(correction?.correctedContent)) latest.set(correction.captureId, correction)
  return captures.flatMap(capture => validId(capture?.id) && validText(capture?.originalContent) ? [{
    kind: 'capture' as const, id: capture.id, captureIds: [capture.id], interpretationIds: [],
    fields: { original: capture.originalContent, ...(latest.has(capture.id) ? { 'corrected-source': latest.get(capture.id)!.correctedContent } : {}) },
  }] : [])
}

function semanticDocuments(objects: readonly SemanticObject[], captures: Set<string>, interpretations: Set<string>): SearchDocument[] {
  return objects.flatMap(object => {
    if (!object || !['action', 'commitment', 'idea'].includes(object.kind) || !validId(object.id) || !validText(object.summary) ||
        !stableIds(object.captureIds) || !object.captureIds.length || !object.captureIds.every(id => captures.has(id)) ||
        !stableIds(object.interpretationIds) || !object.interpretationIds.length || !object.interpretationIds.every(id => interpretations.has(id)) ||
        !['confirmed', 'complete', 'archived'].includes(object.status)) return []
    return [{ kind: object.kind as SearchKind, id: object.id, captureIds: [...object.captureIds],
      interpretationIds: [...object.interpretationIds], fields: { 'current-meaning': object.summary } }]
  })
}

function reminderDocuments(model: PersistedState, captures: Map<string, CaptureRecord>, interpretations: Set<string>, corrections: readonly SourceCorrection[]): SearchDocument[] {
  const targets = new Set(model.semanticObjects.filter(value => value && validId(value.id)).map(value => value.id))
  const latestCorrection = new Map<string, string>()
  for (const correction of corrections) if (validId(correction?.captureId) && validText(correction?.correctedContent)) latestCorrection.set(correction.captureId, correction.correctedContent)
  return (Array.isArray(model.reminderInstructions) ? model.reminderInstructions : []).flatMap(instruction => {
    const source = model.interpretations.find(reading => reading?.id === instruction?.sourceInterpretationId)
    const current = source && model.interpretations.filter(reading => reading?.legacy?.id === source.legacy?.id).at(-1)
    const creation = source?.legacy?.history?.find(entry => entry.reminderInstruction?.instructionId === instruction?.id && entry.reminderInstruction.action === 'created')?.reminderInstruction
    if (!instruction || !validId(instruction.id) || !validId(instruction.targetId) || !targets.has(instruction.targetId) ||
        !stableIds(instruction.captureIds) || !instruction.captureIds.length || !instruction.captureIds.every(id => captures.has(id)) ||
        !validId(instruction.sourceInterpretationId) || !interpretations.has(instruction.sourceInterpretationId) ||
        !source || !instruction.captureIds.every(id => source.captureIds?.includes(id)) ||
        creation?.targetId !== instruction.targetId || creation.mode !== instruction.mode ||
        !current || current.reviewState === 'rejected' || current.legacy.kind !== 'reminder' || current.legacy.status !== 'confirmed' ||
        !current.legacy.history?.some(entry => entry.reminderInstruction?.instructionId === instruction.id && entry.reminderInstruction.action === 'created')) return []
    return [{ kind: 'reminder' as const, id: instruction.id, captureIds: [...instruction.captureIds],
      interpretationIds: [instruction.sourceInterpretationId], targetId: instruction.targetId,
      fields: { 'reminder-source': instruction.captureIds.map(id => latestCorrection.get(id) ?? captures.get(id)!.originalContent).join(' ') } }]
  })
}

function canvasText(elements: readonly CanvasElement[]): string {
  return elements.filter(element => element && element.type !== 'arrow' && validText(element.text)).map(element => element.text!.trim()).join(' ')
}
function canvasDocuments(canvases: readonly CanvasRecord[]): SearchDocument[] {
  return canvases.flatMap(canvas => isCanvasRecord(canvas) ? [{ kind: 'canvas' as const, id: canvas.id,
    captureIds: [], interpretationIds: [], fields: { 'canvas-title': canvas.title, 'canvas-element': canvasText(canvas.elements) } }] : [])
}

/** Canonical source adapter shared by local and account projections. It never mutates or stores the source. */
export function searchDocumentsFromModel(model: PersistedState): SearchDocument[] {
  if (!model || !Array.isArray(model.captures) || !Array.isArray(model.semanticObjects) || !Array.isArray(model.interpretations)) return []
  const captures = new Map(model.captures.filter(value => value && validId(value.id) && validText(value.originalContent)).map(value => [value.id, value]))
  const interpretations = new Set(model.interpretations.filter(value => value && validId(value.id)).map(value => value.id))
  const corrections = Array.isArray(model.sourceCorrections) ? model.sourceCorrections : []
  const bank = model.canvasBank?.canvases ?? bankFromLegacy(Array.isArray(model.canvas) ? model.canvas : [], model.canvasViewport).canvases
  return [...captureDocuments(model.captures, corrections),
    ...semanticDocuments(model.semanticObjects, new Set(captures.keys()), interpretations), ...reminderDocuments(model, captures, interpretations, corrections),
    ...canvasDocuments(Array.isArray(bank) ? bank : [])]
}

/** A loaded local or account AppState uses its canonical model, avoiding duplicate UI projections. */
export function searchDocumentsFromAppState(state: AppState): SearchDocument[] {
  if (!state) return []
  try { return searchDocumentsFromModel(reconcileLegacyUi(state)) }
  catch { return [] }
}
