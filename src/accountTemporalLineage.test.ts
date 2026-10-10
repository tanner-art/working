import { afterEach, describe, expect, it, vi } from 'vitest'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { scheduleStagedAction, stageAction } from './actionStaging'
import { confirmCommitmentDeadline, createDirectCalendarEvent, scheduleCommitment } from './calendarEntry'
import { resolveCommitment } from './commitmentWorkflow'
import type { AppState, ThoughtObject } from './domain'
import { reverseObject, updateObject } from './objectWorkflow'
import { defaultSettings } from './settings'

const digest = { enabled: false }
afterEach(() => vi.useRealTimers())
const commitment: ThoughtObject = {
  id: 'commitment', kind: 'commitment', status: 'review', originalContent: 'Send contract', source: 'text',
  createdAt: '2026-10-01T08:00:00.000Z', confidence: .7,
  interpretation: { summary: 'Send contract', suggestedKind: 'commitment', rationale: 'Promise' },
  metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }],
}
const action: ThoughtObject = {
  ...commitment, id: 'action', kind: 'action', originalContent: 'Draft contract',
  interpretation: { summary: 'Draft contract', suggestedKind: 'action', rationale: 'Needs doing' },
}

function accountFixture(object: ThoughtObject) {
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
  const current = () => row!.data.model
  const save = (state: AppState) => session.save(session.snapshot(state, defaultSettings, digest))
  const readModel = (state: AppState) => session.snapshot(state, defaultSettings, digest).model
  const reopen = async () => (await createAccountSession(adapter, 'owner', () => 'owner').open()).data.model
  return { session, initial: accountData({ objects: [object], canvas: [] }, defaultSettings, digest), current, save, readModel, reopen }
}

describe('account-mode Schedule and Calendar temporal lineage', () => {
  it('confirms a deadline then schedules a Commitment against the latest account interpretation', async () => {
    const fixture = accountFixture(commitment)
    let state = (await fixture.session.open(fixture.initial)).state
    state = { ...state, objects: [resolveCommitment(state.objects[0], {
      title: 'Send contract', date: '2026-10-12', time: '09:30', dependencyIds: [],
    })] }
    await fixture.save(state)
    state = { ...state, objects: [updateObject(state.objects[0], { ...state.objects[0], context: 'Client delivery' })] }
    await fixture.save(state)
    const before = structuredClone(fixture.current().interpretations)
    expect(before.map(item => item.version)).toEqual([1, 2, 3])

    state = confirmCommitmentDeadline(state, 'commitment', fixture.readModel(state))
    await fixture.save(state)
    expect(fixture.current().interpretations).toEqual(before)
    expect(fixture.current().temporalHistory?.[0].target).toMatchObject({
      kind: 'fixed-deadline', interpretationId: before.at(-1)!.id, date: '2026-10-12',
    })

    state = scheduleCommitment(state, 'commitment', 'UTC', fixture.readModel(state))
    await fixture.save(state)
    const reloaded = await fixture.reopen()
    expect(reloaded.interpretations.slice(0, before.length)).toEqual(before)
    expect(reloaded.interpretations.map(item => item.version)).toEqual([1, 2, 3, 4])
    expect(reloaded.temporalHistory?.map(item => item.target.kind)).toEqual(['fixed-deadline', 'event-scheduling'])
    expect(reloaded.temporalHistory?.[1].target).toMatchObject({ interpretationId: reloaded.interpretations.at(-1)!.id })
    expect(reloaded.calendarEvents).toMatchObject([{ objectIds: ['commitment'], status: 'scheduled' }])
    expect(reloaded.captures).toEqual(fixture.initial.model.captures)
  })

  it('schedules a staged Action against the latest account interpretation without collapsing prior saves', async () => {
    const fixture = accountFixture(action)
    let state = (await fixture.session.open(fixture.initial)).state
    state = { ...state, objects: [stageAction(state.objects[0])] }
    await fixture.save(state)
    state = { ...state, objects: [updateObject(state.objects[0], { ...state.objects[0], context: 'Contract project' })] }
    await fixture.save(state)
    const before = structuredClone(fixture.current().interpretations)
    expect(before.map(item => item.version)).toEqual([1, 2, 3])

    state = scheduleStagedAction(state, 'action', '2026-10-12T09:30:00.000Z', 'UTC', fixture.readModel(state))
    await fixture.save(state)
    const reloaded = await fixture.reopen()
    expect(reloaded.interpretations.slice(0, before.length)).toEqual(before)
    expect(reloaded.interpretations.map(item => item.version)).toEqual([1, 2, 3, 4])
    expect(reloaded.stagedActions).toMatchObject([{ objectId: 'action', status: 'scheduled' }])
    expect(reloaded.calendarEvents).toMatchObject([{ objectIds: ['action'], status: 'scheduled' }])
    expect(reloaded.temporalHistory?.[0].target).toMatchObject({ interpretationId: reloaded.interpretations.at(-1)!.id })
    expect(reloaded.captures).toEqual(fixture.initial.model.captures)
  })

  it('keeps the saved Action reversal journal when a later direct event is created without reloading', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-10T10:00:00.000Z'))
    const fixture = accountFixture(action)
    let state = (await fixture.session.open(fixture.initial)).state
    state = { ...state, objects: [stageAction(state.objects[0])] }
    await fixture.save(state)
    state = scheduleStagedAction(state, 'action', '2026-10-12T09:30:00.000Z', 'UTC', fixture.readModel(state))
    await fixture.save(state)

    vi.setSystemTime(new Date('2026-10-10T10:01:00.000Z'))
    state = { ...state, objects: [reverseObject(state.objects[0])] }
    await fixture.save(state)
    const savedReversal = structuredClone(fixture.current().temporalHistory?.at(-1))
    expect(savedReversal).toMatchObject({ decision: 'reversed', at: '2026-10-10T10:01:00.000Z' })

    vi.setSystemTime(new Date('2026-10-10T10:02:00.000Z'))
    state = { ...state, objects: [updateObject(state.objects[0], { ...state.objects[0], context: 'Archived after withdrawal' })] }
    await fixture.save(state)
    const priorInterpretations = structuredClone(fixture.current().interpretations)
    expect(state.model?.temporalHistory?.map(item => item.decision)).toEqual(['confirmed']) // loaded projection predates the saved reversal
    vi.setSystemTime(new Date('2026-10-10T10:03:00.000Z'))
    state = createDirectCalendarEvent(state, { title: 'Independent meeting', date: '2026-10-14', time: '09:30' }, fixture.readModel(state))
    await fixture.save(state)
    vi.setSystemTime(new Date('2026-10-10T10:04:00.000Z'))
    state = createDirectCalendarEvent(state, { title: 'Second meeting', date: '2026-10-15', time: '10:30' }, fixture.readModel(state))
    await fixture.save(state)

    const reloaded = await fixture.reopen()
    expect(reloaded.interpretations).toEqual(priorInterpretations)
    expect(reloaded.temporalHistory?.[1]).toEqual(savedReversal)
    expect(reloaded.temporalHistory?.map(item => item.target.kind)).toEqual(['event-scheduling', 'event-scheduling', 'direct-calendar-event', 'direct-calendar-event'])
    expect(reloaded.calendarEvents).toMatchObject([{ status: 'cancelled' },
      { title: 'Independent meeting', origin: 'calendar-direct-entry', status: 'scheduled' },
      { title: 'Second meeting', origin: 'calendar-direct-entry', status: 'scheduled' }])
  })
})
