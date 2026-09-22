import { describe, expect, it } from 'vitest'
import type { CalendarEvent, Interpretation, PersistedState, SemanticObject } from './domain'
import {
  addDays, addMonths, buildCalendarMonth, buildCalendarTimeGrid, dayAriaLabel, defaultTemporalProvenanceCheck, monthLabel, parseLocalDateKey, weekStart
} from './calendar'
import { localDateKey } from './morningDigest'
import { createCalendarCommitment } from './calendarEntry'
import { legacyUiProjection, reconcileLegacyUi } from './migration'

const object = (id: string, kind: SemanticObject['kind'], status: SemanticObject['status'] = 'confirmed'): SemanticObject => ({
  id, kind, metadata: {}, summary: `${id} summary`, status, captureIds: [], interpretationIds: [id], reminders: []
})
const interpretation = (id: string, legacyId: string, overrides: Partial<Interpretation> = {}): Interpretation => ({
  id, version: 1, captureIds: [], recordedAt: '2026-09-14T00:00:00.000Z', summary: `${legacyId} summary`, rationale: 'r',
  confidence: .9, proposedKind: 'commitment', reviewState: 'accepted', confirmation: { transition: 'commitment', at: '2026-09-14T00:00:00.000Z' },
  legacy: { id: legacyId, kind: 'commitment', confidence: .9, relationships: [], history: [], status: 'confirmed', metadata: {},
    interpretation: { summary: `${legacyId} summary`, suggestedKind: 'commitment', rationale: 'r' } },
  ...overrides
})
const event = (id: string, startsAt: string, objectIds: string[] = [], overrides: Partial<CalendarEvent> = {}): CalendarEvent => ({
  id, startsAt, objectIds, title: id, temporalContext: 'local', captureIds: [], status: 'scheduled', ...overrides
})
function model(partial: Partial<PersistedState> = {}): PersistedState {
  return { schemaVersion: 2, captures: [], interpretations: [], semanticObjects: [], calendarEvents: [], relationships: [], legacyUiIds: [], canvas: [], ...partial }
}

describe('calendar grid math', () => {
  const cases: [number, number][] = [
    [2026, 8],  // Sept 2026 — starts mid-week
    [2026, 1],  // Feb 2026 — non-leap
    [2028, 1],  // Feb 2028 — leap year
    [2026, 0],  // Jan 2026 — year start
    [2026, 11], // Dec 2026 — year end
    [2026, 2],  // month that begins on Sunday somewhere in the cycle
  ]
  it.each(cases)('produces full Sunday-start weeks covering %i-%i with no gaps or duplicates', (year, month) => {
    const calendar = buildCalendarMonth(model(), year, month, new Date(year, month, 1))
    const flat = calendar.weeks.flat()
    expect(flat.length % 7).toBe(0)
    expect(calendar.weeks.every(week => week.length === 7)).toBe(true)
    // Sunday-start: first cell of every week is a Sunday, last is a Saturday.
    for (const week of calendar.weeks) {
      expect(parseLocalDateKey(week[0].date).getDay()).toBe(0)
      expect(parseLocalDateKey(week[6].date).getDay()).toBe(6)
    }
    // Consecutive local calendar days, no skips or repeats (guards against DST/UTC drift).
    for (let i = 1; i < flat.length; i++) {
      const prev = parseLocalDateKey(flat[i - 1].date)
      const next = parseLocalDateKey(flat[i].date)
      expect(next.getTime() - prev.getTime()).toBeGreaterThan(0)
      expect(localDateKey(new Date(prev.getFullYear(), prev.getMonth(), prev.getDate() + 1))).toBe(flat[i].date)
    }
    expect(new Set(flat.map(d => d.date)).size).toBe(flat.length)
    // Every actual day of the target month appears exactly once, flagged inCurrentMonth.
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const inMonth = flat.filter(d => d.inCurrentMonth)
    expect(inMonth).toHaveLength(daysInMonth)
    expect(inMonth.every(d => parseLocalDateKey(d.date).getMonth() === month)).toBe(true)
  })
  it('marks only the local today cell as isToday', () => {
    const now = new Date(2026, 8, 14, 23, 59)
    const calendar = buildCalendarMonth(model(), 2026, 8, now)
    const todays = calendar.weeks.flat().filter(d => d.isToday)
    expect(todays.map(d => d.date)).toEqual(['2026-09-14'])
  })
  it('addMonths rolls over year boundaries in both directions', () => {
    expect(addMonths(2026, 11, 1)).toEqual({ year: 2027, month: 0 })
    expect(addMonths(2026, 0, -1)).toEqual({ year: 2025, month: 11 })
    expect(addMonths(2026, 5, 0)).toEqual({ year: 2026, month: 5 })
  })
  it('keeps Week and Day navigation on local calendar dates through month, year, and DST boundaries', () => {
    expect(weekStart('2026-03-08')).toBe('2026-03-08')
    expect(weekStart('2026-03-14')).toBe('2026-03-08')
    expect(addDays('2026-03-08', 7)).toBe('2026-03-15')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
  })
  it('monthLabel reads naturally', () => {
    expect(monthLabel(2026, 8)).toBe('September 2026')
  })
})

