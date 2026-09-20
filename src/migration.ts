import { validTemporalHistory } from './temporalConfirmation'
import type { AppState, ConfirmationGesture, HistoryEvent, Interpretation, PersistedState, SemanticObject, ThoughtObject } from './domain'
import { isCanvasViewport } from './canvasDocument'
import { isAppState } from './store'

// Compatibility authority stays inside migration. Validation uses detached copies;
// only validated projections expose registered history entries to callers.
const persistedConfirmations = new WeakMap<HistoryEvent, ConfirmationGesture>()

export function hasConfirmation(object: ThoughtObject): boolean {
  for (const entry of object.history.slice().reverse()) {
    if (entry.reviewDecision || entry.event.startsWith('Changed type') || entry.event === 'Marked review' || entry.event === 'Marked inbox' || entry.event.includes('status to review') || entry.event.includes('status to inbox') || entry.event.startsWith('Edited type')) return false
    const confirmation = entry.confirmation ?? persistedConfirmations.get(entry)
    if (confirmation) return confirmation.objectId === object.id &&
      confirmation.transition === object.kind && confirmation.summary === object.interpretation.summary &&
      confirmation.source === 'review-confirmation' && Number.isFinite(Date.parse(entry.at))
  }
  return false
}

const copy = <T>(value: T): T => structuredClone(value)
const equal = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b)
const unique = (ids: string[]) => ids.every(id => id.length > 0) && new Set(ids).size === ids.length
const fail = (): never => { throw new Error('Saved model is invalid or ambiguous; stored data must remain untouched.') }

function latest(model: PersistedState, id: string): Interpretation {
  return model.interpretations.filter(item => item.legacy.id === id).at(-1) ?? fail()
}

function evidence(item: ThoughtObject): Interpretation['legacy'] {
  const { originalContent: _content, currentContent: _current, source: _source, createdAt: _created, ...rest } = item
  return copy(rest)
}

function append(model: PersistedState, item: ThoughtObject, previous?: Interpretation, persistedConfirmation?: Interpretation['confirmation']) {
  const capture = model.captures.find(c => c.id === `capture:${item.id}`)
  if (!capture) model.captures.push({ id: `capture:${item.id}`, source: item.source, createdAt: item.createdAt,
    originalContent: item.originalContent, context: item.context, evidence: 'text-only' })
  else if (capture.originalContent !== item.originalContent || capture.source !== item.source || capture.createdAt !== item.createdAt) fail()
  const version = (previous?.version ?? 0) + 1
  const consequential = item.kind === 'action' || item.kind === 'commitment'
  // Text alone never authorizes a gesture. Compatibility requires a structured
  // confirmation from schema-v2 validation or an already validated save baseline.
  const additions = previous ? item.history.slice(previous.legacy.history.length) : []
  const gesture = additions.slice().reverse().find(h => h.event === `Confirmed as ${item.kind}` && Number.isFinite(Date.parse(h.at)) &&
    (h.confirmation ? h.confirmation.objectId === item.id && h.confirmation.transition === item.kind &&
      h.confirmation.summary === item.interpretation.summary && h.confirmation.source === 'review-confirmation' : persistedConfirmation?.transition === item.kind && persistedConfirmation.at === h.at))
  const compatibleItem = copy(item)
  if (persistedConfirmation) registerCompatibility(compatibleItem, persistedConfirmation)
  const activeGesture = hasConfirmation(item) || hasConfirmation(compatibleItem)
  const confirmation = consequential && activeGesture && ['confirmed', 'complete', 'archived'].includes(item.status)
    ? gesture ? { at: gesture.at, transition: item.kind as 'action' | 'commitment',
      ...(gesture.confirmation ? { objectId: item.id, interpretationId: `interpretation:${item.id}:${version}`,
        historyIndex: item.history.indexOf(gesture), source: 'review-confirmation' as const } : {}) }
      : previous?.confirmation?.transition === item.kind ? previous.confirmation : undefined
    : undefined
  const decision = item.history.slice().reverse().find(h => h.reviewDecision || h.confirmation)
  const rejected = decision?.reviewDecision === 'rejected'
  const awaitingReview = previous && previous.reviewState !== 'accepted'
  const accepted = !rejected && item.kind !== 'reminder' && (!consequential || !!confirmation) &&
    (!awaitingReview || !!gesture) && !['review', 'inbox'].includes(item.status)
  const interpretation: Interpretation = {
    id: `interpretation:${item.id}:${version}`, version, previousId: previous?.id,
    captureIds: [`capture:${item.id}`], recordedAt: item.history.at(-1)?.at ?? item.createdAt,
    summary: item.interpretation.summary, rationale: item.interpretation.rationale, confidence: item.confidence,
    proposedKind: item.kind === 'reminder' ? 'unresolved' : item.kind,
    proposedAction: item.kind === 'action' && !confirmation ? { summary: item.interpretation.summary } : undefined,
    reviewState: rejected ? 'rejected' : accepted ? 'accepted' : 'review', confirmation,
    proposedReminder: item.kind === 'reminder' ? { id: `reminder:${item.id}`, captureIds: [`capture:${item.id}`],
      trigger: { kind: 'unresolved', wording: item.originalContent, legacyDate: item.interpretation.suggestedDate ?? item.metadata.deadline },
      deliveryState: 'needs-review' } : previous?.proposedReminder,
    legacy: evidence(item)
  }
  model.interpretations.push(interpretation)
  const withdrawn = model.semanticObjects.find(o => o.id === item.id)
  model.semanticObjects = model.semanticObjects.filter(o => o.id !== item.id)
  // Unresolved reminders and unconfirmed consequential meaning remain interpretations.
  if (item.kind !== 'reminder' && (!consequential || confirmation)) {
    const metadata = copy(item.metadata)
    // Legacy timing is evidence, never a confirmed fixed deadline or event.
    delete metadata.deadline
    const object: SemanticObject = { id: item.id, kind: item.kind, captureIds: interpretation.captureIds,
      interpretationIds: model.interpretations.filter(i => i.legacy.id === item.id).map(i => i.id),
      summary: interpretation.summary, status: accepted ? item.status : 'review', metadata,
      reminders: interpretation.proposedReminder ? [copy(interpretation.proposedReminder)] : [] }
    model.semanticObjects.push(object)
  }
  if (withdrawn && !model.semanticObjects.some(o => o.id === item.id)) {
    model.semanticObjects.push({ ...withdrawn, status: 'review' })
  }
  model.relationships = model.relationships.filter(r => r.sourceId !== item.id)
  item.relationships.forEach((r, index) => model.relationships.push({ ...copy(r), id: `relationship:${item.id}:${index}`,
    sourceId: item.id, scope: 'semantic', provenance: { interpretationId: interpretation.id, evidence: 'legacy-unverified' } }))
}

