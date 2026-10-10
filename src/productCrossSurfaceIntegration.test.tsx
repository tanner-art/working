import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Today } from './App'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { CalendarView } from './CalendarView'
import { scheduleCommitment } from './calendarEntry'
import { resolveCommitment } from './commitmentWorkflow'
import type { AppState, PersistedState, ThoughtObject } from './domain'
import { GlobalSearchView } from './GlobalSearchView'
import { migrateLegacyState } from './migration'
import { updateObject } from './objectWorkflow'
import { defaultSettings } from './settings'
import { loadStateResult, reconcileCurrentSession, saveState } from './store'
import { searchProjectionFromAppState, type SearchDocument } from './universalSearch'
import { performWorkspaceNavigation, type SearchDestination } from './workspaceNavigation'

const digest = { enabled: false }
const now = new Date(2026, 9, 10, 0, 10)
const review: ThoughtObject = {
  id: 'dentist', kind: 'commitment', status: 'review', originalContent: 'Dentist appointment', source: 'text',
  createdAt: '2026-10-01T08:00:00.000Z', confidence: 1,
  interpretation: { summary: 'Dentist appointment', suggestedKind: 'commitment', rationale: 'Appointment' },
  metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }],
}
const resolve = (state: AppState): AppState => ({ ...state, objects: [resolveCommitment(state.objects[0], {
  title: 'Dentist appointment', date: '2026-10-10', time: '00:05', dependencyIds: [],
})] })
const edit = (state: AppState): AppState => ({ ...state, objects: [updateObject(state.objects[0], {
  ...state.objects[0], context: 'Bring insurance card',
})] })
const documentFor = (state: AppState, readModel: (state: AppState) => PersistedState): SearchDocument => {
  const projection = searchProjectionFromAppState(state, readModel)
  expect(projection.complete).toBe(true)
  return projection.documents.find(document => document.kind === 'commitment' && document.id === 'dentist')!
}