describe('week and day time-grid data', () => {
  it('returns exact consecutive local days and buckets confirmed events without changing their time', () => {
    const state = model({ calendarEvents: [event('morning-call', '2026-09-15T09:30:00.000Z')] })
    const week = buildCalendarTimeGrid(state, '2026-09-13', 7, new Date(2026, 8, 14), () => true)
    expect(week.days.map(day => day.date)).toEqual(['2026-09-13', '2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-19'])
    expect(week.days.flatMap(day => day.events).map(item => item.event.startsAt)).toEqual(['2026-09-15T09:30:00.000Z'])
    expect(buildCalendarTimeGrid(state, '2026-09-15', 1, new Date(2026, 8, 14), () => true).days).toHaveLength(1)
  })
})

describe('calendar commitment entry', () => {
  it('records an explicitly confirmed obligation with source evidence and no CalendarEvent or invented time', () => {
    const commitment = createCalendarCommitment('Send the proposal')
    expect(commitment.kind).toBe('commitment')
    expect(commitment.status).toBe('confirmed')
    expect(commitment.metadata.deadline).toBeUndefined()
    const base = legacyUiProjection(model())
    const saved = reconcileLegacyUi({ ...base, objects: [commitment] })
    expect(saved.calendarEvents).toEqual([])
    expect(saved.captures).toHaveLength(1)
    expect(saved.captures[0].originalContent).toBe('Send the proposal')
    expect(saved.semanticObjects).toMatchObject([{ kind: 'commitment', status: 'confirmed', summary: 'Send the proposal' }])
  })
})

describe('calendar events', () => {
  it('buckets a scheduled event onto its local calendar day regardless of the encoded UTC offset', () => {
    const local = new Date(2026, 8, 14, 21, 30)
    const state = model({ calendarEvents: [event('meeting', local.toISOString())] })
    const calendar = buildCalendarMonth(state, 2026, 8, local, () => true)
    const cell = calendar.weeks.flat().find(d => d.date === localDateKey(local))!
    expect(cell.events.map(e => e.event.id)).toEqual(['meeting'])
  })
  it('fails closed by default: bare status and a parseable timestamp are not D-009 temporal-confirmation evidence, pending TASK-019', () => {
    const now = new Date(2026, 8, 14, 9)
    expect(defaultTemporalProvenanceCheck(event('cancelled', now.toISOString(), [], { status: 'cancelled' }))).toBe(false)
    expect(defaultTemporalProvenanceCheck(event('bad', 'Tuesday'))).toBe(false)
    expect(defaultTemporalProvenanceCheck(event('ok', now.toISOString()))).toBe(false)
    const state = model({ calendarEvents: [event('scheduled-but-unconfirmed', now.toISOString())] })
    const calendar = buildCalendarMonth(state, 2026, 8, now)
    expect(calendar.weeks.flat().flatMap(d => d.events)).toEqual([])
  })
  it('resolves linked objects for a display-ready event and drops dangling ids without throwing', () => {
    const now = new Date(2026, 8, 14, 9)
    const promise = object('promise', 'commitment')
    const state = model({ semanticObjects: [promise], calendarEvents: [event('meeting', now.toISOString(), ['promise', 'missing'])] })
    const calendar = buildCalendarMonth(state, 2026, 8, now, () => true)
    const cell = calendar.weeks.flat().find(d => d.date === localDateKey(now))!
    expect(cell.events[0].linkedObjects).toEqual([promise])
  })
  it('supports a caller-supplied provenance predicate without touching grid logic (TASK-019 seam)', () => {
    const now = new Date(2026, 8, 14, 9)
    const state = model({ calendarEvents: [event('meeting', now.toISOString())] })
    expect(buildCalendarMonth(state, 2026, 8, now, () => false).weeks.flat().flatMap(d => d.events)).toEqual([])
    expect(buildCalendarMonth(state, 2026, 8, now, () => true).weeks.flat().flatMap(d => d.events).map(e => e.event.id)).toEqual(['meeting'])
  })
  it('sorts same-day events by actual instant rather than ISO string, with a deterministic id tie-break', () => {
    // Two instants 5 minutes apart, each written with a different UTC offset so the encoded wall-clock
    // digits sort backwards from the real chronological order (a mixed-offset regression case).
    const earlierInstant = Date.UTC(2026, 8, 14, 14, 0, 0)
    const laterInstant = earlierInstant + 5 * 60 * 1000
    const isoAtOffset = (utcMillis: number, offsetHours: number): string => {
      const wall = new Date(utcMillis + offsetHours * 3600000)
      const pad = (n: number) => String(n).padStart(2, '0')
      const sign = offsetHours >= 0 ? '+' : '-'
      return `${wall.getUTCFullYear()}-${pad(wall.getUTCMonth() + 1)}-${pad(wall.getUTCDate())}T` +
        `${pad(wall.getUTCHours())}:${pad(wall.getUTCMinutes())}:00${sign}${pad(Math.abs(offsetHours))}:00`
    }
    const earlyHighOffset = event('utc-plus6', isoAtOffset(earlierInstant, 6)) // wall "20:00+06:00", instant 14:00 UTC
    const lateLowOffset = event('utc-minus5', isoAtOffset(laterInstant, -5)) // wall "09:05-05:00", instant 14:05 UTC
    expect(earlyHighOffset.startsAt > lateLowOffset.startsAt).toBe(true) // ISO-string order is inverted from real order
    const tieA = event('tie-a', new Date(earlierInstant).toISOString())
    const tieB = event('tie-b', new Date(earlierInstant).toISOString())
    const state = model({ calendarEvents: [lateLowOffset, earlyHighOffset, tieB, tieA] })
    const now = new Date(earlierInstant)
    const calendar = buildCalendarMonth(state, now.getFullYear(), now.getMonth(), now, () => true)
    const cell = calendar.weeks.flat().find(d => d.date === localDateKey(now))!
    expect(cell.events.map(e => e.event.id)).toEqual(['tie-a', 'tie-b', 'utc-plus6', 'utc-minus5'])
  })
})

