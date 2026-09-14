import type { AppState, Interpretation, PersistedState, SemanticObject, ThoughtObject } from './domain'
import { isAppState } from './store'

const copy = <T>(value: T): T => structuredClone(value)
const equal = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b)
const unique = (ids: string[]) => ids.every(id => id.length > 0) && new Set(ids).size === ids.length
const fail = (): never => { throw new Error('Saved model is invalid or ambiguous; stored data must remain untouched.') }

function latest(model: PersistedState, id: string): Interpretation {
  return model.interpretations.filter(item => item.legacy.id === id).at(-1) ?? fail()
}

function evidence(item: ThoughtObject): Interpretation['legacy'] {
  const { originalContent: _content, source: _source, createdAt: _created, ...rest } = item
  return copy(rest)
}

function append(model: PersistedState, item: ThoughtObject, previous?: Interpretation) {
  const capture = model.captures.find(c => c.id === `capture:${item.id}`)
  if (!capture) model.captures.push({ id: `capture:${item.id}`, source: item.source, createdAt: item.createdAt,
    originalContent: item.originalContent, context: item.context, evidence: 'text-only' })
  else if (capture.originalContent !== item.originalContent || capture.source !== item.source || capture.createdAt !== item.createdAt) fail()
  const version = (previous?.version ?? 0) + 1
  const consequential = item.kind === 'action' || item.kind === 'commitment'
  // Only a newly recorded dedicated gesture can authorize a consequential transition.
  const gesture = previous && item.history.slice(previous.legacy.history.length)
    .find(h => h.event === `Confirmed as ${item.kind}` && h.at.length > 0)
  const confirmation = consequential && ['confirmed', 'complete', 'archived'].includes(item.status)
    ? gesture ? { at: gesture.at, transition: item.kind as 'action' | 'commitment' }
      : previous?.confirmation?.transition === item.kind ? previous.confirmation : undefined
    : undefined
  const accepted = item.kind !== 'reminder' && (!consequential || !!confirmation) && !['review', 'inbox'].includes(item.status)
  const interpretation: Interpretation = {
    id: `interpretation:${item.id}:${version}`, version, previousId: previous?.id,
    captureIds: [`capture:${item.id}`], recordedAt: item.history.at(-1)?.at ?? item.createdAt,
    summary: item.interpretation.summary, rationale: item.interpretation.rationale, confidence: item.confidence,
    proposedKind: item.kind === 'reminder' ? 'unresolved' : item.kind,
    proposedAction: item.kind === 'action' && !confirmation ? { summary: item.interpretation.summary } : undefined,
    reviewState: accepted ? 'accepted' : 'review', confirmation,
    proposedReminder: item.kind === 'reminder' ? { id: `reminder:${item.id}`, captureIds: [`capture:${item.id}`],
      trigger: { kind: 'unresolved', wording: item.originalContent, legacyDate: item.interpretation.suggestedDate ?? item.metadata.deadline },
      deliveryState: 'needs-review' } : previous?.proposedReminder,
    legacy: evidence(item)
  }
  model.interpretations.push(interpretation)
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
  const objects = model.legacyUiIds.map(id => {
    const reading = latest(model, id)
    const capture = model.captures.find(c => c.id === reading.captureIds[0]) ?? fail()
    const semantic = model.semanticObjects.find(o => o.id === id)
    return { ...copy(reading.legacy), originalContent: capture.originalContent, source: capture.source,
      createdAt: capture.createdAt, status: semantic?.status ??
        (reading.legacy.kind !== 'action' && reading.legacy.kind !== 'commitment' &&
          (reading.legacy.status === 'archived' || reading.legacy.status === 'complete') ? reading.legacy.status : 'review' as const) }
  })
  return { objects, canvas: copy(model.canvas), model: copy(model) }
}

/** Append evidence versions on UI changes; source edits and destructive removals fail closed. */
export function reconcileLegacyUi(state: AppState): PersistedState {
  if (!isAppState(state)) return fail()
  if (!state.model) return migrateLegacyState({ objects: state.objects, canvas: state.canvas })
  if (!isPersistedState(state.model)) return fail()
  const model = copy(state.model)
  if (!unique(state.objects.map(o => o.id)) || !unique(state.canvas.map(e => e.id)) ||
      model.legacyUiIds.some(id => !state.objects.some(o => o.id === id))) return fail()
  const projection = legacyUiProjection(model)
  for (const item of state.objects) {
    const old = projection.objects.find(o => o.id === item.id)
    if (old && equal(old, item)) continue
    if (old && !equal(item.history.slice(0, old.history.length), old.history)) return fail()
    append(model, item, old ? latest(model, item.id) : undefined)
  }
  model.legacyUiIds = state.objects.map(o => o.id)
  model.canvas = copy(state.canvas)
  if (!isPersistedState(model)) return fail()
  return model
}

/** Validate full entity data and cross-record invariants before exposing it to legacy screens. */
export function isPersistedState(value: unknown): value is PersistedState {
  try {
    if (!value || typeof value !== 'object') return false
    const m = value as PersistedState
    if (Object.keys(m).some(key => !['schemaVersion', 'captures', 'interpretations', 'semanticObjects', 'calendarEvents', 'relationships', 'legacyUiIds', 'canvas'].includes(key))) return false
    if (m.schemaVersion !== 2 || ![m.captures, m.interpretations, m.semanticObjects, m.calendarEvents,
      m.relationships, m.legacyUiIds, m.canvas].every(Array.isArray)) return false
    if (![m.captures, m.interpretations, m.semanticObjects, m.calendarEvents, m.relationships, m.canvas]
      .every(items => unique(items.map(i => i.id))) || !unique(m.legacyUiIds)) return false
    if (!m.captures.every(c => c.evidence === 'text-only' && typeof c.originalContent === 'string' &&
      typeof c.createdAt === 'string' && ['text', 'voice', 'canvas'].includes(c.source) &&
      (c.context === undefined || typeof c.context === 'string'))) return false
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
      append(rebuilt, item, previous)
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
    return isAppState(legacyUiProjection(m))
  } catch { return false }
}
