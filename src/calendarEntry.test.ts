import { afterEach, describe, expect, it, vi } from 'vitest'
import { confirmCommitmentDeadline, createDirectCalendarEvent, scheduleCommitment } from './calendarEntry'
import { resolveCommitment } from './commitmentWorkflow'
import type { ThoughtObject } from './domain'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { activeTemporalDecisions, recordTemporalDecision } from './temporalConfirmation'
import { buildMorningDigest } from './morningDigest'
import { buildCalendarMonth } from './calendar'
import { loadStateResult, saveState } from './store'
import { accountData, mergeAccountData, validateData } from './accountStorage'
import { defaultSettings } from './settings'

const review: ThoughtObject = { id: 'commitment', kind: 'commitment', status: 'review', originalContent: 'Send contract', source: 'text', createdAt: '2026-10-01T08:00:00.000Z', confidence: .7, interpretation: { summary: 'Send contract', suggestedKind: 'commitment', rationale: 'Promise' }, metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }] }
const prepared = () => {
  const baseline = legacyUiProjection(migrateLegacyState({ objects: [review], canvas: [] }))
  return { ...baseline, objects: [resolveCommitment(baseline.objects[0], { title: 'Send contract', date: '2026-10-02', time: '09:30', dependencyIds: [] })] }
}
afterEach(() => vi.unstubAllGlobals())

describe('Commitment calendar confirmations', () => {
  const loadedCommitment = () => {
    let raw: string | null = JSON.stringify(migrateLegacyState({ objects: [review], canvas: [] }))
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const loaded = loadStateResult().state
    expect(saveState({ ...loaded, objects: [resolveCommitment(loaded.objects[0], { title: 'Send contract', date: '2026-10-02', time: '09:30', dependencyIds: [] })] })).toBeUndefined()
    return loadStateResult().state
  }

  it('loads, confirms a deadline, saves and reloads its exact temporal evidence', () => {
    const loaded = loadedCommitment()
    const confirmed = confirmCommitmentDeadline(loaded, 'commitment')
    expect(isPersistedState(confirmed.model)).toBe(true)
    expect(saveState(confirmed)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(reloaded.state.model?.temporalHistory).toMatchObject([{ target: { kind: 'fixed-deadline', objectId: 'commitment' } }])
    expect(reloaded.state.model?.calendarEvents).toEqual([])
  })

  it('loads, schedules a Commitment, saves and reloads its CalendarEvent', () => {
    const loaded = loadedCommitment()
    const scheduled = scheduleCommitment(loaded, 'commitment', 'UTC')
    expect(isPersistedState(scheduled.model)).toBe(true)
    expect(saveState(scheduled)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(reloaded.state.model?.calendarEvents).toMatchObject([{ objectIds: ['commitment'], status: 'scheduled' }])
    expect(reloaded.state.model?.temporalHistory).toMatchObject([{ target: { kind: 'event-scheduling' } }])
  })

  it('keeps deadline and CalendarEvent confirmations distinct and rejects invalid or repeated paths', () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('deadline').mockReturnValueOnce('event').mockReturnValueOnce('event-confirmation') })
    const state = prepared()
    const deadline = confirmCommitmentDeadline(state, 'commitment')
    expect(deadline.temporalHistory).toMatchObject([{ target: { kind: 'fixed-deadline', objectId: 'commitment', date: '2026-10-02' } }])
    expect(deadline.model?.calendarEvents).toEqual([])
    expect(() => confirmCommitmentDeadline(deadline, 'commitment')).toThrow('already confirmed')
    const scheduled = scheduleCommitment(deadline, 'commitment', 'America/Kentucky/Louisville')
    expect(reconcileLegacyUi(scheduled).calendarEvents).toMatchObject([{ id: 'event', objectIds: ['commitment'], status: 'scheduled' }])
    expect(scheduled.temporalHistory?.map(entry => entry.target.kind)).toEqual(['fixed-deadline', 'event-scheduling'])
    expect(() => scheduleCommitment(scheduled, 'commitment')).toThrow('already has a CalendarEvent')
    vi.unstubAllGlobals()
  })

  it('fails safely when scheduling has no valid saved date and time', () => {
    const baseline = legacyUiProjection(migrateLegacyState({ objects: [review], canvas: [] }))
    const noTime = { ...baseline, objects: [resolveCommitment(baseline.objects[0], { title: 'Send contract', date: '2026-10-02', dependencyIds: [] })] }
    expect(() => scheduleCommitment(noTime, 'commitment')).toThrow('both a date and time')
    expect(() => confirmCommitmentDeadline(noTime, 'missing')).toThrow('no longer available')
  })
})

