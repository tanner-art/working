import { describe, expect, it } from 'vitest'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { scheduleStagedAction, stageAction } from './actionStaging'
import { confirmCommitmentDeadline, scheduleCommitment } from './calendarEntry'
import { resolveCommitment } from './commitmentWorkflow'
import type { AppState, ThoughtObject } from './domain'
import { updateObject } from './objectWorkflow'
import { defaultSettings } from './settings'

const digest = { enabled: false }
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
})