function expectCrossSurface(state: AppState, readModel: (state: AppState) => PersistedState, prior: SearchDocument,
  account?: { userId: string }) {
  const model = readModel(state)
  const event = model.calendarEvents?.find(item => item.objectIds.includes('dentist'))
  expect(event).toMatchObject({ status: 'scheduled', objectIds: ['dentist'] })
  expect(event?.startsAt).toBe(new Date(2026, 9, 10, 0, 5).toISOString())
  expect(event?.temporalContext).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone)
  expect(model.temporalHistory?.at(-1)?.target).toMatchObject({ kind: 'event-scheduling', eventId: event?.id,
    interpretationId: model.interpretations.at(-1)?.id })
  const calendar = renderToStaticMarkup(<CalendarView state={state} onOpen={() => undefined}
    onUpdate={() => undefined} readAccountModel={account ? readModel : undefined} />)
  expect(calendar).toContain('chip chip-event">Dentist appointment')
  expect(calendar).toContain('0 shown')
  const today = renderToStaticMarkup(<Today state={state} now={now} onCapture={() => undefined}
    onOpen={() => undefined} readAccountModel={account ? readModel : undefined} />)
  expect(today).toContain('1 scheduled')
  expect(today).toContain('Dentist appointment')
  expect(today).toContain('12:05 AM')
  const otherDay = (date: Date) => renderToStaticMarkup(<Today state={state} now={date}
    onCapture={() => undefined} onOpen={() => undefined} readAccountModel={account ? readModel : undefined} />)
  expect(otherDay(new Date(2026, 9, 9, 23, 59))).toContain('0 scheduled')
  expect(otherDay(new Date(2026, 9, 11, 0, 10))).toContain('0 scheduled')
  const current = documentFor(state, readModel)
  expect(current.interpretationIds).toEqual(model.semanticObjects.find(item => item.id === 'dentist')?.interpretationIds)
  expect(current.interpretationIds).toHaveLength(4)
  expect(prior.interpretationIds).toHaveLength(3)
  const search = renderToStaticMarkup(<GlobalSearchView state={state} readModel={readModel} snapshotToken="same-token"
    navigate={() => ({ ok: true })} initialQuery="Dentist" />)
  expect(search).toContain('Open Commitment')
  expect(search).not.toContain('Some items could not be indexed')
  const opened: SearchDestination[] = []
  const context = { state, snapshotToken: 'same-token', stateIsCurrent: true, available: true, readModel,
    ...(account ? { accountUserId: account.userId, authenticatedUserId: account.userId } : {}) }
  const host = { open: (destination: SearchDestination) => opened.push(destination), close: () => undefined }
  expect(performWorkspaceNavigation({ type: 'open-search-result', document: prior, snapshotToken: 'same-token' }, context, host).ok).toBe(false)
  expect(opened).toEqual([])
  expect(performWorkspaceNavigation({ type: 'open-search-result', document: current, snapshotToken: 'same-token' }, context, host)).toEqual({ ok: true })
  expect(opened).toEqual([{ view: 'calendar', objectId: 'dentist' }])
  if (account) {
    expect(performWorkspaceNavigation({ type: 'open-search-result', document: current, snapshotToken: 'same-token' },
      { ...context, authenticatedUserId: 'different-user' }, host).ok).toBe(false)
    expect(opened).toHaveLength(1)
  }
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('bounded Commitment projection and navigation-contract evidence (not mounted UI)', () => {
  it('projects a locally saved, no-reload Commitment into Calendar, Today, and Search and rejects an old result', () => {
    vi.useFakeTimers(); vi.setSystemTime(now)
    let raw: string | null = JSON.stringify(migrateLegacyState({ objects: [review], canvas: [] }))
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let state = resolve(loadStateResult().state)
    expect(saveState(state)).toBeUndefined()
    state = edit(state)
    expect(saveState(state)).toBeUndefined()
    const prior = documentFor(state, reconcileCurrentSession)
    state = scheduleCommitment(state, 'dentist')
    expect(saveState(state)).toBeUndefined()
    const saved = raw
    expectCrossSurface(state, reconcileCurrentSession, prior)
    expect(raw).toBe(saved) // Search and navigation do not rewrite the saved workspace.
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(reloaded.state.model?.interpretations.map(item => item.version)).toEqual([1, 2, 3, 4])
    expect(reloaded.state.model?.calendarEvents?.[0].objectIds).toEqual(['dentist'])
  })

  it('projects an account-saved, no-reload Commitment into Calendar, Today, and Search and refuses cross-account navigation', async () => {
    vi.useFakeTimers(); vi.setSystemTime(now)
    let row: AccountRow | null = null
    const adapter: AccountAdapter = {
      read: async () => row && structuredClone(row),
      write: async (userId, data, revision) => {
        if (row ? row.revision !== revision : revision !== null) throw Error('conflict')
        row = { user_id: userId, revision: crypto.randomUUID(), data: structuredClone(data) }
        return structuredClone(row)
      },
    }
    const session = createAccountSession(adapter, 'owner', () => 'owner')
    const readModel = (state: AppState) => session.snapshot(state, defaultSettings, digest).model
    const save = (state: AppState) => session.save(session.snapshot(state, defaultSettings, digest))
    let state = resolve((await session.open(accountData({ objects: [review], canvas: [] }, defaultSettings, digest))).state)
    await save(state)
    state = edit(state)
    await save(state)
    const prior = documentFor(state, readModel)
    state = scheduleCommitment(state, 'dentist', undefined, session.decisionModel(state, defaultSettings, digest))
    await save(state)
    expectCrossSurface(state, readModel, prior, { userId: 'owner' })
    const reopened = await createAccountSession(adapter, 'owner', () => 'owner').open()
    expect(reopened.data.model.interpretations.map(item => item.version)).toEqual([1, 2, 3, 4])
    expect(reopened.data.model.calendarEvents?.[0].objectIds).toEqual(['dentist'])
  })
})
