import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, PersistedState, TemporalDecision, TemporalTarget } from './domain'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject, reverseObject, updateObject } from './objectWorkflow'
import { loadStateResult, makeObject, saveState } from './store'
import { buildMorningDigest } from './morningDigest'
import { activeTemporalDecisions, deadlineProposal, eventProposal, recordTemporalDecision } from './temporalConfirmation'

function fixture(kind: 'action' | 'commitment' = 'commitment') {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-14T12:00:00Z'))
  const item = makeObject({ kind, source: 'text', originalContent: 'Deliver draft September 15', confidence: .98,
    interpretation: { suggestedKind: kind, summary: 'Deliver draft', rationale: 'test', suggestedDate: '2026-09-15' } })
  const state = legacyUiProjection(migrateLegacyState({ objects: [item], canvas: [] }))
  state.objects[0] = confirmObject(state.objects[0])
  return legacyUiProjection(reconcileLegacyUi(state))
}
function withEvent(state: AppState) {
  const model = reconcileLegacyUi(state)
  model.calendarEvents.push({ id: 'meeting', title: 'Draft discussion', startsAt: '2026-09-14T12:00:00Z', temporalContext: 'UTC',
    captureIds: [model.captures[0].id], objectIds: [state.objects[0].id], status: 'scheduled' })
  return legacyUiProjection(model)
}
function confirm(state: AppState, event = false) {
  const model = reconcileLegacyUi(state)
  const target = event ? eventProposal(model, 'meeting')! : deadlineProposal(model, state.objects[0].id)!
  return recordTemporalDecision(state, model, target)
}
function reverse(state: AppState, index = 0) {
  const model = reconcileLegacyUi(state)
  const entry = activeTemporalDecisions(model)[index]
  return recordTemporalDecision(state, model, entry.target, entry)
}
const digest = (state: AppState) => buildMorningDigest(reconcileLegacyUi(state), new Date('2026-09-14T12:00:00Z'))
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('dedicated temporal confirmation', () => {
  it.each(['action', 'commitment'] as const)('%s confirmation and date/status strings never confirm timing', kind => {
    const state = withEvent(fixture(kind))
    expect(digest(state).upcoming).toEqual([])
    expect(digest(state).fixedToday).toEqual([])
    const deadline = confirm(state)
    expect(digest(deadline).upcoming).toHaveLength(1)
    expect(digest(deadline).fixedToday).toEqual([])
    const event = confirm(state, true)
    expect(digest(event).fixedToday).toHaveLength(1)
    expect(digest(event).upcoming).toEqual([])
  })
  it('reverses each fact independently, preserves source and interpretation history, and permits reconfirmation', () => {
    const initial = withEvent(fixture())
    const both = confirm(confirm(initial), true)
    expect(digest(both).unscheduledCommitments).toEqual([])
    const deadlineReversed = reverse(both)
    expect(digest(deadlineReversed).upcoming).toEqual([])
    expect(digest(deadlineReversed).fixedToday).toHaveLength(1)
    const reversed = reverse(deadlineReversed)
    expect(digest(reversed).fixedToday).toEqual([])
    expect(digest(reversed).unscheduledCommitments).toHaveLength(1)
    const model = reconcileLegacyUi(reversed)
    expect(model.captures).toEqual(initial.model!.captures)
    expect(model.interpretations).toEqual(initial.model!.interpretations)
    expect(model.temporalHistory).toHaveLength(4)
    expect(digest(confirm(reversed)).upcoming).toHaveLength(1)
  })
  it('preserves independent scheduling when the obligation is reversed', () => {
    const state = confirm(confirm(withEvent(fixture())), true)
    state.objects[0] = reverseObject(state.objects[0])
    expect(digest(state).upcoming).toEqual([])
    expect(digest(state).fixedToday).toHaveLength(1)
    expect(digest(state).fixedToday[0].commitments).toEqual([])
  })
  it('generic edits cannot confirm timing; a changed deadline invalidates old authority even if restored', () => {
    let state = confirm(fixture())
    state.objects[0] = updateObject(state.objects[0], { ...state.objects[0], context: 'work' })
    expect(digest(state).upcoming).toHaveLength(1)
    state = legacyUiProjection(reconcileLegacyUi(state))
    state.objects[0] = updateObject(state.objects[0], { ...state.objects[0], metadata: { deadline: '2026-09-16' } })
    expect(digest(state).upcoming).toEqual([])
    state = legacyUiProjection(reconcileLegacyUi(state))
    state.objects[0] = updateObject(state.objects[0], { ...state.objects[0], metadata: { deadline: '2026-09-15' } })
    expect(digest(state).upcoming).toEqual([])
    state = confirm(reverse(state))
    expect(digest(state).upcoming).toHaveLength(1)
  })
  it('rejects malformed, forged, mismatched, duplicate and orphan evidence', () => {
    const original = reconcileLegacyUi(confirm(confirm(withEvent(fixture())), true))
    const mutations: ((m: PersistedState) => void)[] = [
      m => { m.temporalHistory![0].source = 'review-confirmation' as TemporalDecision['source'] },
      m => { m.temporalHistory![0].at = 'yesterday' },
      m => { m.temporalHistory![0].at = '2026-02-30T12:00:00Z' },
      m => { m.temporalHistory![0].at = '2025-09-14T12:00:00Z' },
      m => { m.temporalHistory![0].target.interpretationId = 'missing' },
      m => { Object.assign(m.temporalHistory![0].target, { objectId: 'different' }) },
      m => { Object.assign(m.temporalHistory![0].target, { date: '2026-09-16' }) },
      m => { Object.assign(m.temporalHistory![1].target, { eventId: 'other' }) },
      m => { Object.assign(m.temporalHistory![1].target, { startsAt: '2026-09-14T13:00:00Z' }) },
      m => { Object.assign(m.temporalHistory![1].target, { temporalContext: 'Other zone' }) },
      m => { Object.assign(m.temporalHistory![1].target, { objectIds: [] }) },
      m => { Object.assign(m.temporalHistory![1].target, { captureIds: [] }) },
      m => { m.temporalHistory!.push(structuredClone(m.temporalHistory![0])) },
      m => { m.temporalHistory![0].decision = 'reversed'; m.temporalHistory![0].reverses = 'missing' },
      m => { m.temporalHistory![0].target = { kind: 'fixed-deadline' } as TemporalTarget },
    ]
    for (const mutate of mutations) {
      const model = structuredClone(original); mutate(model)
      expect(isPersistedState(model)).toBe(false)
      expect(buildMorningDigest(model).fixedToday).toEqual([])
      expect(buildMorningDigest(model).upcoming).toEqual([])
    }
  })
  it('does not infer events from dates or empty capture evidence and rejects stale UI proposals', () => {
    const state = fixture()
    const model = reconcileLegacyUi(state)
    expect(model.calendarEvents).toEqual([])
    const old = deadlineProposal(model, state.objects[0].id)!
    state.objects[0] = updateObject(state.objects[0], { ...state.objects[0], metadata: { deadline: '2026-09-16' } })
    expect(() => recordTemporalDecision(state, reconcileLegacyUi(state), old)).toThrow()
    const eventState = withEvent(state)
    eventState.model!.calendarEvents[0].captureIds = []
    expect(eventProposal(eventState.model!, 'meeting')).toBeUndefined()
  })
  it('round-trips confirmation/reversal and protects session history, concurrent saves and corrupted data', () => {
    let raw: string | null = JSON.stringify(withEvent(fixture()).model)
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let state = confirm(confirm(loadStateResult().state), true)
    expect(saveState(state)).toBeUndefined()
    expect(digest(loadStateResult().state).fixedToday).toHaveLength(1)
    expect(saveState(state)).toBeUndefined()
    state = reverse(loadStateResult().state)
    expect(saveState(state)).toBeUndefined()
    expect(digest(loadStateResult().state).upcoming).toEqual([])
    const saved = raw
    state.temporalHistory = []
    expect(saveState(state)).toBeTruthy()
    expect(raw).toBe(saved)
    const corrupt = JSON.parse(raw!); corrupt.temporalHistory[0].target.date = '2026-09-30'
    raw = JSON.stringify(corrupt)
    expect(loadStateResult().error).toContain('left untouched')
    expect(saveState(state)).toContain('Stored data changed')
  })
  it('matches verified event instants to the device-local day and excludes cancelled events', () => {
    const state = withEvent(fixture())
    const midnight = new Date(2026, 8, 14, 0, 5)
    state.model!.calendarEvents[0].startsAt = midnight.toISOString()
    const model = reconcileLegacyUi(confirm(state, true))
    expect(buildMorningDigest(model, midnight).fixedToday).toHaveLength(1)
    expect(buildMorningDigest(model, new Date(2026, 8, 13, 23, 59)).fixedToday).toEqual([])
    model.calendarEvents[0].status = 'cancelled'
    expect(isPersistedState(model)).toBe(true)
    expect(buildMorningDigest(model, midnight).fixedToday).toEqual([])
  })
  it('can confirm an independent existing event without confirming its proposed Action', () => {
    const state = withEvent(fixture('action'))
    state.objects[0] = reverseObject(state.objects[0])
    state.model!.calendarEvents[0].objectIds = []
    const confirmed = confirm(state, true)
    expect(digest(confirmed).fixedToday).toHaveLength(1)
    expect(digest(confirmed).recommended).toEqual([])
    expect(digest(confirmed).fixedToday[0].commitments).toEqual([])
  })
  it('rejects retargeted reversals and preserves ordinary legacy state without fabricated temporal history', () => {
    const state = confirm(confirm(withEvent(fixture())), true)
    const model = reconcileLegacyUi(reverse(state))
    model.temporalHistory![2].target = model.temporalHistory![1].target
    expect(isPersistedState(model)).toBe(false)
    const legacy = fixture()
    expect(legacy.model!.temporalHistory).toBeUndefined()
    expect(isPersistedState(legacy.model)).toBe(true)
    expect(digest(legacy).upcoming).toEqual([])
  })
  it('retries failed saves without losing pending temporal evidence', () => {
    let raw = JSON.stringify(fixture().model)
    let fail = true
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { if (fail) throw Error('quota'); raw = value } })
    const state = confirm(loadStateResult().state)
    expect(saveState(state)).toBeTruthy()
    expect(digest(state).upcoming).toHaveLength(1)
    fail = false
    expect(saveState(state)).toBeUndefined()
    expect(digest(loadStateResult().state).upcoming).toHaveLength(1)
  })
})
