import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { CalendarView } from './CalendarView'
import { stageAction } from './actionStaging'
import { confirmCommitmentDeadline } from './calendarEntry'
import { resolveCommitment } from './commitmentWorkflow'
import type { ThoughtObject } from './domain'
import { updateObject } from './objectWorkflow'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { ScheduleView } from './ScheduleView'
import { defaultSettings } from './settings'
import { TemporalReview } from './TemporalReview'

const digest = { enabled: false }
const review = (id: string): ThoughtObject => ({
  id, kind: 'commitment', status: 'review', originalContent: id, source: 'text',
  createdAt: '2026-10-01T08:00:00.000Z', confidence: .7,
  interpretation: { summary: id, suggestedKind: 'commitment', rationale: 'Promise' },
  metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }],
})

describe('account temporal decisions during in-flight saves', () => {
  it('keeps a staged Action row and its scheduling input visible while confirmation is blocked', () => {
    const action: ThoughtObject = { ...review('action'), kind: 'action', originalContent: 'Prepare launch',
      interpretation: { summary: 'Prepare launch', suggestedKind: 'action', rationale: 'Work' } }
    const state = legacyUiProjection(migrateLegacyState({ objects: [stageAction(action)], canvas: [] }))
    const html = renderToStaticMarkup(<ScheduleView state={state} update={() => undefined}
      decisionBlocked="Account changes are saving. Wait before confirming time." />)
    expect(html).toContain('Priority for Prepare launch')
    expect(html).toContain('aria-label="Schedule Prepare launch"')
    expect(html).toContain('Account changes are saving')
    expect(html).toContain('type="submit" disabled=""')
    const failedProjection = renderToStaticMarkup(<ScheduleView state={state} update={() => undefined}
      readAccountModel={() => { throw Error('stale snapshot') }} />)
    expect(failedProjection).toContain('Priority for Prepare launch')
    expect(failedProjection).toContain('Showing the last loaded Schedule')
    expect(failedProjection).toContain('type="submit" disabled=""')
  })

  it('blocks decisions until an overlapping edit is saved, then confirms against its exact interpretation', async () => {
    let row: AccountRow | null = null
    let writes = 0
    let started!: () => void
    let release!: () => void
    const writeStarted = new Promise<void>(resolve => { started = resolve })
    const heldWrite = new Promise<void>(resolve => { release = resolve })
    const adapter: AccountAdapter = {
      read: async () => row && structuredClone(row),
      write: async (userId, data, revision) => {
        const attempt = ++writes
        if (attempt === 3) { started(); await heldWrite }
        if (row ? row.revision !== revision : revision !== null) throw Error('conflict')
        row = { user_id: userId, revision: `revision-${attempt}`, data: structuredClone(data) }
        return structuredClone(row)
      },
    }
    const session = createAccountSession(adapter, 'owner', () => 'owner')
    const readModel = (state: Parameters<typeof session.decisionModel>[0]) => session.decisionModel(state, defaultSettings, digest)
    const save = (state: Parameters<typeof session.snapshot>[0], retry = false) => session.save(session.snapshot(state, defaultSettings, digest), retry)
    let state = (await session.open(accountData({ objects: [review('c1'), review('c2')], canvas: [] }, defaultSettings, digest))).state
    state = { ...state, objects: state.objects.map(item => resolveCommitment(item, {
      title: item.id, date: item.id === 'c1' ? '2026-10-12' : '2026-10-13', time: '09:30', dependencyIds: [],
    })) }
    await save(state)
    state = { ...state, objects: state.objects.map(item => item.id === 'c1'
      ? updateObject(item, { ...item, metadata: { ...item.metadata, deadline: '2026-10-14' } }) : item) }
    const firstSave = save(state)
    await writeStarted
    state = { ...state, objects: state.objects.map(item => item.id === 'c1'
      ? updateObject(item, { ...item, metadata: { ...item.metadata, deadline: '2026-10-15' } }) : item) }
    expect(() => readModel(state)).toThrow('Account changes are saving')
    expect(() => confirmCommitmentDeadline(state, 'c1', readModel(state))).toThrow('Account changes are saving')
    expect(() => confirmCommitmentDeadline(state, 'c2', readModel(state))).toThrow('Account changes are saving')
    const preview = (current: typeof state) => session.snapshot(current, defaultSettings, digest).model
    for (const view of [
      <CalendarView state={state} onOpen={() => undefined} onUpdate={() => undefined} readAccountModel={preview} readDecisionModel={readModel} decisionBlocked={session.decisionBlockReason()} />,
      <ScheduleView state={state} update={() => undefined} readAccountModel={preview} readDecisionModel={readModel} decisionBlocked={session.decisionBlockReason()} />,
      <TemporalReview state={state} onUpdate={() => undefined} readAccountModel={preview} readDecisionModel={readModel} decisionBlocked={session.decisionBlockReason()} />,
    ]) {
      const html = renderToStaticMarkup(view)
      expect(html).toContain('Account changes are saving')
      expect(html).toContain('Your edits')
    }
    const calendar = renderToStaticMarkup(<CalendarView state={state} onOpen={() => undefined} onUpdate={() => undefined} readAccountModel={preview} decisionBlocked={session.decisionBlockReason()} />)
    expect(calendar).toContain('Add event')
    expect(calendar).toContain('Unscheduled commitments')
    expect(calendar).toContain('disabled=""')
    const fallbackCalendar = renderToStaticMarkup(<CalendarView state={state} onOpen={() => undefined} onUpdate={() => undefined}
      readAccountModel={() => { throw Error('stale snapshot') }} />)
    expect(fallbackCalendar).toContain('Add event')
    expect(fallbackCalendar).toContain('Showing the last loaded Calendar')
    // The ordinary edit is still saved; only the temporal decisions wait.
    const secondSave = save(state)
    release()
    await firstSave
    await secondSave
    expect(writes).toBe(4)
    const afterEdits = structuredClone(row!.data.model.interpretations)
    expect(afterEdits.filter(entry => entry.legacy.id === 'c1').map(entry => entry.version)).toEqual([1, 2, 3, 4])
    state = confirmCommitmentDeadline(state, 'c1', readModel(state))
    state = confirmCommitmentDeadline(state, 'c2', readModel(state))
    await save(state)
    const reloaded = (await createAccountSession(adapter, 'owner', () => 'owner').open()).data.model
    expect(reloaded.interpretations).toEqual(afterEdits)
    expect(reloaded.interpretations.find(entry => entry.id === 'interpretation:c1:3')?.legacy.metadata.deadline).toBe('2026-10-14')
    expect(reloaded.interpretations.find(entry => entry.id === 'interpretation:c1:4')?.legacy.metadata.deadline).toBe('2026-10-15')
    expect(reloaded.temporalHistory?.map(entry => entry.target)).toMatchObject([
      { kind: 'fixed-deadline', objectId: 'c1', interpretationId: 'interpretation:c1:4', date: '2026-10-15' },
      { kind: 'fixed-deadline', objectId: 'c2', interpretationId: 'interpretation:c2:2', date: '2026-10-13' },
    ])
  })

  it('keeps an unsaved resolution visible and blocks timing until an explicit retry succeeds', async () => {
    let row: AccountRow | null = null
    let writes = 0
    const adapter: AccountAdapter = {
      read: async () => row && structuredClone(row),
      write: async (userId, data, revision) => {
        const attempt = ++writes
        if (attempt === 2) throw Error('storage unavailable')
        if (row ? row.revision !== revision : revision !== null) throw Error('conflict')
        row = { user_id: userId, revision: `revision-${attempt}`, data: structuredClone(data) }
        return structuredClone(row)
      },
    }
    const session = createAccountSession(adapter, 'owner', () => 'owner')
    let state = (await session.open(accountData({ objects: [review('c1')], canvas: [] }, defaultSettings, digest))).state
    state = { ...state, objects: [resolveCommitment(state.objects[0], {
      title: 'c1', date: '2026-10-15', time: '09:30', dependencyIds: [],
    })] }
    const snapshot = () => session.snapshot(state, defaultSettings, digest)
    const readModel = () => session.decisionModel(state, defaultSettings, digest)
    await expect(session.save(snapshot())).rejects.toThrow('Account changes could not be saved')
    expect(state.objects[0].status).toBe('confirmed')
    expect(() => readModel()).toThrow('Account changes are not saved')
    expect(renderToStaticMarkup(<CalendarView state={state} onOpen={() => undefined} onUpdate={() => undefined}
      readAccountModel={current => session.snapshot(current, defaultSettings, digest).model}
      readDecisionModel={readModel} decisionBlocked={session.decisionBlockReason()} />)).toContain('Retry saving or download a backup')
    await session.save(snapshot(), true)
    state = confirmCommitmentDeadline(state, 'c1', readModel())
    await session.save(snapshot())
    const reloaded = (await createAccountSession(adapter, 'owner', () => 'owner').open()).data.model
    expect(reloaded.temporalHistory?.[0].target).toMatchObject({ objectId: 'c1', date: '2026-10-15', interpretationId: 'interpretation:c1:2' })
  })
})
