import { directCalendarEventsFromHistory, validTemporalHistory } from './temporalConfirmation'
import { isGroupingReviewState } from './groupingProposal'
import type { ActionPriority, AppState, CommitmentScheduleAudit, ConfirmationGesture, HistoryEvent, Interpretation, PersistedState, ResolvedReminderInstruction, SemanticObject, StagedAction, ThoughtObject } from './domain'
import { isCanvasViewport } from './canvasDocument'
import { bankFromLegacy, isCanvasBank } from './canvasBank'
import { isAppState } from './store'

// Compatibility authority stays inside migration. Validation uses detached copies;
// only validated projections expose registered history entries to callers.
const persistedConfirmations = new WeakMap<HistoryEvent, ConfirmationGesture>()

export function hasConfirmation(object: ThoughtObject): boolean {
  for (const entry of object.history.slice().reverse()) {
    // A revision invalidates earlier summary-specific confirmations; the old event stays for audit.
    if (entry.reviewRevision || entry.reviewDecision || entry.event.startsWith('Changed type') || entry.event === 'Marked review' || entry.event === 'Marked inbox' || entry.event.includes('status to review') || entry.event.includes('status to inbox') || entry.event.startsWith('Edited type')) return false
    const confirmation = entry.confirmation ?? persistedConfirmations.get(entry)
    if (confirmation) return confirmation.objectId === object.id &&
      confirmation.transition === object.kind && confirmation.summary === object.interpretation.summary &&
      confirmation.source === 'review-confirmation' && Number.isFinite(Date.parse(entry.at))
  }
  return false
}

/** Rebuild reminder instructions from append-only source-capture audit events. */
function materializeReminderInstructions(model: PersistedState) {
  const records = new Map<string, ResolvedReminderInstruction>()
  const latestReadings = new Map<string, Interpretation>()
  for (const reading of model.interpretations) latestReadings.set(reading.legacy.id, reading)
  for (const reading of latestReadings.values()) {
    for (const entry of reading.legacy.history) {
      const audit = entry.reminderInstruction
      if (!audit) continue
      const existing = records.get(audit.instructionId)
      if (audit.action === 'created') {
        if (existing || reading.legacy.kind !== 'reminder' || !audit.targetId || !audit.mode || !Number.isFinite(Date.parse(entry.at)) ||
          (audit.mode === 'specific' && (!audit.dueAt || !Number.isFinite(Date.parse(audit.dueAt)))) ||
          (audit.mode === 'daily-log' && audit.dueAt !== undefined)) fail()
        const targetId = audit.targetId!
        const mode = audit.mode!
        const sourceInterpretationId = model.interpretations.find(candidate => candidate.legacy.id === reading.legacy.id &&
          candidate.legacy.history.some(candidateEntry => candidateEntry.reminderInstruction?.instructionId === audit.instructionId && candidateEntry.reminderInstruction.action === 'created'))?.id ?? fail()
        records.set(audit.instructionId, { id: audit.instructionId, targetId, captureIds: reading.captureIds,
          sourceInterpretationId, mode, ...(mode === 'specific' ? { dueAt: audit.dueAt! } : {}),
          deliveryState: 'active', createdAt: entry.at })
        continue
      }
      const active = existing ?? fail()
      if (active.deliveryState !== 'active' || !Number.isFinite(Date.parse(entry.at))) fail()
      records.set(audit.instructionId, audit.action === 'handled'
        ? { ...active, deliveryState: 'handled', handledAt: entry.at }
        : { ...active, deliveryState: 'dismissed', dismissedAt: entry.at })
    }
  }
  const instructions = [...records.values()]
  if (instructions.some(instruction => !model.semanticObjects.some(target => target.id === instruction.targetId))) fail()
  if (instructions.length || model.reminderInstructions !== undefined) model.reminderInstructions = instructions
  for (const target of model.semanticObjects) {
    const legacy = target.reminders.filter(reminder => !('targetId' in reminder))
    target.reminders = [...legacy, ...instructions.filter(instruction => instruction.targetId === target.id).map(copy)]
  }
}

