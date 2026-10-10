import type { AppState, CalendarEvent, PersistedState, TemporalDecision, TemporalTarget } from './domain'

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
  if (event?.origin === 'calendar-direct-entry') return
  // Existing events need actual captured interpretation provenance; do not invent it.
  const superseded = new Set(model.interpretations.map(i => i.previousId))
  const candidates = model.interpretations.filter(i => !superseded.has(i.id) && event?.captureIds.length && event.captureIds.every(id => i.captureIds.includes(id)))
  const reading = candidates.length === 1 ? candidates[0] : undefined
  if (!event || !reading || event.status !== 'scheduled' || !instant(event.startsAt)) return
  return { kind: 'event-scheduling', eventId, interpretationId: reading.id, startsAt: event.startsAt,
    temporalContext: event.temporalContext, title: event.title, objectIds: [...event.objectIds], captureIds: [...event.captureIds] }
}
function supportedTarget(model: PersistedState, target: TemporalTarget): boolean {
  if (target.kind === 'direct-calendar-event') {
    const event = model.calendarEvents.find(e => e.id === target.eventId)
    return !!event && event.origin === 'calendar-direct-entry' && event.objectIds.length === 0 && event.captureIds.length === 0 &&
      typeof target.title === 'string' && !!target.title.trim() && typeof target.temporalContext === 'string' && !!target.temporalContext.trim() &&
      instant(target.startsAt) && Object.keys(target).length === 5 && target.eventId === event.id &&
      target.startsAt === event.startsAt && target.temporalContext === event.temporalContext && target.title === event.title
  }
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
/** The direct-entry decision is the append-only source for an unlinked event. */
export function directCalendarEventsFromHistory(history: readonly TemporalDecision[]): CalendarEvent[] {
  const events = new Map<string, CalendarEvent>()
  for (const entry of history) {
    const target = entry.target
    if (target.kind !== 'direct-calendar-event') continue
    if (entry.decision === 'confirmed') {
      if (events.has(target.eventId)) throw new Error('A direct CalendarEvent may be created only once.')
      events.set(target.eventId, { id: target.eventId, title: target.title, startsAt: target.startsAt,
        temporalContext: target.temporalContext, objectIds: [], captureIds: [], status: 'scheduled', origin: 'calendar-direct-entry' })
    } else {
      const prior = events.get(target.eventId)
      if (!prior || prior.status !== 'scheduled') throw new Error('A direct CalendarEvent cannot be reversed twice.')
      events.set(target.eventId, { ...prior, status: 'cancelled' })
    }
  }
  return [...events.values()]
}
/** Strict journal validation. Persisted evidence is auditable local data, not cryptographic proof of a click. */
export function validTemporalHistory(model: PersistedState): boolean {
  try {
    if (model.temporalHistory === undefined) return !model.calendarEvents.some(event => event.origin === 'calendar-direct-entry')
    if (!Array.isArray(model.temporalHistory)) return false
    const ids = new Set<string>()
    const active = new Map<string, TemporalDecision>()
    let last = -Infinity
    for (const entry of model.temporalHistory) {
      if (!entry || Object.keys(entry).some(k => !['id', 'at', 'source', 'decision', 'target', 'reverses'].includes(k)) ||
        typeof entry.id !== 'string' || !entry.id || ids.has(entry.id) || !instant(entry.at) || Date.parse(entry.at) < last ||
        entry.source !== (entry.target.kind === 'direct-calendar-event' ? 'calendar-direct-confirmation' : 'review-temporal-confirmation') ||
        !supportedTarget(model, entry.target)) return false
      if (entry.target.kind !== 'direct-calendar-event') {
        const interpretationId = entry.target.interpretationId
        const reading = model.interpretations.find(i => i.id === interpretationId)!
        if (!Number.isFinite(Date.parse(reading.recordedAt)) || Date.parse(entry.at) < Date.parse(reading.recordedAt)) return false
      }
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
    const direct = directCalendarEventsFromHistory(model.temporalHistory)
    const stored = model.calendarEvents.filter(event => event.origin === 'calendar-direct-entry')
    return direct.length === stored.length && direct.every(expected => {
      const event = stored.find(candidate => candidate.id === expected.id)
      return !!event && Object.keys(event).length === 8 && event.title === expected.title &&
        event.startsAt === expected.startsAt && event.temporalContext === expected.temporalContext &&
        event.status === expected.status && event.objectIds.length === 0 && event.captureIds.length === 0
    })
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
  if (target.kind === 'event-scheduling' || target.kind === 'direct-calendar-event') return model.calendarEvents.some(e => e.id === target.eventId && e.status === 'scheduled')
  const reading = model.interpretations.find(i => i.id === target.interpretationId)!
  return model.interpretations.filter(i => i.legacy.id === target.objectId && i.version >= reading.version).every(i =>
    (i.legacy.metadata.deadline ?? i.legacy.interpretation.suggestedDate) === target.date)
}
/** Dedicated Review handler. The caller supplies the reconciled current model, never a status dropdown. */
export function recordTemporalDecision(state: AppState, model: PersistedState, target: TemporalTarget, reverse?: TemporalDecision): AppState {
  if (!reverse && (target.kind === 'direct-calendar-event' || !equal(target, target.kind === 'fixed-deadline' ? deadlineProposal(model, target.objectId) : eventProposal(model, target.eventId)))) throw new Error('Temporal proposal changed.')
  const entry: TemporalDecision = { id: crypto.randomUUID(), at: new Date().toISOString(), source: target.kind === 'direct-calendar-event' ? 'calendar-direct-confirmation' : 'review-temporal-confirmation',
    decision: reverse ? 'reversed' : 'confirmed', target: structuredClone(target), ...(reverse ? { reverses: reverse.id } : {}) }
  const temporalHistory = [...(model.temporalHistory ?? []), entry]
  const calendarEvents = target.kind === 'direct-calendar-event' && reverse
    ? model.calendarEvents.map(event => event.id === target.eventId ? { ...event, status: 'cancelled' as const } : event)
    : model.calendarEvents
  if (!validTemporalHistory({ ...model, calendarEvents, temporalHistory })) throw new Error('Temporal proposal changed or confirmation is invalid.')
  return { ...state, temporalHistory }
}