/** Pure conversion: never writes storage, guesses reminder targets, or schedules events. */
export function migrateLegacyState(value: unknown): PersistedState {
  if (!isAppState(value) || Object.keys(value).some(key => !['objects', 'canvas'].includes(key)) || 'schemaVersion' in value || value.model !== undefined ||
      !unique(value.objects.map(o => o.id)) || !unique(value.canvas.map(e => e.id))) return fail()
  const model: PersistedState = { schemaVersion: 2, captures: [], interpretations: [], semanticObjects: [],
    calendarEvents: [], relationships: [], legacyUiIds: value.objects.map(o => o.id), canvas: copy(value.canvas) }
  value.objects.forEach(item => append(model, item))
  return model
}

/** Existing screens receive a projection; canonical evidence travels through AppState spreads. */
export function legacyUiProjection(model: PersistedState): AppState {
  if (!isPersistedState(model)) return fail()
  return projectModel(model)
}

function registerCompatibility(item: ThoughtObject, confirmation: NonNullable<Interpretation['confirmation']>) {
  const entry = item.history.find(h => h.at === confirmation.at && h.event === `Confirmed as ${confirmation.transition}`)
  if (entry && !entry.confirmation) persistedConfirmations.set(entry, {
    objectId: item.id, transition: confirmation.transition, summary: item.interpretation.summary, source: 'review-confirmation'
  })
}