const copy = <T>(value: T): T => structuredClone(value)
const equal = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b)
const unique = (ids: string[]) => ids.every(id => id.length > 0) && new Set(ids).size === ids.length
const fail = (): never => { throw new Error('Saved model is invalid or ambiguous; stored data must remain untouched.') }
const actionPriorities: ActionPriority[] = [1, 2, 3, 4, 5]

/** Action-only history is meaningful only while the current interpretation is an Action. */
function stagedAction(item: ThoughtObject, captureId: string): StagedAction | undefined {
  if (item.kind !== 'action') return undefined
  const stages = item.history.map((entry, index) => ({ entry, index })).filter(value => value.entry.actionStage !== undefined)
  if (stages.length > 1 || stages.some(value => value.entry.actionStage?.source !== 'review-action-staging')) fail()
  const stageIndex = stages[0]?.index ?? -1
  if (stageIndex < 0) return undefined
  const stage = item.history[stageIndex]
  const initial = stage.actionStage?.priority
  if (!initial || !actionPriorities.includes(initial) || !Number.isFinite(Date.parse(stage.at))) fail()
  const initialPriority = initial as ActionPriority
  if (item.history.slice(0, stageIndex).some(entry => entry.actionPriority || entry.actionSchedule)) fail()
  const later = item.history.slice(stageIndex + 1)
  const priorities = later.filter(entry => entry.actionPriority !== undefined)
  if (priorities.some(entry => entry.actionPriority?.source !== 'schedule-priority-selection' || !actionPriorities.includes(entry.actionPriority.priority))) fail()
  const schedules = later.filter(entry => entry.actionSchedule !== undefined)
  if (schedules.length > 1) fail()
  const schedule = schedules[0]?.actionSchedule
  if (schedule && (!schedule.eventId || !Number.isFinite(Date.parse(schedule.startsAt)) || !schedule.temporalContext.trim())) fail()
  const reversed = later.some(entry => entry.reviewDecision === 'reversed' || entry.reviewDecision === 'rejected' || entry.reviewDecision === 'superseded')
  const selectedPriority = priorities.at(-1)?.actionPriority?.priority
  if (!selectedPriority) return { id: `staged-action:${item.id}`, objectId: item.id, captureId, priority: initialPriority,
    status: reversed ? 'reversed' : schedule ? 'scheduled' : 'staged', stagedAt: stage.at, ...(schedule ? { schedule: copy(schedule) } : {}) }
  return { id: `staged-action:${item.id}`, objectId: item.id, captureId, priority: selectedPriority,
    status: reversed ? 'reversed' : schedule ? 'scheduled' : 'staged', stagedAt: stage.at, ...(schedule ? { schedule: copy(schedule) } : {}) }
}

