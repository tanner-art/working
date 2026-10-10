import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { CalendarView, canLeaveCalendarForSearch } from './CalendarView'
import { legacyUiProjection, migrateLegacyState } from './migration'

it('keeps keyboard-reachable Calendar entry and month navigation outside the day grid', () => {
  const state = legacyUiProjection(migrateLegacyState({ objects: [], canvas: [] }))
  const markup = renderToStaticMarkup(<CalendarView state={state} onOpen={() => undefined} onUpdate={() => undefined} />)
  expect(markup).toContain('aria-label="Previous month"')
  expect(markup).toContain('aria-label="Next month"')
  expect(markup).toContain('>Add event</button>')
  expect(markup).toContain('class="calendar-cell-add"')
  expect(markup).not.toContain('aria-label="Add Calendar event"')
})

it('blocks Search handoff while either Calendar entry form has a draft', () => {
  expect(canLeaveCalendarForSearch('', false)).toBe(true)
  expect(canLeaveCalendarForSearch('  ', false)).toBe(true)
  expect(canLeaveCalendarForSearch('Dentist', false)).toBe(false)
  expect(canLeaveCalendarForSearch('', true)).toBe(false)
  expect(canLeaveCalendarForSearch('Dentist', true)).toBe(false)
})