function projectModel(model: PersistedState): AppState {
  const objects = model.legacyUiIds.map(id => {
    const reading = latest(model, id)
    const capture = model.captures.find(c => c.id === reading.captureIds[0]) ?? fail()
    const semantic = model.semanticObjects.find(o => o.id === id)
    const correction = (model.sourceCorrections ?? []).filter(value => value.captureId === capture.id).at(-1)
    const item: ThoughtObject = { ...copy(reading.legacy), originalContent: capture.originalContent,
      ...(correction ? { currentContent: correction.correctedContent } : {}), source: capture.source,
      createdAt: capture.createdAt, status: semantic?.status ??
        (reading.legacy.kind !== 'action' && reading.legacy.kind !== 'commitment' &&
          (reading.legacy.status === 'archived' || reading.legacy.status === 'complete') ? reading.legacy.status : 'review' as const) }
    if (reading.confirmation) registerCompatibility(item, reading.confirmation)
    return item
  })
  return { objects, canvas: copy(model.canvas), ...(model.canvasViewport === undefined ? {} : { canvasViewport: copy(model.canvasViewport) }), model: copy(model) }
}

/** Append evidence versions on UI changes; source edits and destructive removals fail closed. */
export function reconcileLegacyUi(state: AppState): PersistedState {
  if (!isAppState(state)) return fail()
  if (!state.model) {
    const model = migrateLegacyState({ objects: state.objects, canvas: state.canvas })
    if (state.canvasViewport !== undefined) model.canvasViewport = copy(state.canvasViewport)
    return model
  }
  if (!isPersistedState(state.model)) return fail()
  const model = copy(state.model)
  if (!unique(state.objects.map(o => o.id)) || !unique(state.canvas.map(e => e.id)) ||
      model.legacyUiIds.some(id => !state.objects.some(o => o.id === id))) return fail()
  const projection = legacyUiProjection(model)
  for (const item of state.objects) {
    const old = projection.objects.find(o => o.id === item.id)
    if (old && equal(old, item)) continue
    if (old && (!equal(item.history.slice(0, old.history.length), old.history) || item.confidence !== old.confidence)) return fail()
    if (old && !equal(item.interpretation, old.interpretation)) {
      // Every summary change since the saved baseline must be an unbroken chain of recorded revisions.
      let summary = old.interpretation.summary
      for (const { reviewRevision } of item.history.slice(old.history.length)) {
        if (!reviewRevision) continue
        if (reviewRevision.from !== summary) return fail()
        summary = reviewRevision.to
      }
      if (summary !== item.interpretation.summary) return fail()
    }
    const additions = old ? item.history.slice(old.history.length) : item.history
    if (additions.some(h => h.event.startsWith('Confirmed as ') && !h.confirmation)) return fail()
    // A capture can be reviewed while its first save is pending/failed. Retain a
    // proposed baseline before recording the dedicated gestures in that same save.
    if (!old && additions.some(h => h.confirmation)) {
      const firstGesture = item.history.findIndex(h => h.confirmation)
      append(model, { ...item, status: 'review', history: item.history.slice(0, firstGesture) })
      append(model, item, latest(model, item.id))
    } else append(model, item, old ? latest(model, item.id) : undefined, old ? latest(model, item.id).confirmation : undefined)
    // Source corrections are derived from their audit events so one history entry is the only writer.
    for (const { at, sourceCorrection } of additions) {
      if (!sourceCorrection) continue
      const captureId = latest(model, item.id).captureIds[0]
      const chain = (model.sourceCorrections ?? []).filter(c => c.captureId === captureId)
      const current = chain.at(-1)?.correctedContent ?? model.captures.find(c => c.id === captureId)?.originalContent
      if (sourceCorrection.from !== current || !sourceCorrection.to.trim()) return fail()
      model.sourceCorrections = [...(model.sourceCorrections ?? []), { id: sourceCorrection.correctionId, captureId, correctedAt: at,
        correctedContent: sourceCorrection.to, ...(chain.length ? { previousId: chain.at(-1)!.id } : {}) }]
    }
  }
  model.legacyUiIds = state.objects.map(o => o.id)
  model.canvas = copy(state.canvas)
  if (state.canvasViewport !== undefined) model.canvasViewport = copy(state.canvasViewport)
  if (state.temporalHistory !== undefined) {
    const previousHistory = model.temporalHistory ?? []
    if (!equal(state.temporalHistory.slice(0, previousHistory.length), previousHistory)) return fail()
    model.temporalHistory = copy(state.temporalHistory)
  }
  if (!isPersistedState(model)) return fail()
  return model
}

/** Corrections are an append-only, per-capture chain over text captures: the first has no
 * previousId and each later one names the immediately preceding correction of that capture. */