/** Commitment time is only a proposal until this separate scheduling audit exists. */
function commitmentSchedule(item: ThoughtObject): CommitmentScheduleAudit | undefined {
  if (item.kind !== 'commitment') return undefined
  const schedules = item.history.filter(entry => entry.commitmentSchedule !== undefined)
  if (schedules.length > 1) fail()
  const schedule = schedules[0]?.commitmentSchedule
  if (!schedule) return undefined
  if (!schedule.eventId || !Number.isFinite(Date.parse(schedule.startsAt)) || !schedule.temporalContext.trim() || schedule.source !== 'commitment-calendar-scheduling') fail()
  return schedule
}

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
  const actionStage = stagedAction(item, `capture:${item.id}`)
  const commitmentEvent = commitmentSchedule(item)
  // Text alone never authorizes a gesture. Compatibility requires a structured
  // confirmation from schema-v2 validation or an already validated save baseline.
  const additions = previous ? item.history.slice(previous.legacy.history.length) : []
  const gesture = additions.slice().reverse().find(h => h.event === `Confirmed as ${item.kind}` && Number.isFinite(Date.parse(h.at)) &&
    (h.confirmation ? h.confirmation.objectId === item.id && h.confirmation.transition === item.kind &&
      h.confirmation.summary === item.interpretation.summary && h.confirmation.source === 'review-confirmation' : persistedConfirmation?.transition === item.kind && persistedConfirmation.at === h.at))
  const compatibleItem = copy(item)
  if (persistedConfirmation) registerCompatibility(compatibleItem, persistedConfirmation)
  // A freshly resolved Commitment carries its setup audit immediately before
  // the dedicated confirmation. That same-save pair is explicit evidence even
  // before a compatibility projection has registered it.
  const activeGesture = hasConfirmation(item) || hasConfirmation(compatibleItem) || (item.kind === 'commitment' && !!gesture)
  const confirmation = consequential && activeGesture && ['confirmed', 'complete', 'archived'].includes(item.status)
    ? gesture ? { at: gesture.at, transition: item.kind as 'action' | 'commitment',
      ...(gesture.confirmation ? { objectId: item.id, interpretationId: `interpretation:${item.id}:${version}`,
        historyIndex: item.history.indexOf(gesture), source: 'review-confirmation' as const } : {}) }
      : previous?.confirmation?.transition === item.kind ? previous.confirmation : undefined
    : undefined
  const decision = item.history.slice().reverse().find(h => h.reviewDecision || h.confirmation)
  const rejected = decision?.reviewDecision === 'rejected'
  const awaitingReview = previous && previous.reviewState !== 'accepted'
  const accepted = !rejected && item.kind !== 'reminder' && (!consequential || !!confirmation || !!actionStage) &&
    (!awaitingReview || !!gesture || !!actionStage) && !['review', 'inbox'].includes(item.status)
  const interpretation: Interpretation = {
    id: `interpretation:${item.id}:${version}`, version, previousId: previous?.id,
    captureIds: [`capture:${item.id}`], recordedAt: item.history.at(-1)?.at ?? item.createdAt,
    summary: item.interpretation.summary, rationale: item.interpretation.rationale, confidence: item.confidence,
    method: item.interpretation.method,
    proposedKind: item.kind === 'reminder' ? 'unresolved' : item.kind,
    proposedAction: item.kind === 'action' && !confirmation && !actionStage ? { summary: item.interpretation.summary } : undefined,
    reviewState: rejected ? 'rejected' : accepted ? 'accepted' : 'review', confirmation,
    proposedReminder: item.kind === 'reminder' ? { id: `reminder:${item.id}`, captureIds: [`capture:${item.id}`],
      trigger: { kind: 'unresolved', wording: item.originalContent, legacyDate: item.interpretation.suggestedDate ?? item.metadata.deadline },
      deliveryState: 'needs-review' } : previous?.proposedReminder,
    legacy: evidence(item)
  }
  model.interpretations.push(interpretation)
  const withdrawn = model.semanticObjects.find(o => o.id === item.id)
  model.semanticObjects = model.semanticObjects.filter(o => o.id !== item.id)
  const priorStages = (model.stagedActions ?? []).filter(stage => stage.objectId === item.id)
  const priorEventIds = new Set(priorStages.flatMap(stage => stage.schedule?.eventId ?? []))
  const historicalSchedules = item.history.flatMap(entry => entry.actionSchedule ? [entry.actionSchedule] : [])
  const historicalEventIds = new Set(historicalSchedules.map(schedule => schedule.eventId))
  model.stagedActions = (model.stagedActions ?? []).filter(stage => stage.objectId !== item.id)
  if (!actionStage || actionStage.status === 'reversed') {
    const cancelledIds = new Set([...priorEventIds, ...historicalEventIds])
    model.calendarEvents = model.calendarEvents.map(event => cancelledIds.has(event.id) ? { ...event, status: 'cancelled' as const } : event)
    for (const schedule of historicalSchedules) if (!model.calendarEvents.some(event => event.id === schedule.eventId)) {
      model.calendarEvents.push({ id: schedule.eventId, title: interpretation.summary, startsAt: schedule.startsAt, temporalContext: schedule.temporalContext,
        objectIds: [item.id], captureIds: interpretation.captureIds, status: 'cancelled' })
    }
    // A later object reversal invalidates only its own confirmed temporal fact;
    // retain the temporal audit as an explicit reversal rather than a dangling event.
    for (const eventId of cancelledIds) {
      const active = [...(model.temporalHistory ?? [])].reverse().find(entry => entry.target.kind === 'event-scheduling' && entry.target.eventId === eventId && entry.decision === 'confirmed')
      const alreadyReversed = active && (model.temporalHistory ?? []).some(entry => entry.decision === 'reversed' && entry.reverses === active.id)
      if (active && !alreadyReversed) model.temporalHistory = [...(model.temporalHistory ?? []), { id: `action-reversal:${eventId}`, at: item.history.at(-1)?.at ?? new Date().toISOString(), source: 'review-temporal-confirmation', decision: 'reversed', target: copy(active.target), reverses: active.id }]
    }
  }
  if (actionStage) {
    model.stagedActions.push(actionStage)
    if (actionStage.status !== 'reversed' && actionStage.schedule && !model.calendarEvents.some(event => event.id === actionStage.schedule!.eventId)) {
      model.calendarEvents.push({ id: actionStage.schedule.eventId, title: interpretation.summary, startsAt: actionStage.schedule.startsAt,
        temporalContext: actionStage.schedule.temporalContext, objectIds: [item.id], captureIds: interpretation.captureIds, status: 'scheduled' })
    }
  }
  if (commitmentEvent && !model.calendarEvents.some(event => event.id === commitmentEvent.eventId)) {
    model.calendarEvents.push({ id: commitmentEvent.eventId, title: interpretation.summary, startsAt: commitmentEvent.startsAt,
      temporalContext: commitmentEvent.temporalContext, objectIds: [item.id], captureIds: interpretation.captureIds, status: 'scheduled' })
  }
  // Unresolved reminders and unconfirmed consequential meaning remain interpretations.
  if (item.kind !== 'reminder' && (!consequential || confirmation || (actionStage && actionStage.status !== 'reversed'))) {
    const metadata = copy(item.metadata)
    // Legacy timing is evidence, never a confirmed fixed deadline or event.
    delete metadata.deadline
    const object: SemanticObject = { id: item.id, kind: item.kind, captureIds: interpretation.captureIds,
      interpretationIds: model.interpretations.filter(i => i.legacy.id === item.id).map(i => i.id),
      summary: interpretation.summary, status: actionStage ? 'confirmed' : accepted ? item.status : 'review', metadata,
      reminders: interpretation.proposedReminder ? [copy(interpretation.proposedReminder)] : [] }
    model.semanticObjects.push(object)
  }
  if (((withdrawn && item.kind !== 'reminder') || (historicalSchedules.length && item.kind !== 'reminder')) && !model.semanticObjects.some(o => o.id === item.id)) {
    model.semanticObjects.push(withdrawn ? { ...withdrawn, status: 'review' } : { id: item.id, kind: item.kind as SemanticObject['kind'], captureIds: interpretation.captureIds,
      interpretationIds: model.interpretations.filter(i => i.legacy.id === item.id).map(i => i.id), summary: interpretation.summary,
      status: 'review', metadata: copy(item.metadata), reminders: [] })
  }
  model.relationships = model.relationships.filter(r => r.sourceId !== item.id)
  item.relationships.forEach((r, index) => model.relationships.push({ ...copy(r), id: `relationship:${item.id}:${index}`,
    sourceId: item.id, scope: 'semantic', provenance: { interpretationId: interpretation.id, evidence: 'legacy-unverified' } }))
}

