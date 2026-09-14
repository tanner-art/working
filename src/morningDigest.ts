import { isPersistedState } from './migration'
import { activeTemporalDecisions, temporalFactIsCurrent } from './temporalConfirmation'
import type { CalendarEvent, Interpretation, PersistedState, SemanticObject } from './domain'

export function localDateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

/** Validate the delivery schedule’s stored local day without converting it to an instant. */
export function validDateKey(value?: string): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(+parsed) && parsed.toISOString().slice(0, 10) === value
}

export interface MorningDigest {
  day: string
  fixedToday: { event: CalendarEvent; commitments: SemanticObject[] }[]
  upcoming: SemanticObject[]
  unscheduledCommitments: SemanticObject[]
  recommended: SemanticObject[]
  needsReview: Interpretation[]
  projectSignals: SemanticObject[]
}

/** Interpretation versions still reachable from the UI: every version except one superseded by a newer `previousId` link. */
export function currentInterpretations(model: PersistedState): Interpretation[] {
  const superseded = new Set(model.interpretations.map(i => i.previousId))
  return model.interpretations.filter(i => !superseded.has(i.id))
}

/** Confirmed, non-superseded semantic objects — the shared "real obligation/eligible work" base for the digest and the calendar (src/calendar.ts). */
export function confirmedSemanticObjects(model: PersistedState): SemanticObject[] {
  const current = currentInterpretations(model)
  return model.semanticObjects.filter(o => o.status === 'confirmed' &&
    (!['action', 'commitment'].includes(o.kind) || current.some(i => o.interpretationIds.includes(i.id) &&
      i.reviewState === 'accepted' && i.confirmation?.transition === o.kind)))
}

export function buildMorningDigest(model: PersistedState, now = new Date()): MorningDigest {
  const day = localDateKey(now)
  const current = currentInterpretations(model)
  const confirmed = confirmedSemanticObjects(model)
  const commitments = confirmed.filter(o => o.kind === 'commitment')
  const byId = (a: SemanticObject, b: SemanticObject) => a.id.localeCompare(b.id)
  // Temporal buckets require full canonical validation, including journal targets.
  const temporal = isPersistedState(model) ? activeTemporalDecisions(model).filter(e => temporalFactIsCurrent(model, e)) : []
  const events = model.calendarEvents.filter(e => e.status === 'scheduled' && temporal.some(t => t.target.kind === 'event-scheduling' && t.target.eventId === e.id))
  const deadlines = confirmed.flatMap(o => {
    const evidence = temporal.find(t => t.target.kind === 'fixed-deadline' && t.target.objectId === o.id)
    return evidence?.target.kind === 'fixed-deadline' ? [{ ...o, metadata: { ...o.metadata, deadline: evidence.target.date } }] : []
  })
  return {
    day,
    fixedToday: events.filter(e => localDateKey(new Date(e.startsAt)) === day)
      .sort((a, b) => Date.parse(a.startsAt) - Date.parse(b.startsAt) || a.id.localeCompare(b.id)).slice(0, 3)
      .map(event => ({ event, commitments: commitments.filter(o => event.objectIds.includes(o.id)) })),
    upcoming: deadlines.sort((a, b) => a.metadata.deadline!.localeCompare(b.metadata.deadline!) || byId(a, b)).slice(0, 3),
    unscheduledCommitments: commitments.filter(o => !events.some(e => e.objectIds.includes(o.id))).sort(byId).slice(0, 3),
    // Deterministic selection, not an Adaptive Plan or a new composite priority score.
    recommended: confirmed.filter(o => o.kind === 'action' && !model.relationships.some(r =>
      r.scope === 'semantic' && r.sourceId === o.id && r.type === 'depends_on' &&
      model.semanticObjects.find(target => target.id === r.targetId)?.status !== 'complete'))
      .sort((a, b) => (b.metadata.strategicImportance ?? 0) - (a.metadata.strategicImportance ?? 0) || byId(a, b)).slice(0, 3),
    needsReview: current.filter(i => i.reviewState === 'review' || i.proposedReminder?.deliveryState === 'needs-review')
      .sort((a, b) => a.recordedAt.localeCompare(b.recordedAt) || a.id.localeCompare(b.id)).slice(0, 5),
    projectSignals: confirmed.filter(o => o.kind === 'project' || o.kind === 'objective').sort(byId).slice(0, 3)
  }
}
