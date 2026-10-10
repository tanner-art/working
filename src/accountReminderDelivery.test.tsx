import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import type { AppState, ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { ReminderProjections, reminderDeliveryFailureMessage } from './ReminderResolution'
import { resolveReminderInState, setReminderDeliveryState } from './reminderWorkflow'
import { reviseInterpretation } from './reviewRevision'
import { defaultSettings } from './settings'
import { loadStateResult, reconcileCurrentSession, saveState } from './store'

afterEach(() => vi.unstubAllGlobals())

const createdAt = '2026-10-10T08:00:00.000Z'
const digest = { enabled: false }
const thought = (id: string, kind: ThoughtObject['kind'], summary: string): ThoughtObject => ({
  id, kind, status: kind === 'idea' ? 'confirmed' : 'review', originalContent: summary, source: 'text', createdAt,
  confidence: .6, interpretation: { summary, suggestedKind: kind, rationale: 'Test evidence' },
  metadata: {}, relationships: [], history: [{ at: createdAt, event: 'Captured' }],
})

describe('account Reminder delivery lineage', () => {
  it('uses fresh local session evidence for a Reminder row after an edit without reloading', () => {
    let raw: string | null = JSON.stringify(migrateLegacyState({ objects: [
      thought('target', 'idea', 'Original target'), thought('reminder', 'reminder', 'Surface target'),
    ], canvas: [] }))
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let state = loadStateResult().state
    state = resolveReminderInState(state, 'reminder', { targetId: 'target', mode: 'daily-log' }, '2026-10-10T08:01:00.000Z')
    expect(saveState(state)).toBeUndefined()
    state = reviseInterpretation(state, 'target', 'Updated target', '2026-10-10T08:02:00.000Z')
    expect(saveState(state)).toBeUndefined()
    expect(state.model!.semanticObjects.find(item => item.id === 'target')?.summary).toBe('Original target')
    const fresh = renderToStaticMarkup(<ReminderProjections state={state} readModel={reconcileCurrentSession} onDeliveryState={() => undefined} />)
    expect(fresh).toContain('Updated target')
    expect(fresh).not.toContain('Original target')
    expect(loadStateResult().state.model?.semanticObjects.find(item => item.id === 'target')?.summary).toBe('Updated target')
  })

  it('uses fresh account evidence for rows and a no-reload handled decision after multiple saves', async () => {
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
    const initial = legacyUiProjection(migrateLegacyState({ objects: [
      thought('target', 'idea', 'Original target'), thought('reminder', 'reminder', 'Surface target'),
    ], canvas: [] }))
    let state = (await session.open(accountData(initial, defaultSettings, digest))).state
    const readModel = (current: AppState) => session.snapshot(current, defaultSettings, digest).model
    const save = (current: AppState) => session.save(session.snapshot(current, defaultSettings, digest))

    state = resolveReminderInState(state, 'reminder', { targetId: 'target', mode: 'daily-log' },
      '2026-10-10T08:01:00.000Z', readModel(state))
    await save(state)
    const beforeEdit = structuredClone(readModel(state).interpretations)
    state = reviseInterpretation(state, 'target', 'Updated target', '2026-10-10T08:02:00.000Z')
    await save(state)
    const beforeDelivery = structuredClone(readModel(state).interpretations)
    expect(beforeDelivery).toHaveLength(beforeEdit.length + 1)
    expect(beforeDelivery.slice(0, beforeEdit.length)).toEqual(beforeEdit)
    expect(state.model!.semanticObjects.find(item => item.id === 'target')?.summary).toBe('Original target')

    const stale = renderToStaticMarkup(<ReminderProjections state={state} onDeliveryState={() => undefined} />)
    expect(stale).toContain('Original target')
    const fresh = renderToStaticMarkup(<ReminderProjections state={state} readModel={readModel} onDeliveryState={() => undefined} />)
    expect(fresh).toContain('Updated target')
    expect(fresh).not.toContain('Original target')

    const instructionId = 'reminder:reminder'
    state = setReminderDeliveryState(state, instructionId, 'handled', '2026-10-10T08:03:00.000Z', readModel(state))
    await save(state)
    const reloaded = (await createAccountSession(adapter, 'owner', () => 'owner').open()).state.model!
    expect(reloaded.interpretations.slice(0, beforeDelivery.length)).toEqual(beforeDelivery)
    expect(reloaded.reminderInstructions).toMatchObject([{ id: instructionId, targetId: 'target', deliveryState: 'handled', handledAt: '2026-10-10T08:03:00.000Z' }])
    expect(reloaded.semanticObjects.find(item => item.id === 'target')?.summary).toBe('Updated target')
    expect(renderToStaticMarkup(<ReminderProjections state={state} readModel={readModel} onDeliveryState={() => undefined} />)).toContain('No active Daily log reminders.')
    const saved = structuredClone(row)
    expect(() => setReminderDeliveryState(state, instructionId, 'dismissed', '2026-10-10T08:04:00.000Z', readModel(state))).toThrow('no longer active')
    expect(readModel(state).reminderInstructions?.[0].deliveryState).toBe('handled')
    expect(row).toEqual(saved)
  })

  it('shows a degraded projection and refuses delivery when the account snapshot fails', async () => {
    let row: AccountRow | null = null
    const adapter: AccountAdapter = {
      read: async () => row,
      write: async (userId, data) => {
        row = { user_id: userId, revision: 'v1', data: structuredClone(data) }
        return structuredClone(row)
      },
    }
    const session = createAccountSession(adapter, 'owner', () => 'owner')
    const initial = legacyUiProjection(migrateLegacyState({ objects: [
      thought('target', 'idea', 'Target'), thought('reminder', 'reminder', 'Surface target'),
    ], canvas: [] }))
    let state = (await session.open(accountData(initial, defaultSettings, digest))).state
    const readModel = (current: AppState) => session.snapshot(current, defaultSettings, digest).model
    state = resolveReminderInState(state, 'reminder', { targetId: 'target', mode: 'daily-log' },
      '2026-10-10T08:01:00.000Z', readModel(state))
    await session.save(session.snapshot(state, defaultSettings, digest))
    const before = structuredClone(state)
    const saved = structuredClone(row)
    const unavailable = (): never => { throw Error('Account snapshot unavailable') }
    const markup = renderToStaticMarkup(<ReminderProjections state={state} readModel={unavailable} onDeliveryState={() => undefined} />)
    expect(markup).toContain('role="alert"')
    expect(markup).toContain('Reminders could not be verified')
    expect(markup).not.toContain('>Handled</button>')
    let current = state
    const update = (transition: (latest: AppState) => AppState) => { current = transition(current) }
    const onDelivery = () => update(latest => setReminderDeliveryState(latest, 'reminder:reminder', 'handled',
      '2026-10-10T08:02:00.000Z', unavailable()))
    expect(reminderDeliveryFailureMessage(onDelivery)).toBe('Account snapshot unavailable')
    expect(current).toEqual(before)
    expect(state).toEqual(before)
    expect(row).toEqual(saved)
  })
})