describe('unscheduled commitments', () => {
  it('does not let a bare-status linked event suppress a commitment by default (D-009 fail-closed, pending TASK-019)', () => {
    const now = new Date(2026, 8, 14, 9)
    const linked = object('linked', 'commitment')
    const loose = object('loose', 'commitment')
    const reviewOnly = object('review-only', 'commitment', 'review')
    const state = model({
      semanticObjects: [linked, loose, reviewOnly],
      interpretations: [interpretation('linked', 'linked'), interpretation('loose', 'loose'),
        interpretation('review-only', 'review-only', { reviewState: 'review', confirmation: undefined })],
      calendarEvents: [event('meeting', now.toISOString(), ['linked'])]
    })
    const calendar = buildCalendarMonth(state, 2026, 8, now)
    expect(calendar.unscheduledCommitments.map(o => o.id).sort()).toEqual(['linked', 'loose'])
  })
  it('excludes a commitment from unscheduled once its linked event passes a caller-supplied provenance check (TASK-019 seam)', () => {
    const now = new Date(2026, 8, 14, 9)
    const linked = object('linked', 'commitment')
    const loose = object('loose', 'commitment')
    const state = model({
      semanticObjects: [linked, loose],
      interpretations: [interpretation('linked', 'linked'), interpretation('loose', 'loose')],
      calendarEvents: [event('meeting', now.toISOString(), ['linked'])]
    })
    const calendar = buildCalendarMonth(state, 2026, 8, now, () => true)
    expect(calendar.unscheduledCommitments.map(o => o.id)).toEqual(['loose'])
  })
  it('keeps a commitment unscheduled when its only link is a non-display-ready (cancelled) event', () => {
    const now = new Date(2026, 8, 14, 9)
    const promise = object('promise', 'commitment')
    const state = model({
      semanticObjects: [promise],
      interpretations: [interpretation('promise', 'promise')],
      calendarEvents: [event('meeting', now.toISOString(), ['promise'], { status: 'cancelled' })]
    })
    const calendar = buildCalendarMonth(state, 2026, 8, now)
    expect(calendar.unscheduledCommitments.map(o => o.id)).toEqual(['promise'])
  })
})

