import { useMemo, useState } from 'react'
import type { AppState } from './domain'
import { objectLabels } from './domain'
import { reconcileLegacyUi } from './migration'
import { localDateKey } from './morningDigest'
import {
  addMonths, buildCalendarMonth, dayAriaLabel, dayNumber, monthLabel, parseLocalDateKey, WEEKDAY_LABELS
} from './calendar'
import type { CalendarDayCell } from './calendar'

const dayHeading = (key: string) => new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).format(parseLocalDateKey(key))
const time = (iso: string) => new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(new Date(iso))

export function CalendarView({ state, onOpen }: { state: AppState; onOpen: (id: string) => void }) {
  const model = useMemo(() => reconcileLegacyUi(state), [state])
  const todayKey = useMemo(() => localDateKey(new Date()), [])
  const [cursor, setCursor] = useState(() => { const d = new Date(); return { year: d.getFullYear(), month: d.getMonth() } })
  const [selected, setSelected] = useState(todayKey)
  const calendar = useMemo(() => buildCalendarMonth(model, cursor.year, cursor.month, new Date()), [model, cursor])
  const cells = calendar.weeks.flat()
  const selectedCell = cells.find(day => day.date === selected) ?? cells.find(day => day.isToday)

  const go = (delta: number) => setCursor(current => addMonths(current.year, current.month, delta))
  const goToday = () => {
    const now = new Date()
    setCursor({ year: now.getFullYear(), month: now.getMonth() })
    setSelected(localDateKey(now))
  }
  const selectDay = (day: CalendarDayCell) => {
    setSelected(day.date)
    if (!day.inCurrentMonth) setCursor({ year: parseLocalDateKey(day.date).getFullYear(), month: parseLocalDateKey(day.date).getMonth() })
  }

  return <div className="page calendar-page">
    <header className="page-header">
      <div><p className="eyebrow">Time, scheduled and proposed</p><h1>Calendar</h1></div>
    </header>
    <p className="lede">CalendarEvents, linked or unscheduled Commitments, and unverified proposed dates stay visually separate here. A proposed date is never shown as a scheduled time.</p>

    <div className="month-calendar">
      <div className="calendar-toolbar">
        <button type="button" className="secondary" aria-label="Previous month" onClick={() => go(-1)}>‹</button>
        <h2 id="calendar-month-label">{monthLabel(cursor.year, cursor.month)}</h2>
        <button type="button" className="secondary" aria-label="Next month" onClick={() => go(1)}>›</button>
        <button type="button" className="secondary" onClick={goToday}>Today</button>
      </div>
      <table className="month-grid" role="grid" aria-labelledby="calendar-month-label">
        <thead><tr>{WEEKDAY_LABELS.map(w => <th key={w.short} scope="col" abbr={w.long}>{w.short}</th>)}</tr></thead>
        <tbody>
          {calendar.weeks.map((week, index) => <tr key={index}>
            {week.map(day => {
              const classes = ['calendar-cell']
              if (!day.inCurrentMonth) classes.push('outside-month')
              if (day.isToday) classes.push('is-today')
              if (day.date === selectedCell?.date) classes.push('is-selected')
              return <td key={day.date}>
                <button type="button" className={classes.join(' ')} aria-current={day.isToday ? 'date' : undefined}
                  aria-pressed={day.date === selectedCell?.date} aria-label={dayAriaLabel(day)} onClick={() => selectDay(day)}>
                  <span className="day-number">{dayNumber(day.date)}</span>
                  <span className="day-chips">
                    {day.events.slice(0, 2).map(e => <span key={e.event.id} className="chip chip-event">{e.event.title}</span>)}
                    {day.proposedDates.slice(0, 2).map(p => <span key={p.interpretationId} className="chip chip-proposed">{p.summary}</span>)}
                    {(day.events.length + day.proposedDates.length) > 2 &&
                      <span className="chip chip-more">+{day.events.length + day.proposedDates.length - 2}</span>}
                  </span>
                </button>
              </td>
            })}
          </tr>)}
        </tbody>
      </table>
    </div>

    <section className="calendar-detail" aria-live="polite">
      <h3>{selectedCell ? dayHeading(selectedCell.date) : 'Select a day'}{selectedCell?.isToday && ' · Today'}</h3>
      <div className="detail-group">
        <p className="section-label">Events</p>
        {selectedCell && selectedCell.events.length ? <ul className="detail-list">
          {selectedCell.events.map(({ event: e, linkedObjects }) => <li key={e.id} className="detail-card">
            <strong>{e.title}</strong><small>{time(e.startsAt)} · {e.temporalContext}</small>
            {linkedObjects.length > 0 && <div className="detail-links">
              {linkedObjects.map(o => <button type="button" key={o.id} className="quiet-button" onClick={() => onOpen(o.id)}>
                {objectLabels[o.kind]}: {o.summary} →
              </button>)}
            </div>}
          </li>)}
        </ul> : <p className="empty-inline">No scheduled events on this day.</p>}
      </div>
      <div className="detail-group">
        <p className="section-label">Proposed dates — unconfirmed</p>
        {selectedCell && selectedCell.proposedDates.length ? <ul className="detail-list">
          {selectedCell.proposedDates.map(p => <li key={p.interpretationId} className="detail-card proposed">
            <button type="button" className="quiet-button" onClick={() => onOpen(p.objectId)}>
              {objectLabels[p.kind]}: {p.summary} →
            </button>
            <small>Not a scheduled time — open the object to confirm or change it.</small>
          </li>)}
        </ul> : <p className="empty-inline">No proposed dates on this day.</p>}
      </div>
    </section>

    <section className="list-section">
      <div className="section-heading"><div><p className="section-label">Not tied to a day</p><h2>Unscheduled commitments</h2></div>
        <span>{calendar.unscheduledCommitments.length} shown</span></div>
      {calendar.unscheduledCommitments.length ? <ul className="detail-list">
        {calendar.unscheduledCommitments.map(o => <li key={o.id}>
          <button type="button" className="commitment-row clickable-row" onClick={() => onOpen(o.id)}>
            <span className="time-dot" /><div><strong>{o.summary}</strong><small>No linked CalendarEvent — this promise has no fixed time yet.</small></div>
            <span className="kind-chip">{objectLabels[o.kind]}</span>
          </button>
        </li>)}
      </ul> : <div className="empty">No unscheduled commitments. Confirmed obligations without a linked event will appear here.</div>}
    </section>
  </div>
}