describe('direct Calendar event entry', () => {
  const empty = () => legacyUiProjection(migrateLegacyState({ objects: [], canvas: [] }))

  it('creates one independent event with exact temporal audit, Calendar and digest visibility', () => {
    const state = createDirectCalendarEvent(empty(), { title: '  Dentist  ', date: '2026-10-14', time: '09:30' })
    const model = reconcileLegacyUi(state)
    expect(isPersistedState(model)).toBe(true)
    expect(model.captures).toEqual([])
    expect(model.interpretations).toEqual([])
    expect(model.semanticObjects).toEqual([])
    expect(model.calendarEvents).toMatchObject([{ title: 'Dentist', objectIds: [], captureIds: [], status: 'scheduled', origin: 'calendar-direct-entry' }])
    const decision = model.temporalHistory![0]
    expect(decision).toMatchObject({ source: 'calendar-direct-confirmation', decision: 'confirmed', target: {
      kind: 'direct-calendar-event', title: 'Dentist', temporalContext: Intl.DateTimeFormat().resolvedOptions().timeZone || 'local', eventId: model.calendarEvents[0].id,
    } })
    expect(model.calendarEvents[0].startsAt).toBe(new Date(2026, 9, 14, 9, 30).toISOString())
    const eventReady = (event: { id: string }) => event.id === model.calendarEvents[0].id && activeTemporalDecisions(model).some(entry =>
      entry.target.kind === 'direct-calendar-event' && entry.target.eventId === event.id)
    expect(buildCalendarMonth(model, 2026, 9, new Date(2026, 9, 14), eventReady).weeks.flat().find(day => day.date === '2026-10-14')?.events).toHaveLength(1)
    expect(buildMorningDigest(model, new Date(2026, 9, 14, 12)).fixedToday).toHaveLength(1)
  })

  it('round-trips through local save/reload and account snapshot without inventing a Commitment', () => {
    let raw: string | null = JSON.stringify(empty().model)
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const before = loadStateResult().state
    const created = createDirectCalendarEvent(before, { title: 'Coffee', date: '2026-10-14', time: '10:00' })
    expect(saveState(created)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(reloaded.state.objects).toEqual([])
    expect(reloaded.state.model?.calendarEvents).toMatchObject([{ title: 'Coffee', origin: 'calendar-direct-entry' }])
    const account = accountData(reloaded.state, defaultSettings, { enabled: false })
    expect(validateData(structuredClone(account))).toEqual(account)
    const accountLoaded = legacyUiProjection(account.model)
    expect(reconcileLegacyUi(accountLoaded).calendarEvents).toEqual(reloaded.state.model!.calendarEvents)
    expect(accountLoaded.objects).toEqual([])
    const merged = mergeAccountData(accountData(empty(), defaultSettings, { enabled: false }), account,
      { settings: 'account', digest: 'account' })
    expect(merged.data.model.calendarEvents).toEqual(account.model.calendarEvents)
    expect(merged.data.model.temporalHistory).toEqual(account.model.temporalHistory)
  })

  it('rejects malformed input or unaudited/tampered events and preserves reversal history', () => {
    for (const input of [
      { title: ' ', date: '2026-10-14', time: '09:30' },
      { title: 'Dentist', date: '2026-02-30', time: '09:30' },
      { title: 'Dentist', date: '2026-10-14', time: '24:00' },
      { title: 'Dentist', date: '2026-10-14', time: '' },
    ]) expect(() => createDirectCalendarEvent(empty(), input)).toThrow()
    const created = createDirectCalendarEvent(empty(), { title: 'Dentist', date: '2026-10-14', time: '09:30' })
    const model = reconcileLegacyUi(created)
    const forged = structuredClone(model)
    forged.calendarEvents[0].title = 'Forged title'
    expect(isPersistedState(forged)).toBe(false)
    const unaudited = structuredClone(model)
    unaudited.temporalHistory = []
    expect(isPersistedState(unaudited)).toBe(false)
    const confirmation = activeTemporalDecisions(model)[0]
    const reversed = recordTemporalDecision(created, model, confirmation.target, confirmation)
    const cancelled = reconcileLegacyUi(reversed)
    expect(cancelled.calendarEvents[0].status).toBe('cancelled')
    expect(cancelled.temporalHistory).toHaveLength(2)
    expect(buildMorningDigest(cancelled, new Date(2026, 9, 14, 12)).fixedToday).toEqual([])
  })
})