describe('proposed dates stay unconfirmed and never merge into events', () => {
  it('plots a legacy deadline on its exact local day at year boundaries, with no UTC shift', () => {
    const janState = model({
      semanticObjects: [object('nye', 'idea')],
      interpretations: [interpretation('i1', 'nye', { legacy: { id: 'nye', kind: 'idea', confidence: .9, relationships: [], history: [], status: 'confirmed',
        metadata: { deadline: '2026-01-01' }, interpretation: { summary: 'nye', suggestedKind: 'idea', rationale: 'r' } } })]
    })
    const jan = buildCalendarMonth(janState, 2026, 0, new Date(2026, 0, 1))
    expect(jan.weeks.flat().find(d => d.date === '2026-01-01')!.proposedDates.map(p => p.objectId)).toEqual(['nye'])

    const decState = model({
      semanticObjects: [object('eoy', 'idea')],
      interpretations: [interpretation('i2', 'eoy', { legacy: { id: 'eoy', kind: 'idea', confidence: .9, relationships: [], history: [], status: 'confirmed',
        metadata: { deadline: '2026-12-31' }, interpretation: { summary: 'eoy', suggestedKind: 'idea', rationale: 'r' } } })]
    })
    const dec = buildCalendarMonth(decState, 2026, 11, new Date(2026, 11, 1))
    expect(dec.weeks.flat().find(d => d.date === '2026-12-31')!.proposedDates.map(p => p.objectId)).toEqual(['eoy'])
  })
  it('ignores unparseable or impossible date strings instead of guessing', () => {
    const legacyWith = (deadline?: string) => ({ id: 'x', kind: 'idea' as const, confidence: .9, relationships: [], history: [], status: 'confirmed' as const,
      metadata: { deadline }, interpretation: { summary: 'x', suggestedKind: 'idea' as const, rationale: 'r' } })
    for (const bad of ['Needs a date', 'Tuesday', '2026-13-40', '2026-02-30', undefined]) {
      const state = model({ semanticObjects: [object('x', 'idea')], interpretations: [interpretation('i', 'x', { legacy: legacyWith(bad) })] })
      const calendar = buildCalendarMonth(state, 2026, 8, new Date(2026, 8, 1))
      expect(calendar.weeks.flat().flatMap(d => d.proposedDates)).toEqual([])
    }
  })
  it('excludes rejected interpretations and archived objects, and only surfaces the current (non-superseded) version', () => {
    const now = new Date(2026, 8, 1)
    const legacyWith = (deadline: string) => ({ id: 'x', kind: 'idea' as const, confidence: .9, relationships: [], history: [], status: 'confirmed' as const,
      metadata: { deadline }, interpretation: { summary: 'x', suggestedKind: 'idea' as const, rationale: 'r' } })
    const rejected = model({ interpretations: [interpretation('i', 'x', { reviewState: 'rejected', legacy: legacyWith('2026-09-10') })] })
    expect(buildCalendarMonth(rejected, 2026, 8, now).weeks.flat().flatMap(d => d.proposedDates)).toEqual([])

    const archived = model({ semanticObjects: [object('x', 'idea', 'archived')], interpretations: [interpretation('i', 'x', { legacy: legacyWith('2026-09-10') })] })
    expect(buildCalendarMonth(archived, 2026, 8, now).weeks.flat().flatMap(d => d.proposedDates)).toEqual([])

    const superseded: PersistedState = model({
      semanticObjects: [object('x', 'idea')],
      interpretations: [
        interpretation('v1', 'x', { legacy: legacyWith('2026-09-05') }),
        interpretation('v2', 'x', { previousId: 'v1', legacy: legacyWith('2026-09-20') })
      ]
    })
    const calendar = buildCalendarMonth(superseded, 2026, 8, now)
    expect(calendar.weeks.flat().find(d => d.date === '2026-09-05')?.proposedDates ?? []).toEqual([])
    expect(calendar.weeks.flat().find(d => d.date === '2026-09-20')!.proposedDates.map(p => p.interpretationId)).toEqual(['v2'])
  })
  it('never places a proposed date inside a day cell\'s events list', () => {
    const now = new Date(2026, 8, 14)
    const legacy = { id: 'x', kind: 'commitment' as const, confidence: .9, relationships: [], history: [], status: 'confirmed' as const,
      metadata: { deadline: '2026-09-14' }, interpretation: { summary: 'x', suggestedKind: 'commitment' as const, rationale: 'r' } }
    const state = model({ semanticObjects: [object('x', 'commitment')], interpretations: [interpretation('i', 'x', { legacy })] })
    const calendar = buildCalendarMonth(state, 2026, 8, now)
    const cell = calendar.weeks.flat().find(d => d.date === '2026-09-14')!
    expect(cell.events).toEqual([])
    expect(cell.proposedDates).toHaveLength(1)
  })
})

describe('accessibility label', () => {
  it('describes the date, today status, and counts of events and proposed dates', () => {
    const base = { date: '2026-09-14', inCurrentMonth: true, isToday: false, events: [], proposedDates: [] }
    expect(dayAriaLabel(base)).toBe('Monday, September 14, 2026')
    expect(dayAriaLabel({ ...base, isToday: true })).toBe('Monday, September 14, 2026, today')
    expect(dayAriaLabel({ ...base, events: [{}, {}] as never })).toBe('Monday, September 14, 2026, 2 events')
    expect(dayAriaLabel({ ...base, proposedDates: [{}] as never })).toBe('Monday, September 14, 2026, 1 proposed date')
  })
})