/** Pure conversion: never writes storage, guesses reminder targets, or schedules events. */
export function migrateLegacyState(value: unknown): PersistedState {
  if (!isAppState(value) || Object.keys(value).some(key => !['objects', 'canvas'].includes(key)) || 'schemaVersion' in value || value.model !== undefined ||
      !unique(value.objects.map(o => o.id)) || !unique(value.canvas.map(e => e.id))) return fail()
  const model: PersistedState = { schemaVersion: 2, captures: [], interpretations: [], semanticObjects: [], stagedActions: [],
    calendarEvents: [], relationships: [], legacyUiIds: value.objects.map(o => o.id), canvas: copy(value.canvas) }
  value.objects.forEach(item => append(model, item))
  materializeReminderInstructions(model)
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
    const resolvedReminder = (model.reminderInstructions ?? []).find(instruction => instruction.captureIds.includes(capture.id)) ??
      reading.legacy.history.find(entry => entry.reminderInstruction?.action === 'created')
    const item: ThoughtObject = { ...copy(reading.legacy), originalContent: capture.originalContent,
      ...(correction ? { currentContent: correction.correctedContent } : {}), source: capture.source,
      createdAt: capture.createdAt, status: semantic?.status ??
        (resolvedReminder ? reading.legacy.status : reading.legacy.kind !== 'action' && reading.legacy.kind !== 'commitment' &&
          (reading.legacy.status === 'archived' || reading.legacy.status === 'complete') ? reading.legacy.status : 'review' as const) }
    if (reading.confirmation) registerCompatibility(item, reading.confirmation)
    return item
  })
  return { objects, canvas: copy(model.canvas), ...(model.canvasViewport === undefined ? {} : { canvasViewport: copy(model.canvasViewport) }),
    canvasBank: copy(model.canvasBank ?? bankFromLegacy(model.canvas, model.canvasViewport)), model: copy(model) }
}

