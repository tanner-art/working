import type { AppState, PersistedState, TemporalDecision, TemporalTarget } from './domain'

const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
export function validTemporalDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
}
function instant(value: string): boolean {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    validTemporalDate(value.slice(0, 10)) && Number(value.slice(11, 13)) < 24 && Number(value.slice(14, 16)) < 60 &&
    Number(value.slice(17, 19)) < 60 && Number.isFinite(Date.parse(value))
}
export function deadlineProposal(model: PersistedState, objectId: string): TemporalTarget | undefined {
  const reading = model.interpretations.filter(i => i.legacy.id === objectId).at(-1)
  const date = reading?.legacy.metadata.deadline ?? reading?.legacy.interpretation.suggestedDate
  if (!reading || !date || !validTemporalDate(date) || !model.semanticObjects.some(o => o.id === objectId)) return
  return { kind: 'fixed-deadline', objectId, interpretationId: reading.id, date }
}
export function eventProposal(model: PersistedState, eventId: string): TemporalTarget | undefined {
  const event = model.calendarEvents.find(e => e.id === eventId)
  // Existing events need actual captured interpretation provenance; do not invent it.
  const superseded = new Set(model.interpretations.map(i => i.previousId))
  const candidates = model.interpretations.filter(i => !superseded.has(i.id) && event?.captureIds.length && event.captureIds.every(id => i.captureIds.includes(id)))
  const reading = candidates.length === 1 ? candidates[0] : undefined
  if (!event || !reading || event.status !== 'scheduled' || !instant(event.startsAt)) return
  return { kind: 'event-scheduling', eventId, interpretationId: reading.id, startsAt: event.startsAt,
    temporalContext: event.temporalContext, title: event.title, objectIds: [...event.objectIds], captureIds: [...event.captureIds] }
}
function supportedTarget(model: PersistedState, target: TemporalTarget): boolean {
  const reading = model.interpretations.find(i => i.id === target.interpretationId)
  if (!reading) return false
  if (target.kind === 'fixed-deadline') {
    const date = reading.legacy.metadata.deadline ?? reading.legacy.interpretation.suggestedDate
    return equal(target, { kind: 'fixed-deadline', objectId: reading.legacy.id, interpretationId: reading.id, date }) &&
      typeof date === 'string' && validTemporalDate(date) && model.semanticObjects.some(o => o.id === target.objectId)
  }
  if (target.kind !== 'event-scheduling') return false
  const event = model.calendarEvents.find(e => e.id === target.eventId)
  return !!event && instant(target.startsAt) && target.captureIds.length > 0 &&
    target.captureIds.every(id => reading.captureIds.includes(id)) && equal(target, {
      kind: 'event-scheduling', eventId: event.id, interpretationId: reading.id, startsAt: event.startsAt,
      temporalContext: event.temporalContext, title: event.title, objectIds: event.objectIds, captureIds: event.captureIds
    })
}
const key = (target: TemporalTarget) => target.kind === 'fixed-deadline' ? `deadline:${target.objectId}` : `event:${target.eventId}`
/** Strict journal validation. Persisted evidence is auditable local data, not cryptographic proof of a click. */
export function validTemporalHistory(model: PersistedState): boolean {
  try {
    if (model.temporalHistory === undefined) return true
    if (!Array.isArray(model.temporalHistory)) return false
    const ids = new Set<string>()
    const active = new Map<string, TemporalDecision>()
    let last = -Infinity
    for (const entry of model.temporalHistory) {
      if (!entry || Object.keys(entry).some(k => !['id', 'at', 'source', 'decision', 'target', 'reverses'].includes(k)) ||
        typeof entry.id !== 'string' || !entry.id || ids.has(entry.id) || !instant(entry.at) || Date.parse(entry.at) < last ||
        entry.source !== 'review-temporal-confirmation' || !supportedTarget(model, entry.target)) return false
      const reading = model.interpretations.find(i => i.id === entry.target.interpretationId)!
      if (!Number.isFinite(Date.parse(reading.recordedAt)) || Date.parse(entry.at) < Date.parse(reading.recordedAt)) return false
      ids.add(entry.id); last = Date.parse(entry.at)
      const targetKey = key(entry.target)
      if (entry.decision === 'confirmed') {
        if (entry.reverses !== undefined || active.has(targetKey)) return false
        active.set(targetKey, entry)
      } else if (entry.decision === 'reversed') {
        const prior = active.get(targetKey)
        if (!prior || prior.id !== entry.reverses || !equal(prior.target, entry.target)) return false
        active.delete(targetKey)
      } else return false
    }
    return true
  } catch { return false }
}
export function activeTemporalDecisions(model: PersistedState): TemporalDecision[] {
  if (!validTemporalHistory(model)) return []
  const active = new Map<string, TemporalDecision>()
  for (const entry of model.temporalHistory ?? []) {
    if (entry.decision === 'reversed') active.delete(key(entry.target))
    else active.set(key(entry.target), entry)
  }
  return [...active.values()]
}
export function temporalFactIsCurrent(model: PersistedState, entry: TemporalDecision): boolean {
  const target = entry.target
  if (target.kind === 'event-scheduling') return model.calendarEvents.some(e => e.id === target.eventId && e.status === 'scheduled')
  const reading = model.interpretations.find(i => i.id === target.interpretationId)!
  return model.interpretations.filter(i => i.legacy.id === target.objectId && i.version >= reading.version).every(i =>
    (i.legacy.metadata.deadline ?? i.legacy.interpretation.suggestedDate) === target.date)
}
/** Dedicated Review handler. The caller supplies the reconciled current model, never a status dropdown. */
export function recordTemporalDecision(state: AppState, model: PersistedState, target: TemporalTarget, reverse?: TemporalDecision): AppState {
  if (!reverse && !equal(target, target.kind === 'fixed-deadline' ? deadlineProposal(model, target.objectId) : eventProposal(model, target.eventId))) throw new Error('Temporal proposal changed.')
  const entry: TemporalDecision = { id: crypto.randomUUID(), at: new Date().toISOString(), source: 'review-temporal-confirmation',
    decision: reverse ? 'reversed' : 'confirmed', target: structuredClone(target), ...(reverse ? { reverses: reverse.id } : {}) }
  const temporalHistory = [...(model.temporalHistory ?? []), entry]
  if (!validTemporalHistory({ ...model, temporalHistory })) throw new Error('Temporal proposal changed or confirmation is invalid.')
  return { ...state, temporalHistory }
}
