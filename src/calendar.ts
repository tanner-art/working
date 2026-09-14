import type { CalendarEvent, ObjectKind, PersistedState, SemanticObject } from './domain'
import { confirmedSemanticObjects, currentInterpretations, localDateKey, validDateKey } from './morningDigest'

export const WEEKDAY_LABELS = [
  { short: 'Sun', long: 'Sunday' }, { short: 'Mon', long: 'Monday' }, { short: 'Tue', long: 'Tuesday' },
  { short: 'Wed', long: 'Wednesday' }, { short: 'Thu', long: 'Thursday' }, { short: 'Fri', long: 'Friday' },
  { short: 'Sat', long: 'Saturday' }
] as const

export interface CalendarDayEvent { event: CalendarEvent; linkedObjects: SemanticObject[] }
/** A date the user or AI associated with an object, never a scheduled time. D-005/D-009: only a CalendarEvent is a confirmed schedule. */
export interface ProposedDateMarker { interpretationId: string; objectId: string; kind: ObjectKind; summary: string; date: string }
export interface CalendarDayCell {
  date: string
  inCurrentMonth: boolean
  isToday: boolean
  events: CalendarDayEvent[]
  proposedDates: ProposedDateMarker[]
}
export interface CalendarMonth {
  year: number
  month: number
  weeks: CalendarDayCell[][]
  /** Confirmed commitments no display-ready CalendarEvent currently references. Never placed on a day — D-005: an unscheduled promise has no calendar time to invent. */
  unscheduledCommitments: SemanticObject[]
}

/**
 * Seam for D-009 temporal-confirmation provenance, reconciled after TASK-019 (parallel work) merges.
 * domain.ts's CalendarEvent has no `confirmation`/provenance field yet, and no path in this codebase
 * currently creates one — so nothing can yet prove a CalendarEvent's `startsAt` passed an explicit
 * scheduling-confirmation gesture. `status: 'scheduled'` and a parseable `startsAt` are structural
 * facts, not evidence of that gesture, so this fails closed and reports every event not display-ready
 * until TASK-019 defines what a provenanced CalendarEvent looks like. Callers that already have such
 * evidence (or tests exercising grid/linking behavior independent of provenance) pass their own
 * predicate as the fifth argument to buildCalendarMonth. Swap this one predicate — not the
 * rendering/grid code — once TASK-019 lands.
 */
export type TemporalProvenanceCheck = (event: CalendarEvent) => boolean
export const defaultTemporalProvenanceCheck: TemporalProvenanceCheck = () => false

export function parseLocalDateKey(key: string): Date {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, month - 1, day)
}

export function dayNumber(key: string): number {
  return Number(key.slice(8, 10))
}

export function monthLabel(year: number, month: number): string {
  return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(year, month, 1))
}

export function addMonths(year: number, month: number, delta: number): { year: number; month: number } {
  const total = year * 12 + month + delta
  return { year: Math.floor(total / 12), month: ((total % 12) + 12) % 12 }
}

export function dayAriaLabel(cell: CalendarDayCell): string {
  const spoken = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(parseLocalDateKey(cell.date))
  const parts = [spoken]
  if (cell.isToday) parts.push('today')
  if (cell.events.length) parts.push(`${cell.events.length} event${cell.events.length === 1 ? '' : 's'}`)
  if (cell.proposedDates.length) parts.push(`${cell.proposedDates.length} proposed date${cell.proposedDates.length === 1 ? '' : 's'}`)
  return parts.join(', ')
}

/** Sunday-start weeks covering the full month, including the leading/trailing days needed to fill each row. Every step advances by local calendar day, never by a fixed millisecond offset, so DST transitions cannot skip or repeat a day. */
function calendarGridDates(year: number, month: number): Date[] {
  const firstOfMonth = new Date(year, month, 1)
  const start = new Date(year, month, 1 - firstOfMonth.getDay())
  const lastOfMonth = new Date(year, month + 1, 0)
  const end = new Date(year, month, lastOfMonth.getDate() + (6 - lastOfMonth.getDay()))
  const dates: Date[] = []
  for (let cursor = start; cursor.getTime() <= end.getTime(); cursor = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + 1)) {
    dates.push(cursor)
  }
  return dates
}

export function buildCalendarMonth(
  model: PersistedState,
  year: number,
  month: number,
  now: Date,
  isEventDisplayReady: TemporalProvenanceCheck = defaultTemporalProvenanceCheck
): CalendarMonth {
  const todayKey = localDateKey(now)
  const readyEvents = model.calendarEvents.filter(isEventDisplayReady)
  const eventsByDay = new Map<string, CalendarDayEvent[]>()
  for (const event of readyEvents) {
    const key = localDateKey(new Date(event.startsAt))
    const linkedObjects = event.objectIds
      .map(id => model.semanticObjects.find(o => o.id === id))
      .filter((o): o is SemanticObject => Boolean(o))
    const list = eventsByDay.get(key) ?? []
    list.push({ event, linkedObjects })
    eventsByDay.set(key, list)
  }

  const commitments = confirmedSemanticObjects(model).filter(o => o.kind === 'commitment')
  const linkedObjectIds = new Set(readyEvents.flatMap(e => e.objectIds))
  const unscheduledCommitments = commitments.filter(o => !linkedObjectIds.has(o.id))

  const proposedByDay = new Map<string, ProposedDateMarker[]>()
  for (const interpretation of currentInterpretations(model)) {
    if (interpretation.reviewState === 'rejected') continue
    const objectId = interpretation.legacy.id
    if (model.semanticObjects.find(o => o.id === objectId)?.status === 'archived') continue
    const raw = interpretation.legacy.metadata.deadline
    if (!validDateKey(raw)) continue
    const list = proposedByDay.get(raw) ?? []
    list.push({ interpretationId: interpretation.id, objectId, kind: interpretation.legacy.kind, summary: interpretation.summary, date: raw })
    proposedByDay.set(raw, list)
  }

  const dates = calendarGridDates(year, month)
  const weeks: CalendarDayCell[][] = []
  for (let i = 0; i < dates.length; i += 7) {
    weeks.push(dates.slice(i, i + 7).map(date => {
      const key = localDateKey(date)
      return {
        date: key,
        inCurrentMonth: date.getMonth() === month,
        isToday: key === todayKey,
        events: (eventsByDay.get(key) ?? []).slice().sort((a, b) =>
          Date.parse(a.event.startsAt) - Date.parse(b.event.startsAt) || a.event.id.localeCompare(b.event.id)),
        proposedDates: (proposedByDay.get(key) ?? []).slice().sort((a, b) => a.summary.localeCompare(b.summary))
      }
    }))
  }
  return { year, month, weeks, unscheduledCommitments: unscheduledCommitments.slice().sort((a, b) => a.id.localeCompare(b.id)) }
}
