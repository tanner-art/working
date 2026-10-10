import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Today } from './App'
import { accountData, validateData } from './accountStorage'
import { confirmCommitmentDeadline, createDirectCalendarEvent, scheduleCommitment } from './calendarEntry'
import { resolveCommitment } from './commitmentWorkflow'
import type { AppState, ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { defaultSettings } from './settings'
import { loadStateResult, saveState } from './store'

const review: ThoughtObject = {
  id: 'dentist', kind: 'commitment', status: 'review', originalContent: 'Dentist appointment', source: 'text',
  createdAt: '2026-10-01T08:00:00.000Z', confidence: .7,
  interpretation: { summary: 'Dentist appointment', suggestedKind: 'commitment', rationale: 'Appointment' },
  metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }],
}
const renderToday = (state: AppState, now: Date, readAccountModel?: Parameters<typeof Today>[0]['readAccountModel']) =>
  renderToStaticMarkup(<Today state={state} now={now} onCapture={() => undefined} onOpen={() => undefined} readAccountModel={readAccountModel} />)

function preparedLocal() {
  let raw: string | null = JSON.stringify(migrateLegacyState({ objects: [review], canvas: [] }))
  vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
  const loaded = loadStateResult().state
  const commitment = resolveCommitment(loaded.objects[0], { title: 'Dentist appointment', date: '2026-10-02', time: '00:05', dependencyIds: [] })
  expect(saveState({ ...loaded, objects: [commitment] })).toBeUndefined()
  return loadStateResult().state
}

afterEach(() => vi.unstubAllGlobals())

describe('reachable Today fixed commitments', () => {
  it('does not turn a confirmed unscheduled obligation into a fixed calendar entry', () => {
    const html = renderToday(confirmCommitmentDeadline(preparedLocal(), 'dentist'), new Date(2026, 9, 2, 0, 10))
    expect(html).toContain('0 scheduled')
    expect(html).toContain('No fixed commitments today')
    expect(html).not.toContain('00:05')
  })

  it('does not count a separately confirmed unlinked CalendarEvent as a Commitment', () => {
    const state = createDirectCalendarEvent(preparedLocal(), { title: 'Early meeting', date: '2026-10-02', time: '00:05' })
    const html = renderToday(state, new Date(2026, 9, 2, 0, 10))
    expect(html).toContain('0 scheduled')
    expect(html).not.toContain('Early meeting')
  })

  it('shows a provenance-confirmed scheduled Commitment after local save/reload only on its local day', () => {
    const scheduled = scheduleCommitment(preparedLocal(), 'dentist')
    expect(saveState(scheduled)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    const yesterday = renderToday(reloaded.state, new Date(2026, 9, 1, 23, 59))
    const today = renderToday(reloaded.state, new Date(2026, 9, 2, 0, 10))
    const tomorrow = renderToday(reloaded.state, new Date(2026, 9, 3, 0, 0))
    expect(yesterday).toContain('0 scheduled')
    expect(today).toContain('1 scheduled')
    expect(today).toContain('Dentist appointment')
    expect(today).toContain('12:05 AM')
    expect(today).not.toContain('No fixed commitments today')
    expect(tomorrow).toContain('0 scheduled')
  })

  it('shows the same confirmed event from an account snapshot and fails visibly if projection is unavailable', () => {
    const scheduled = scheduleCommitment(preparedLocal(), 'dentist')
    expect(saveState(scheduled)).toBeUndefined()
    const account = validateData(structuredClone(accountData(loadStateResult().state, defaultSettings, { enabled: false })))
    const accountState = legacyUiProjection(account.model)
    const now = new Date(2026, 9, 2, 0, 10)
    expect(renderToday(accountState, now, () => account.model)).toContain('1 scheduled')
    const unavailable = renderToday(accountState, now, () => { throw Error('account snapshot unavailable') })
    expect(unavailable).toContain('Unable to verify fixed commitments')
    expect(unavailable).not.toContain('0 scheduled')
  })
})
