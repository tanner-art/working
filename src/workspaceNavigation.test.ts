import { describe, expect, it } from 'vitest'
import { createCanvasRecord } from './canvasBank'
import { stageAction } from './actionStaging'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject } from './objectWorkflow'
import { resolveReminderInState, setReminderDeliveryState } from './reminderWorkflow'
import { searchDocumentsFromAppState, type SearchDocument } from './universalSearch'
import { performWorkspaceNavigation, resolveSearchDestination, type SearchDestination } from './workspaceNavigation'
import type { AppState, ThoughtObject } from './domain'

const at = '2026-10-09T00:00:00.000Z'
const thought = (id: string, kind: ThoughtObject['kind']): ThoughtObject => ({
  id, kind, originalContent: `Orchid ${kind} source`, source: 'text', createdAt: at, confidence: 1, status: 'review',
  interpretation: { summary: `Orchid ${kind}`, suggestedKind: kind, rationale: '' }, metadata: {}, history: [], relationships: [],
})
function fixture(): AppState {
  const source: AppState = { canvas: [], objects: [thought('a', 'action'), thought('c', 'commitment'), thought('i', 'idea'), thought('r', 'reminder')] }
  let state = legacyUiProjection(migrateLegacyState(source))
  state = legacyUiProjection(reconcileLegacyUi({ ...state, objects: state.objects.map(item => item.id === 'r' ? item : confirmObject(item)) }))
  state = resolveReminderInState(state, 'r', { targetId: 'i', mode: 'daily-log' })
  const canvas = { ...createCanvasRecord(at, 'canvas:orchid'), title: 'Orchid board' }
  return { ...state, canvasBank: { canvases: [canvas] } }
}
const document = (state: AppState, kind: SearchDocument['kind']) => searchDocumentsFromAppState(state).find(item => item.kind === kind)!

describe('workspace search navigation contract', () => {
  it('resolves all six identities to their real in-workspace destinations without writing state', () => {
    const state = fixture()
    const before = structuredClone(state)
    expect(resolveSearchDestination(state, document(state, 'capture'))).toEqual({ view: 'review', objectId: 'a' })
    expect(resolveSearchDestination(state, document(state, 'action'))).toEqual({ view: 'schedule', objectId: 'a' })
    expect(resolveSearchDestination(state, document(state, 'commitment'))).toEqual({ view: 'calendar', objectId: 'c' })
    expect(resolveSearchDestination(state, document(state, 'idea'))).toEqual({ view: 'review', objectId: 'i' })
    expect(resolveSearchDestination(state, document(state, 'reminder'))).toEqual({ view: 'review', reminderId: 'reminder:r' })
    expect(resolveSearchDestination(state, document(state, 'canvas'))).toEqual({ view: 'canvas', canvasId: 'canvas:orchid' })
    expect(state).toEqual(before)
  })

  it('does not follow stale, forged, deleted, or different-workspace documents', () => {
    const state = fixture()
    const idea = document(state, 'idea')
    const another = { ...state, objects: state.objects.map(item => item.id === 'i'
      ? { ...item, interpretation: { ...item.interpretation, summary: 'Cobalt idea' } } : item) }
    expect(resolveSearchDestination(another, idea)).toBeUndefined()
    expect(resolveSearchDestination(state, { ...idea, captureIds: ['capture:not-this-object'] })).toBeUndefined()
    expect(resolveSearchDestination(state, { ...idea, id: 'missing' })).toBeUndefined()
    const withoutCanvas = { ...state, canvasBank: { canvases: [] } }
    expect(resolveSearchDestination(withoutCanvas, document(state, 'canvas'))).toBeUndefined()
    expect(resolveSearchDestination({ ...state, model: undefined, objects: [] }, idea)).toBeUndefined()
  })

  it('opens an inactive reminder at its preserved source and rejects lost instruction identity', () => {
    const active = fixture()
    const reminder = document(active, 'reminder')
    const handled = setReminderDeliveryState(active, 'reminder:r', 'handled', at)
    expect(resolveSearchDestination(handled, reminder)).toEqual({ view: 'review', objectId: 'r' })
    const broken = { ...handled, model: { ...handled.model!, reminderInstructions: [] } }
    expect(resolveSearchDestination(broken, reminder)).toBeUndefined()
  })

  it('focuses a staged Action row rather than opening its generic details panel', () => {
    const staged = legacyUiProjection(migrateLegacyState({ canvas: [], objects: [stageAction(thought('a', 'action'))] }))
    expect(resolveSearchDestination(staged, document(staged, 'action'))).toEqual({ view: 'schedule', actionId: 'a' })
  })

  it('hands a current result to the host, but never hands off a stale snapshot or account', () => {
    const state = fixture()
    const calls: (SearchDestination | 'close')[] = []
    const host = { open: (destination: SearchDestination) => calls.push(destination), close: () => { calls.push('close') } }
    const context = { state, snapshotToken: 'current', stateIsCurrent: true, available: true,
      accountUserId: 'account-a', authenticatedUserId: 'account-a' }
    const result = { type: 'open-search-result' as const, document: document(state, 'idea'), snapshotToken: 'current' }
    expect(performWorkspaceNavigation(result, context, host)).toEqual({ ok: true })
    expect(calls).toEqual([{ view: 'review', objectId: 'i' }])
    calls.length = 0
    expect(performWorkspaceNavigation({ ...result, snapshotToken: 'old' }, context, host).ok).toBe(false)
    expect(performWorkspaceNavigation(result, { ...context, stateIsCurrent: false }, host).ok).toBe(false)
    expect(performWorkspaceNavigation(result, { ...context, authenticatedUserId: 'account-b' }, host).ok).toBe(false)
    expect(performWorkspaceNavigation({ ...result, document: { ...result.document, id: 'missing' } }, context, host).ok).toBe(false)
    expect(calls).toEqual([])
    expect(performWorkspaceNavigation({ type: 'close-surface' }, context, host)).toEqual({ ok: true })
    expect(calls).toEqual(['close'])
  })
})