function validSourceCorrections(m: PersistedState): boolean {
  const corrections = m.sourceCorrections
  if (!Array.isArray(corrections) || !unique(corrections.map(c => c?.id))) return false
  const tails = new Map<string, string>()
  for (const c of corrections) {
    if (!c || typeof c !== 'object' || typeof c.id !== 'string' || !c.id || typeof c.captureId !== 'string' ||
      typeof c.correctedContent !== 'string' || !c.correctedContent.trim() || typeof c.correctedAt !== 'string' ||
      !Number.isFinite(Date.parse(c.correctedAt)) || (c.previousId !== undefined && typeof c.previousId !== 'string')) return false
    if (Object.keys(c).some(key => !['id', 'captureId', 'correctedAt', 'correctedContent', 'previousId'].includes(key))) return false
    if (m.captures.find(capture => capture.id === c.captureId)?.source !== 'text') return false
    if (tails.get(c.captureId) !== c.previousId) return false
    tails.set(c.captureId, c.id)
  }
  return true
}

/** Validate full entity data and cross-record invariants before exposing it to legacy screens. */
export function isPersistedState(value: unknown): value is PersistedState {
  try {
    if (!value || typeof value !== 'object') return false
    const m = value as PersistedState
    if (Object.keys(m).some(key => !['schemaVersion', 'captures', 'sourceCorrections', 'interpretations', 'semanticObjects', 'calendarEvents', 'relationships', 'legacyUiIds', 'canvas', 'canvasViewport', 'temporalHistory'].includes(key))) return false
    if (m.canvasViewport !== undefined && !isCanvasViewport(m.canvasViewport)) return false
    if (m.schemaVersion !== 2 || ![m.captures, m.interpretations, m.semanticObjects, m.calendarEvents,
      m.relationships, m.legacyUiIds, m.canvas].every(Array.isArray)) return false
    if (![m.captures, m.interpretations, m.semanticObjects, m.calendarEvents, m.relationships, m.canvas]
      .every(items => unique(items.map(i => i.id))) || !unique(m.legacyUiIds)) return false
    if (!m.captures.every(c => c.evidence === 'text-only' && typeof c.originalContent === 'string' &&
      typeof c.createdAt === 'string' && ['text', 'voice', 'canvas'].includes(c.source) &&
      (c.context === undefined || typeof c.context === 'string'))) return false
    if (m.sourceCorrections !== undefined && !validSourceCorrections(m)) return false
    // Reconstruct supported adapter versions to verify semantic derivations and history links.
    const rebuilt: PersistedState = { schemaVersion: 2, captures: copy(m.captures), interpretations: [],
      semanticObjects: [], calendarEvents: [], relationships: [], legacyUiIds: copy(m.legacyUiIds), canvas: copy(m.canvas) }
    for (const reading of m.interpretations) {
      const capture = m.captures.find(c => c.id === reading.captureIds?.[0])
      if (!capture || capture.id !== `capture:${reading.legacy.id}`) return false
      const item = { ...reading.legacy, originalContent: capture.originalContent, source: capture.source, createdAt: capture.createdAt }
      if (!isAppState({ objects: [item], canvas: [] })) return false
      const previous = rebuilt.interpretations.filter(i => i.legacy.id === item.id).at(-1)
      if (previous && !equal(item.history.slice(0, previous.legacy.history.length), previous.legacy.history)) return false
      append(rebuilt, item, previous, reading.confirmation)
      if (!equal(rebuilt.interpretations.at(-1), reading)) return false
    }
    if (!equal(rebuilt.semanticObjects, m.semanticObjects) || !equal(rebuilt.relationships, m.relationships)) return false
    if (m.captures.length !== new Set(m.interpretations.flatMap(i => i.captureIds)).size ||
        m.legacyUiIds.length !== new Set(m.interpretations.map(i => i.legacy.id)).size) return false
    // Events have their own scheduling identity; the legacy UI neither authors nor projects them.
    if (!m.calendarEvents.every(e => typeof e.title === 'string' && typeof e.startsAt === 'string' &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(e.startsAt) && Number.isFinite(Date.parse(e.startsAt)) && typeof e.temporalContext === 'string' && e.temporalContext.length > 0 &&
      ['scheduled', 'cancelled'].includes(e.status) && Array.isArray(e.objectIds) &&
      e.objectIds.every(id => m.semanticObjects.some(o => o.id === id)) && Array.isArray(e.captureIds) &&
      e.captureIds.every(id => m.captures.some(c => c.id === id)))) return false
    return validTemporalHistory(m) && isAppState(projectModel(m))
  } catch { return false }
}
