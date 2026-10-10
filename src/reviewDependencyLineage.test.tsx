import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { stageAction } from './actionStaging'
import { Review } from './App'
import { CommitmentResolution } from './CommitmentResolution'
import { resolveCommitmentInState } from './commitmentWorkflow'
import type { AppState, ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { ReminderResolution } from './ReminderResolution'
import { resolveReminderInState } from './reminderWorkflow'
import { readReviewTargets } from './reviewTargets'
import { defaultSettings } from './settings'
import { loadStateResult, reconcileCurrentSession, saveState } from './store'

const at = '2026-10-10T09:00:00.000Z'
const digest = { enabled: false }
const thought = (id: string, kind: ThoughtObject['kind']): ThoughtObject => ({
  id, kind, status: 'review', originalContent: id, source: 'text', createdAt: at, confidence: .6,
  interpretation: { summary: id, suggestedKind: kind, rationale: 'Awaiting Review' },
  metadata: {}, relationships: [], history: [{ at, event: 'Captured' }],
})
const initial = () => migrateLegacyState({ objects: [thought('commitment', 'commitment'), thought('action', 'action'), thought('reminder', 'reminder')], canvas: [] })
const staged = (state: AppState): AppState => ({ ...state, objects: state.objects.map(item => item.id === 'action' ? stageAction(item) : item) })

afterEach(() => vi.unstubAllGlobals())

describe('Review target choices and Commitment validation', () => {
  it('shows a newly staged Action to Commitment and Reminder without a local reload, then persists both decisions', () => {
    let raw: string | null = JSON.stringify(initial())
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let state = loadStateResult().state
    expect(state.model!.semanticObjects).toEqual([])
    state = staged(state)
    expect(saveState(state)).toBeUndefined()
    const targets = readReviewTargets(state, reconcileCurrentSession)
    expect(targets.error).toBeUndefined()
    expect(targets.targets.map(item => item.id)).toEqual(['action'])
    expect(renderToStaticMarkup(<CommitmentResolution object={state.objects[0]} dependencies={targets.targets} onResolve={() => undefined} />)).toContain('action</label>')
    expect(renderToStaticMarkup(<ReminderResolution object={state.objects[2]} targets={targets.targets} onResolve={() => undefined} />)).toContain('value="action"')

    state = resolveCommitmentInState(state, 'commitment', { title: 'commitment', dependencyIds: ['action'] }, reconcileCurrentSession, '2026-10-10T09:01:00.000Z')
    expect(saveState(state)).toBeUndefined()
    state = resolveReminderInState(state, 'reminder', { targetId: 'action', mode: 'daily-log' }, '2026-10-10T09:02:00.000Z')
    expect(saveState(state)).toBeUndefined()
    const reloaded = loadStateResult().state.model!
    expect(reloaded.relationships).toMatchObject([{ sourceId: 'commitment', targetId: 'action', type: 'depends_on' }])
    expect(reloaded.reminderInstructions).toMatchObject([{ targetId: 'action', mode: 'daily-log' }])
    expect(reloaded.interpretations.filter(item => item.legacy.id === 'action').map(item => item.version)).toEqual([1, 2])
  })

  it('resolves the seeded proposed Commitment date with a fresh Action dependency without losing the proposal', () => {
    let raw: string | null = null
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let state = loadStateResult().state
    const proposedDate = state.objects.find(item => item.id === 'welcome-commitment')!.interpretation.suggestedDate
    expect(proposedDate).toBeDefined()
    expect(state.objects.find(item => item.id === 'welcome-commitment')!.status).toBe('review')
    state = { ...state, objects: state.objects.map(item => item.id === 'welcome-action' ? stageAction(item) : item) }
    expect(saveState(state)).toBeUndefined()
    const unaudited = { ...state, objects: state.objects.map(item => item.id === 'welcome-commitment'
      ? { ...item, interpretation: { ...item.interpretation, suggestedDate: undefined } } : item) }
    expect(() => reconcileCurrentSession(unaudited)).toThrow('invalid or ambiguous')

    state = resolveCommitmentInState(state, 'welcome-commitment',
      { title: 'Product planning block', dependencyIds: ['welcome-action'] }, reconcileCurrentSession, at)
    const current = reconcileCurrentSession(state)
    expect(current.relationships).toMatchObject([{ sourceId: 'welcome-commitment', targetId: 'welcome-action', type: 'depends_on' }])
    expect(current.calendarEvents).toEqual([])
    expect(saveState(state)).toBeUndefined()

    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    const readings = reloaded.state.model!.interpretations.filter(item => item.legacy.id === 'welcome-commitment')
    expect(readings[0].legacy.interpretation.suggestedDate).toBe(proposedDate)
    expect(readings.at(-1)!.legacy.interpretation.suggestedDate).toBeUndefined()
    expect(readings.at(-1)!.legacy.history.some(entry => entry.commitmentSetup?.source === 'review-commitment-resolution')).toBe(true)
    expect(reloaded.state.model!.calendarEvents).toEqual([])
  })

  it('uses the current account session for both choices and their decisions without reloading', async () => {
    let row: AccountRow | null = null
    const adapter: AccountAdapter = {
      read: async () => row,
      write: async (userId, data, revision) => {
        if (row ? row.revision !== revision : revision !== null) throw Error('conflict')
        row = { user_id: userId, revision: crypto.randomUUID(), data: structuredClone(data) }
        return structuredClone(row)
      },
    }
    const session = createAccountSession(adapter, 'owner', () => 'owner')
    const account = accountData(legacyUiProjection(initial()), defaultSettings, digest)
    let state = (await session.open(account)).state
    const readModel = (current: AppState) => session.snapshot(current, defaultSettings, digest).model
    const save = (current: AppState) => session.save(session.snapshot(current, defaultSettings, digest))
    expect(state.model!.semanticObjects).toEqual([])
    state = staged(state)
    await save(state)
    expect(state.model!.semanticObjects).toEqual([])
    const targets = readReviewTargets(state, readModel)
    expect(targets.targets.map(item => item.id)).toEqual(['action'])
    expect(renderToStaticMarkup(<CommitmentResolution object={state.objects[0]} dependencies={targets.targets} onResolve={() => undefined} />)).toContain('action</label>')
    expect(renderToStaticMarkup(<ReminderResolution object={state.objects[2]} targets={targets.targets} onResolve={() => undefined} />)).toContain('value="action"')

    state = resolveCommitmentInState(state, 'commitment', { title: 'commitment', dependencyIds: ['action'] }, readModel, '2026-10-10T09:01:00.000Z')
    await save(state)
    state = resolveReminderInState(state, 'reminder', { targetId: 'action', mode: 'daily-log' }, '2026-10-10T09:02:00.000Z', readModel(state))
    await save(state)
    const reloaded = (await createAccountSession(adapter, 'owner', () => 'owner').open()).state.model!
    expect(reloaded.relationships).toMatchObject([{ sourceId: 'commitment', targetId: 'action', type: 'depends_on' }])
    expect(reloaded.reminderInstructions).toMatchObject([{ targetId: 'action', mode: 'daily-log' }])
    expect(reloaded.interpretations.filter(item => item.legacy.id === 'action').map(item => item.version)).toEqual([1, 2])
  })

  it('rejects stale, self, and duplicate dependencies without mutating the state or local storage', () => {
    let raw: string | null = JSON.stringify(initial())
    const write = vi.fn((_key: string, value: string) => { raw = value })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: write })
    const state = loadStateResult().state
    const before = structuredClone(state)
    const saved = raw
    for (const ids of [['missing'], ['commitment'], ['action', 'action']]) {
      expect(() => resolveCommitmentInState(state, 'commitment', { title: 'commitment', dependencyIds: ids }, reconcileCurrentSession)).toThrow()
      expect(state).toEqual(before)
      expect(raw).toBe(saved)
      expect(write).not.toHaveBeenCalled()
    }
  })

  it('rejects a candidate projection failure before installing a Commitment into UI state', () => {
    const state = legacyUiProjection(initial())
    const before = structuredClone(state)
    const readModel = (current: AppState) => {
      if (current.objects.find(item => item.id === 'commitment')?.status === 'confirmed') throw Error('candidate projection rejected')
      return reconcileCurrentSession(current)
    }
    expect(() => resolveCommitmentInState(state, 'commitment', { title: 'commitment', dependencyIds: [] }, readModel))
      .toThrow('candidate projection rejected')
    expect(state).toEqual(before)
  })

  it('keeps Review visible and decisions fail closed when the canonical snapshot is unavailable', () => {
    const state = legacyUiProjection(initial())
    const failing = (): never => { throw Error('account snapshot unavailable') }
    const targets = readReviewTargets(state, failing)
    expect(targets.targets).toEqual([])
    expect(targets.error).toContain('unavailable')
    const markup = renderToStaticMarkup(<Review objects={state.objects} targets={targets.targets} targetsError={targets.error}
      onResolve={() => undefined} onReject={() => undefined} onOpen={() => undefined} />)
    expect(markup).toContain('role="alert"')
    expect(markup).toContain('>Commitment</button>')
    expect(markup).toContain('>Reminder</button>')
    expect(() => resolveCommitmentInState(state, 'commitment', { title: 'commitment', dependencyIds: [] }, failing)).toThrow('account snapshot unavailable')
    expect(state.model!.semanticObjects).toEqual([])
  })
})
