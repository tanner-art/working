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

export function buildMorningDigest(model: PersistedState, now = new Date()): MorningDigest {
  const day = localDateKey(now)
  const superseded = new Set(model.interpretations.map(i => i.previousId))
  const current = model.interpretations.filter(i => !superseded.has(i.id))
  const confirmed = model.semanticObjects.filter(o => o.status === 'confirmed' &&
    (!['action', 'commitment'].includes(o.kind) || current.some(i => o.interpretationIds.includes(i.id) &&
      i.reviewState === 'accepted' && i.confirmation?.transition === o.kind)))
  const commitments = confirmed.filter(o => o.kind === 'commitment')
  const byId = (a: SemanticObject, b: SemanticObject) => a.id.localeCompare(b.id)
  return {
    day,
    // D-009 requires separate timestamped scheduling/deadline confirmation.
    // The current schema cannot record it. Status strings and date metadata are
    // not evidence; keep these buckets blocked until that provenance exists.
    fixedToday: [],
    upcoming: [],
    // No schedule can currently be verified. Unverified timing must not hide
    // a confirmed obligation or be presented as its fixed deadline.
    unscheduledCommitments: commitments.sort(byId).slice(0, 3),
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
