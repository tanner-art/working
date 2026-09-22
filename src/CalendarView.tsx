import { useMemo, useState, type CSSProperties, type FormEvent } from 'react'
import type { AppState } from './domain'
import { objectLabels } from './domain'
import { reconcileLegacyUi } from './migration'
import { localDateKey } from './morningDigest'
import { activeTemporalDecisions, temporalFactIsCurrent } from './temporalConfirmation'
import { createCalendarCommitment } from './calendarEntry'
import { buildCalendarMonth, buildCalendarTimeGrid, dayAriaLabel, dayNumber, monthLabel, navigateCalendarDate, parseLocalDateKey, weekStart, WEEKDAY_LABELS } from './calendar'
import type { CalendarDayCell } from './calendar'

type CalendarMode = 'month' | 'week' | 'day'
const hours = Array.from({ length: 24 }, (_, hour) => hour)
const dayHeading = (key: string) => new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).format(parseLocalDateKey(key))
const time = (iso: string) => new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(new Date(iso))
const dateLabel = (key: string) => new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).format(parseLocalDateKey(key))

export function CalendarView({ state, onOpen, onUpdate }: { state: AppState; onOpen: (id: string) => void; onUpdate: (next: (state: AppState) => AppState) => void }) {
  const model = useMemo(() => reconcileLegacyUi(state), [state])
  const todayKey = localDateKey(new Date())
  const [mode, setMode] = useState<CalendarMode>('month')
  const [selected, setSelected] = useState(todayKey)
  const [commitment, setCommitment] = useState('')
  const confirmedEventIds = useMemo(() => new Set(activeTemporalDecisions(model)
    .filter(entry => entry.target.kind === 'event-scheduling' && temporalFactIsCurrent(model, entry))
    .map(entry => entry.target.kind === 'event-scheduling' ? entry.target.eventId : '')), [model])
  const eventReady = (event: { id: string }) => confirmedEventIds.has(event.id)
  const selectedDate = parseLocalDateKey(selected)
  const month = useMemo(() => buildCalendarMonth(model, selectedDate.getFullYear(), selectedDate.getMonth(), new Date(), eventReady), [model, selected, confirmedEventIds])
  const timeGrid = useMemo(() => buildCalendarTimeGrid(model, mode === 'week' ? weekStart(selected) : selected, mode === 'week' ? 7 : 1, new Date(), eventReady), [model, mode, selected, confirmedEventIds])
  const unscheduled = mode === 'month' ? month.unscheduledCommitments : timeGrid.unscheduledCommitments
  const selectedCell = month.weeks.flat().find(day => day.date === selected)
  const go = (direction: -1 | 1) => setSelected(navigateCalendarDate(selected, mode, direction))
  const submitCommitment = (event: FormEvent) => {
    event.preventDefault()
    if (!commitment.trim()) return
    const item = createCalendarCommitment(commitment)
    onUpdate(current => ({ ...current, objects: [item, ...current.objects] }))
    setCommitment('')
  }

  return <div className="page calendar-page">
    <header className="page-header"><div><p className="eyebrow">Time, scheduled and proposed</p><h1>Calendar</h1></div></header>
    <p className="lede">CalendarEvents, Commitments, and proposed dates stay distinct. An obligation has no time until you explicitly schedule a separate CalendarEvent.</p>
    <form className="calendar-commitment-form" onSubmit={submitCommitment}><label>New commitment<input aria-label="New commitment" value={commitment} onChange={event => setCommitment(event.target.value)} placeholder="I’ll send the draft" /></label><button className="primary">Add commitment</button><small>This confirms the obligation only. It remains unscheduled.</small></form>
    <div className="month-calendar">
      <div className="calendar-toolbar"><button type="button" className="secondary" aria-label={`Previous ${mode}`} onClick={() => go(-1)}>‹</button><h2 id="calendar-view-label">{mode === 'month' ? monthLabel(selectedDate.getFullYear(), selectedDate.getMonth()) : mode === 'week' ? `${dateLabel(timeGrid.days[0].date)} – ${dateLabel(timeGrid.days.at(-1)!.date)}` : dayHeading(selected)}</h2><button type="button" className="secondary" aria-label={`Next ${mode}`} onClick={() => go(1)}>›</button><button type="button" className="secondary" onClick={() => setSelected(localDateKey(new Date()))}>Today</button><div className="calendar-modes" role="group" aria-label="Calendar view">{(['month', 'week', 'day'] as const).map(value => <button type="button" key={value} className={mode === value ? 'active' : 'secondary'} aria-pressed={mode === value} onClick={() => setMode(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div></div>
      {mode === 'month' ? <MonthGrid calendar={month} selected={selected} onSelect={setSelected} /> : <TimeGrid days={timeGrid.days} onOpen={onOpen} />}
    </div>
    {mode === 'month' && selectedCell && <SelectedDayDetail day={selectedCell} onOpen={onOpen} />}
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Not tied to a time</p><h2>Unscheduled commitments</h2></div><span>{unscheduled.length} shown</span></div>{unscheduled.length ? <ul className="detail-list">{unscheduled.map(o => <li key={o.id}><button type="button" className="commitment-row clickable-row" onClick={() => onOpen(o.id)}><span className="time-dot" /><div><strong>{o.summary}</strong><small>No CalendarEvent time chosen yet.</small></div><span className="kind-chip">{objectLabels[o.kind]}</span></button></li>)}</ul> : <div className="empty">No unscheduled commitments. Confirmed obligations without an event appear here.</div>}</section>
  </div>
}

function MonthGrid({ calendar, selected, onSelect }: { calendar: ReturnType<typeof buildCalendarMonth>; selected: string; onSelect: (date: string) => void }) {
  return <table className="month-grid" role="grid" aria-labelledby="calendar-view-label"><thead><tr>{WEEKDAY_LABELS.map(w => <th key={w.short} scope="col" abbr={w.long}>{w.short}</th>)}</tr></thead><tbody>{calendar.weeks.map((week, index) => <tr key={index}>{week.map(day => <MonthCell key={day.date} day={day} selected={selected} onSelect={onSelect} />)}</tr>)}</tbody></table>
}
function MonthCell({ day, selected, onSelect }: { day: CalendarDayCell; selected: string; onSelect: (date: string) => void }) {
  const classes = ['calendar-cell', !day.inCurrentMonth ? 'outside-month' : '', day.isToday ? 'is-today' : '', day.date === selected ? 'is-selected' : ''].filter(Boolean).join(' ')
  return <td><button type="button" className={classes} aria-current={day.isToday ? 'date' : undefined} aria-pressed={day.date === selected} aria-label={dayAriaLabel(day)} onClick={() => onSelect(day.date)}><span className="day-number">{dayNumber(day.date)}</span><span className="day-chips">{day.events.slice(0, 2).map(e => <span key={e.event.id} className="chip chip-event">{e.event.title}</span>)}{day.proposedDates.slice(0, 2).map(p => <span key={p.interpretationId} className="chip chip-proposed">{p.summary}</span>)}</span></button></td>
}
function SelectedDayDetail({ day, onOpen }: { day: CalendarDayCell; onOpen: (id: string) => void }) {
  return <section className="calendar-detail" aria-live="polite"><h3>{dayHeading(day.date)}{day.isToday && ' · Today'}</h3>
    <div className="detail-group"><p className="section-label">Events</p>{day.events.length ? <ul className="detail-list">{day.events.map(({ event, linkedObjects }) => <li key={event.id} className="detail-card"><strong>{event.title}</strong><small>{time(event.startsAt)} · {event.temporalContext}</small>{linkedObjects.length > 0 && <div className="detail-links">{linkedObjects.map(object => <button type="button" key={object.id} className="quiet-button" onClick={() => onOpen(object.id)}>{objectLabels[object.kind]}: {object.summary} →</button>)}</div>}</li>)}</ul> : <p className="empty-inline">No scheduled events on this day.</p>}</div>
    <div className="detail-group"><p className="section-label">Proposed dates — unconfirmed</p>{day.proposedDates.length ? <ul className="detail-list">{day.proposedDates.map(marker => <li key={marker.interpretationId} className="detail-card proposed"><button type="button" className="quiet-button" onClick={() => onOpen(marker.objectId)}>{objectLabels[marker.kind]}: {marker.summary} →</button><small>Not a scheduled time — open the object to confirm or change it.</small></li>)}</ul> : <p className="empty-inline">No proposed dates on this day.</p>}</div>
  </section>
}
function TimeGrid({ days, onOpen }: { days: CalendarDayCell[]; onOpen: (id: string) => void }) {
  const now = new Date(); const nowKey = localDateKey(now)
  const columns = { '--day-count': days.length } as CSSProperties
  return <section className={`time-grid-wrap ${days.length === 1 ? 'one-day' : 'week-grid'}`} aria-labelledby="calendar-view-label"><div className="time-grid-head" style={columns}><span aria-hidden="true" />{days.map(day => <span key={day.date} className={day.isToday ? 'is-today' : ''}>{dateLabel(day.date)}</span>)}</div><div className="time-grid" style={columns}><div className="time-labels" aria-label="Hours">{hours.map(hour => <span key={hour}>{hour === 0 ? '' : new Intl.DateTimeFormat('en-US', { hour: 'numeric' }).format(new Date(2026, 0, 1, hour))}</span>)}</div>{days.map(day => <section key={day.date} className={`time-column ${day.isToday ? 'is-today' : ''}`} aria-label={dayHeading(day.date)}>{hours.map(hour => <div key={hour} className="time-slot" aria-hidden="true" />)}{day.proposedDates.map(marker => <button type="button" key={marker.interpretationId} className="time-proposed" onClick={() => onOpen(marker.objectId)}>{marker.summary}</button>)}{day.events.map(({ event, linkedObjects }) => { const start = new Date(event.startsAt); const position = (start.getHours() * 60 + start.getMinutes()) / 60; return <section key={event.id} className="time-event" aria-label={`${event.title}, ${time(event.startsAt)}`} style={{ top: `${position * 52}px` }}><strong>{event.title}</strong><small>{time(event.startsAt)}</small>{linkedObjects.map(object => <button key={object.id} type="button" onClick={() => onOpen(object.id)}>{objectLabels[object.kind]}: {object.summary}</button>)}</section> })}{day.date === nowKey && <span className="current-time" style={{ top: `${(now.getHours() * 60 + now.getMinutes()) / 60 * 52}px` }} aria-label="Current time" />}</section>)}</div></section>
}