/** Append evidence versions on UI changes; source edits and destructive removals fail closed. */
export function reconcileLegacyUi(state: AppState): PersistedState {
  if (!isAppState(state)) return fail()
  if (!state.model) {
    const model = migrateLegacyState({ objects: state.objects, canvas: state.canvas })
    if (state.canvasViewport !== undefined) model.canvasViewport = copy(state.canvasViewport)
    model.canvasBank = copy(state.canvasBank ?? bankFromLegacy(state.canvas, state.canvasViewport))
    return model
  }
  if (!isPersistedState(state.model)) return fail()
  const model = copy(state.model)
  if (!unique(state.objects.map(o => o.id)) || !unique(state.canvas.map(e => e.id)) ||
      model.legacyUiIds.some(id => !state.objects.some(o => o.id === id))) return fail()
  const projection = legacyUiProjection(model)
  // Once the Bank exists, the top-level canvas is a frozen one-release recovery mirror.
  // Opening or editing a Bank document must never mutate it.
  if (!equal(state.canvas, projection.canvas) || !equal(state.canvasViewport, projection.canvasViewport)) return fail()
  const baselineBank = model.canvasBank ?? bankFromLegacy(model.canvas, model.canvasViewport)
  const nextBank = state.canvasBank ?? baselineBank
  if (baselineBank.canvases.some(saved => !nextBank.canvases.some(current => current.id === saved.id))) return fail()
  for (const item of state.objects) {
    const old = projection.objects.find(o => o.id === item.id)
    if (old && equal(old, item)) continue
    if (old && (!equal(item.history.slice(0, old.history.length), old.history) || item.confidence !== old.confidence)) return fail()
    if (old) {
      // Only the summary may change, and only through recorded revisions; other interpretation fields are frozen.
      const { summary: _next, ...nextRest } = item.interpretation
      const { summary: _prior, ...priorRest } = old.interpretation
      if (!equal(nextRest, priorRest)) return fail()
    }
    if (old && item.interpretation.summary !== old.interpretation.summary) {
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
  model.canvasBank = copy(nextBank)
  if (state.temporalHistory !== undefined) {
    const previousHistory = model.temporalHistory ?? []
    if (equal(state.temporalHistory.slice(0, previousHistory.length), previousHistory)) model.temporalHistory = copy(state.temporalHistory)
    // Reconciliation may have appended the deterministic reversal of a cancelled
    // Action-derived event. Keep that audit entry rather than restoring its stale
    // active confirmation from the caller's pre-reconciliation snapshot.
    else if (!(state.temporalHistory.length > 0 && equal(state.temporalHistory, previousHistory.slice(0, state.temporalHistory.length)))) return fail()
    const actionEventIds = new Set(model.interpretations.flatMap(reading => reading.legacy.history.flatMap(entry => entry.actionSchedule ? [entry.actionSchedule.eventId] : [])))
    for (const event of model.calendarEvents) {
      if (event.status !== 'cancelled' || !actionEventIds.has(event.id)) continue
      const confirmed = [...(model.temporalHistory ?? [])].reverse().find(entry => entry.decision === 'confirmed' && entry.target.kind === 'event-scheduling' && entry.target.eventId === event.id)
      if (!confirmed || (model.temporalHistory ?? []).some(entry => entry.decision === 'reversed' && entry.reverses === confirmed.id)) continue
      const reversalAt = model.interpretations.at(-1)?.legacy.history.at(-1)?.at ?? new Date().toISOString()
      model.temporalHistory = [...(model.temporalHistory ?? []), { id: `action-reversal:${event.id}`, at: reversalAt, source: 'review-temporal-confirmation', decision: 'reversed', target: copy(confirmed.target), reverses: confirmed.id }]
    }
  }
  const directEvents = directCalendarEventsFromHistory(model.temporalHistory ?? [])
  const otherEvents = model.calendarEvents.filter(event => event.origin !== 'calendar-direct-entry')
  if (directEvents.some(event => otherEvents.some(other => other.id === event.id))) return fail()
  model.calendarEvents = [...otherEvents, ...directEvents]
  materializeReminderInstructions(model)
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

/** Each correction needs a matching, ordered `sourceCorrection` audit event in its capture's latest
 * interpretation history (append-only across versions), and no event may exist without its correction. */
function validCorrectionAudit(m: PersistedState): boolean {
  const corrections = m.sourceCorrections ?? []
  for (const capture of m.captures) {
    const reading = m.interpretations.filter(i => i.captureIds?.[0] === capture.id).at(-1)
    const events = (reading?.legacy.history ?? []).filter(h => h.sourceCorrection)
    const chain = corrections.filter(c => c.captureId === capture.id)
    if (events.length !== chain.length) return false
    let text = capture.originalContent
    for (const [index, correction] of chain.entries()) {
      const event = events[index]
      const audit = event.sourceCorrection!
      if (audit.correctionId !== correction.id || event.at !== correction.correctedAt ||
        audit.from !== text || audit.to !== correction.correctedContent) return false
      text = correction.correctedContent
    }
  }
  return true
}

/** Validate full entity data and cross-record invariants before exposing it to legacy screens. */
export function isPersistedState(value: unknown): value is PersistedState {
  try {
    if (!value || typeof value !== 'object') return false
    const m = value as PersistedState
    if (Object.keys(m).some(key => !['schemaVersion', 'captures', 'sourceCorrections', 'interpretations', 'semanticObjects', 'reminderInstructions', 'stagedActions', 'calendarEvents', 'relationships', 'legacyUiIds', 'canvas', 'canvasViewport', 'canvasBank', 'temporalHistory', 'groupingReview'].includes(key))) return false
    if (m.canvasViewport !== undefined && !isCanvasViewport(m.canvasViewport)) return false
    if (m.canvasBank !== undefined && !isCanvasBank(m.canvasBank)) return false
    if (m.schemaVersion !== 2 || ![m.captures, m.interpretations, m.semanticObjects, m.calendarEvents,
      m.relationships, m.legacyUiIds, m.canvas].every(Array.isArray) || (m.stagedActions !== undefined && !Array.isArray(m.stagedActions))) return false
    if (![m.captures, m.interpretations, m.semanticObjects, m.calendarEvents, m.relationships, m.canvas]
      .every(items => unique(items.map(i => i.id))) || !unique(m.legacyUiIds)) return false
    if (!m.captures.every(c => c.evidence === 'text-only' && typeof c.originalContent === 'string' &&
      typeof c.createdAt === 'string' && ['text', 'voice', 'canvas'].includes(c.source) &&
      (c.context === undefined || typeof c.context === 'string'))) return false
    if (m.sourceCorrections !== undefined && !validSourceCorrections(m)) return false
    if (!validCorrectionAudit(m)) return false
    // Reconstruct supported adapter versions to verify semantic derivations and history links.
    const rebuilt: PersistedState = { schemaVersion: 2, captures: copy(m.captures), interpretations: [],
      semanticObjects: [], ...(m.reminderInstructions === undefined ? {} : { reminderInstructions: [] }), ...(m.stagedActions === undefined ? {} : { stagedActions: [] }), calendarEvents: [], relationships: [], legacyUiIds: copy(m.legacyUiIds), canvas: copy(m.canvas) }
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
    materializeReminderInstructions(rebuilt)
    if (!equal(rebuilt.semanticObjects, m.semanticObjects) || !equal(rebuilt.reminderInstructions ?? [], m.reminderInstructions ?? []) || !equal(rebuilt.relationships, m.relationships) || !equal(rebuilt.stagedActions ?? [], m.stagedActions ?? [])) return false
    const latestReadings = m.legacyUiIds.map(id => m.interpretations.filter(reading => reading.legacy.id === id).at(-1)!).filter(Boolean)
    const activeActionSchedules = new Map((m.stagedActions ?? []).filter(stage => stage.status === 'scheduled' && stage.schedule).map(stage => [stage.schedule!.eventId, stage]))
    for (const reading of latestReadings) {
      for (const entry of reading.legacy.history) if (entry.actionSchedule && !activeActionSchedules.has(entry.actionSchedule.eventId) &&
        m.calendarEvents.some(event => event.id === entry.actionSchedule!.eventId && event.status === 'scheduled')) return false
    }
    for (const [eventId, stage] of activeActionSchedules) {
      const event = m.calendarEvents.find(value => value.id === eventId)
      if (!event || event.status !== 'scheduled' || event.objectIds.length !== 1 || event.objectIds[0] !== stage.objectId || event.startsAt !== stage.schedule!.startsAt || event.temporalContext !== stage.schedule!.temporalContext) return false
    }
    if (m.captures.length !== new Set(m.interpretations.flatMap(i => i.captureIds)).size ||
        m.legacyUiIds.length !== new Set(m.interpretations.map(i => i.legacy.id)).size) return false
    // Events have their own scheduling identity; the legacy UI neither authors nor projects them.
    if (!m.calendarEvents.every(e => typeof e.title === 'string' && typeof e.startsAt === 'string' &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(e.startsAt) && Number.isFinite(Date.parse(e.startsAt)) && typeof e.temporalContext === 'string' && e.temporalContext.length > 0 &&
      ['scheduled', 'cancelled'].includes(e.status) && (e.origin === undefined || e.origin === 'calendar-direct-entry') && Array.isArray(e.objectIds) &&
      e.objectIds.every(id => m.semanticObjects.some(o => o.id === id)) && Array.isArray(e.captureIds) &&
      e.captureIds.every(id => m.captures.some(c => c.id === id)))) return false
    return validTemporalHistory(m) && (m.groupingReview === undefined || isGroupingReviewState(m.groupingReview, m.captures)) && isAppState(projectModel(m))
  } catch { return false }
}
