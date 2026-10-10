import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import type { AppState, PersistedState, ThoughtObject } from './domain'
import { GlobalSearchView } from './GlobalSearchView'
import { migrateLegacyState } from './migration'
import { confirmObject, updateObject } from './objectWorkflow'
import { defaultSettings } from './settings'
import { loadStateResult, reconcileCurrentSession, saveState } from './store'
import { searchProjectionFromAppState, type SearchDocument } from './universalSearch'
import { performWorkspaceNavigation, type SearchDestination } from './workspaceNavigation'

const digest = { enabled: false }
const idea = (): ThoughtObject => confirmObject({
  id: 'idea', kind: 'idea', status: 'review', originalContent: 'Orchid source', source: 'text',
  createdAt: '2026-10-09T08:00:00.000Z', confidence: 1,
  interpretation: { summary: 'Orchid idea', suggestedKind: 'idea', rationale: 'A thought' },
  metadata: {}, relationships: [], history: [{ at: '2026-10-09T08:00:00.000Z', event: 'Captured' }],
})
const changeContext = (state: AppState, context: string): AppState => ({ ...state,
  objects: [updateObject(state.objects[0], { ...state.objects[0], context })],
})
const ideaDocument = (state: AppState, readModel: (current: AppState) => PersistedState): SearchDocument => {
  const projection = searchProjectionFromAppState(state, readModel)
  expect(projection.complete).toBe(true)
  return projection.documents.find(document => document.kind === 'idea')!
}

afterEach(() => vi.unstubAllGlobals())

describe('Search uses the current validated workspace lineage', () => {
  it('indexes v3 after two local saves without reload and rejects the older v2 result', () => {
    let raw: string | null = JSON.stringify(migrateLegacyState({ objects: [idea()], canvas: [] }))
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let state = loadStateResult().state
    state = changeContext(state, 'A')
    expect(saveState(state)).toBeUndefined()
    const prior = ideaDocument(state, reconcileCurrentSession)
    expect(prior.interpretationIds).toHaveLength(2)
    state = changeContext(state, 'B')
    expect(saveState(state)).toBeUndefined()
    const savedRaw = raw
    const current = ideaDocument(state, reconcileCurrentSession)
    expect(reconcileCurrentSession(state).interpretations.map(item => item.version)).toEqual([1, 2, 3])
    expect(current.interpretationIds).toHaveLength(3)
    expect(current.interpretationIds).toEqual(reconcileCurrentSession(state).semanticObjects[0].interpretationIds)
    const opened: SearchDestination[] = []
    const context = { state, snapshotToken: 'same-token', stateIsCurrent: true, available: true, readModel: reconcileCurrentSession }
    expect(performWorkspaceNavigation({ type: 'open-search-result', document: prior, snapshotToken: 'same-token' }, context,
      { open: destination => opened.push(destination), close: () => undefined }).ok).toBe(false)
    expect(performWorkspaceNavigation({ type: 'open-search-result', document: current, snapshotToken: 'same-token' }, context,
      { open: destination => opened.push(destination), close: () => undefined })).toEqual({ ok: true })
    expect(opened).toEqual([{ view: 'review', objectId: 'idea' }])
    expect(raw).toBe(savedRaw)
  })

  it('indexes authoritative account v3 and revalidates against that same model before navigation', async () => {
    let row: AccountRow | null = null
    let writes = 0
    const adapter: AccountAdapter = {
      read: async () => row && structuredClone(row),
      write: async (userId, data, revision) => {
        writes++
        if (row ? row.revision !== revision : revision !== null) throw Error('conflict')
        row = { user_id: userId, revision: crypto.randomUUID(), data: structuredClone(data) }
        return structuredClone(row)
      },
    }
    const session = createAccountSession(adapter, 'owner', () => 'owner')
    const readModel = (state: AppState) => session.snapshot(state, defaultSettings, digest).model
    let state = (await session.open(accountData({ objects: [idea()], canvas: [] }, defaultSettings, digest))).state
    state = changeContext(state, 'A')
    await session.save(session.snapshot(state, defaultSettings, digest))
    const prior = ideaDocument(state, readModel)
    expect(prior.interpretationIds).toHaveLength(2)
    state = changeContext(state, 'B')
    await session.save(session.snapshot(state, defaultSettings, digest))
    const current = ideaDocument(state, readModel)
    expect(readModel(state).interpretations.map(item => item.version)).toEqual([1, 2, 3])
    expect(current.interpretationIds).toHaveLength(3)
    expect(current.interpretationIds).toEqual(readModel(state).semanticObjects[0].interpretationIds)
    const markup = renderToStaticMarkup(<GlobalSearchView state={state} readModel={readModel} snapshotToken="current"
      navigate={() => ({ ok: true })} initialQuery="Orchid" />)
    expect(markup).toContain('2 matching items')
    expect(markup).not.toContain('Some items could not be indexed')
    const opened: SearchDestination[] = []
    const context = { state, snapshotToken: 'current', stateIsCurrent: true, available: true,
      accountUserId: 'owner', authenticatedUserId: 'owner', readModel }
    const host = { open: (destination: SearchDestination) => opened.push(destination), close: () => undefined }
    expect(performWorkspaceNavigation({ type: 'open-search-result', document: prior, snapshotToken: 'current' }, context, host).ok).toBe(false)
    expect(opened).toEqual([])
    expect(performWorkspaceNavigation({ type: 'open-search-result', document: current, snapshotToken: 'current' }, context, host)).toEqual({ ok: true })
    expect(opened).toEqual([{ view: 'review', objectId: 'idea' }])
    expect(performWorkspaceNavigation({ type: 'open-search-result', document: current, snapshotToken: 'current' },
      { ...context, readModel: undefined }, host).ok).toBe(false)
    expect(performWorkspaceNavigation({ type: 'open-search-result', document: current, snapshotToken: 'current' },
      { ...context, authenticatedUserId: 'someone-else' }, host).ok).toBe(false)
    expect(opened).toHaveLength(1)
    expect(writes).toBe(3)
  })

  it('marks a failed canonical read incomplete and refuses a result without opening a destination', () => {
    const state: AppState = { objects: [idea()], canvas: [] }
    const readModel = (): PersistedState => { throw Error('source unavailable') }
    expect(searchProjectionFromAppState(state, readModel)).toEqual({ documents: [], omittedCount: 0, complete: false })
    const request = { type: 'open-search-result' as const,
      document: { kind: 'idea' as const, id: 'idea', captureIds: ['capture:idea'], interpretationIds: ['interpretation:idea:1'], fields: { 'current-meaning': 'Orchid idea' } },
      snapshotToken: 'current' }
    const opened: SearchDestination[] = []
    expect(performWorkspaceNavigation(request, { state, snapshotToken: 'current', stateIsCurrent: true, available: true, readModel },
      { open: destination => opened.push(destination), close: () => undefined }).ok).toBe(false)
    expect(opened).toEqual([])
  })
})
