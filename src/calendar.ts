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

export interface CalendarTimeGrid {
  days: CalendarDayCell[]
  unscheduledCommitments: SemanticObject[]
}

/**
 * Seam for D-009 temporal-confirmation provenance. A scheduled status and parseable timestamp are
 * structural facts, not evidence of a separate scheduling-confirmation gesture, so the reusable
 * default fails closed. CalendarView supplies a predicate backed by TASK-019's active temporal
 * decisions; tests focused on grid/linking behavior can supply their own predicate.
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

/** Advance local calendar days rather than milliseconds so navigation remains stable across DST. */
export function addDays(key: string, delta: number): string {
  const date = parseLocalDateKey(key)
  return localDateKey(new Date(date.getFullYear(), date.getMonth(), date.getDate() + delta))
}

/** Sunday-start week, matching the Month grid's labels and avoiding UTC date shifts. */
export function weekStart(key: string): string {
  const date = parseLocalDateKey(key)
  return addDays(key, -date.getDay())
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
  const cells = dates.map(date => cellForDate(date, month, todayKey, eventsByDay, proposedByDay))
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7))
  return { year, month, weeks, unscheduledCommitments: unscheduledCommitments.slice().sort((a, b) => a.id.localeCompare(b.id)) }
}

/** Builds consecutive local day cells for Week and Day without introducing event times. */
export function buildCalendarTimeGrid(
  model: PersistedState,
  start: string,
  days: number,
  now: Date,
  isEventDisplayReady: TemporalProvenanceCheck = defaultTemporalProvenanceCheck
): CalendarTimeGrid {
  if (!validDateKey(start) || !Number.isInteger(days) || days < 1) throw new Error('Calendar time grid requires a valid local start date and positive day count.')
  const todayKey = localDateKey(now)
  const readyEvents = model.calendarEvents.filter(isEventDisplayReady)
  const eventsByDay = new Map<string, CalendarDayEvent[]>()
  for (const event of readyEvents) {
    const key = localDateKey(new Date(event.startsAt))
    const linkedObjects = event.objectIds.map(id => model.semanticObjects.find(o => o.id === id)).filter((o): o is SemanticObject => Boolean(o))
    const list = eventsByDay.get(key) ?? []
    list.push({ event, linkedObjects })
    eventsByDay.set(key, list)
  }
  const proposedByDay = proposedDatesByDay(model)
  const linkedObjectIds = new Set(readyEvents.flatMap(e => e.objectIds))
  const unscheduledCommitments = confirmedSemanticObjects(model).filter(o => o.kind === 'commitment' && !linkedObjectIds.has(o.id))
  const startDate = parseLocalDateKey(start)
  const cells = Array.from({ length: days }, (_, index) => {
    const date = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate() + index)
    return cellForDate(date, date.getMonth(), todayKey, eventsByDay, proposedByDay)
  })
  return { days: cells, unscheduledCommitments: unscheduledCommitments.slice().sort((a, b) => a.id.localeCompare(b.id)) }
}

function proposedDatesByDay(model: PersistedState): Map<string, ProposedDateMarker[]> {
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
  return proposedByDay
}

function cellForDate(
  date: Date,
  currentMonth: number,
  todayKey: string,
  eventsByDay: Map<string, CalendarDayEvent[]>,
  proposedByDay: Map<string, ProposedDateMarker[]>
): CalendarDayCell {
  const key = localDateKey(date)
  return {
    date: key,
    inCurrentMonth: date.getMonth() === currentMonth,
    isToday: key === todayKey,
    events: (eventsByDay.get(key) ?? []).slice().sort((a, b) => Date.parse(a.event.startsAt) - Date.parse(b.event.startsAt) || a.event.id.localeCompare(b.event.id)),
    proposedDates: (proposedByDay.get(key) ?? []).slice().sort((a, b) => a.summary.localeCompare(b.summary))
  }
}
