import { describe, expect, it, vi } from 'vitest'
import { accountData, mergeAccountData, validateData } from './accountStorage'
import { isPersistedState, legacyUiProjection, migrateLegacyState } from './migration'
import { confirmObject, setObjectStatus } from './objectWorkflow'
import { connectThoughts, confirmedConnectionGraph, removeThoughtConnection, safeConnectionGraph } from './semanticLinks'
import { defaultSettings } from './settings'
import { loadStateResult, makeObject, saveState, serializeState } from './store'

function thoughts() {
  const first = confirmObject(makeObject({ kind: 'idea', source: 'text', originalContent: 'A garden', confidence: .9,
    interpretation: { summary: 'Garden', suggestedKind: 'idea', rationale: 'Idea' } }))
  const second = confirmObject(makeObject({ kind: 'idea', source: 'text', originalContent: 'A quiet room', confidence: .9,
    interpretation: { summary: 'Quiet room', suggestedKind: 'idea', rationale: 'Idea' } }))
  const pending = setObjectStatus(makeObject({ kind: 'idea', source: 'text', originalContent: 'Not decided', confidence: .6,
    interpretation: { summary: 'Pending', suggestedKind: 'idea', rationale: 'Idea' } }), 'review')
  first.id = 'thought:first'; second.id = 'thought:second'; pending.id = 'thought:pending'
  return { first, second, pending }
}

describe('explicit semantic connections', () => {
  it('requires two resolved endpoints and one distinct manual gesture', () => {
    const { first, second, pending } = thoughts()
    const state = legacyUiProjection(migrateLegacyState({ objects: [first, second, pending], canvas: [] }))
    expect(() => connectThoughts(state, first.id, pending.id, 'gesture:bad')).toThrow('resolved thoughts')
    expect(() => connectThoughts(state, first.id, first.id, 'gesture:self')).toThrow('resolved thoughts')
    const linked = connectThoughts(state, first.id, second.id, 'gesture:one', '2026-10-10T12:00:00.000Z')
    const model = serializeState(linked)
    expect(isPersistedState(model)).toBe(true)
    expect(model.relationships).toContainEqual(expect.objectContaining({ id: 'relationship:confirmed:gesture:one',
      sourceId: first.id, targetId: second.id, type: 'relates_to', provenance: expect.objectContaining({
        evidence: 'user-confirmed', gestureId: 'gesture:one', confirmedAt: '2026-10-10T12:00:00.000Z',
      }) }))
    expect(confirmedConnectionGraph(linked).links).toEqual([{ id: 'relationship:confirmed:gesture:one', sourceId: first.id, targetId: second.id }])
    expect(() => connectThoughts(linked, second.id, first.id, 'gesture:two')).toThrow('already connected')
    const archived = { ...linked, objects: linked.objects.map(item => item.id === second.id ? setObjectStatus(item, 'archived') : item) }
    expect(confirmedConnectionGraph(archived).links).toEqual([])
    expect(confirmedConnectionGraph(archived).hiddenCount).toBe(1)
  })

  it('disambiguates duplicate thought labels only when needed', () => {
    const { first, second } = thoughts()
    second.interpretation.summary = 'Garden  \n'
    const third = confirmObject(makeObject({ kind: 'idea', source: 'text', originalContent: 'A literal suffix', confidence: .9,
      interpretation: { summary: 'Garden ·irst', suggestedKind: 'idea', rationale: 'Idea' } }))
    third.id = 'thought:third'
    const state = legacyUiProjection(migrateLegacyState({ objects: [first, second, third], canvas: [] }))
    const labels = confirmedConnectionGraph(state).candidates.map(node => node.label)
    expect(labels).toHaveLength(3)
    expect(new Set(labels).size).toBe(3)
    expect(labels[2]).toBe('Garden ·irst')
    expect(labels.every(label => label.startsWith('Garden'))).toBe(true)
    expect(labels.every(label => !/\s{2}/.test(label))).toBe(true)
  })

  it('never promotes old relationship hints or Canvas arrows into confirmed links', () => {
    const { first, second } = thoughts()
    first.relationships = [{ targetId: second.id, type: 'relates_to' }]
    const state = legacyUiProjection(migrateLegacyState({ objects: [first, second], canvas: [{ id: 'arrow', type: 'arrow', x: 0, y: 0,
      fromId: first.id, toId: second.id }] }))
    expect(state.model?.relationships[0].provenance.evidence).toBe('legacy-unverified')
    expect(confirmedConnectionGraph(state).links).toEqual([])
    const tampered = structuredClone(state.model!)
    tampered.relationships[0].provenance = { ...tampered.relationships[0].provenance, evidence: 'user-confirmed' }
    expect(isPersistedState(tampered)).toBe(false)
    expect(safeConnectionGraph({ ...state, model: tampered })).toEqual({ unavailable: true })
  })

  it('removes a mistaken link with an append-only reversal, then allows a new explicit link', () => {
    const { first, second } = thoughts()
    const baseline = legacyUiProjection(migrateLegacyState({ objects: [first, second], canvas: [] }))
    const linked = connectThoughts(baseline, first.id, second.id, 'gesture:create', '2026-10-10T12:00:00.000Z')
    const removed = removeThoughtConnection(linked, 'relationship:confirmed:gesture:create', 'gesture:remove', '2026-10-10T12:01:00.000Z')
    expect(confirmedConnectionGraph(removed).links).toEqual([])
    expect(removed.objects.find(item => item.id === first.id)?.history).toEqual(expect.arrayContaining([
      expect.objectContaining({ relationshipConfirmation: expect.objectContaining({ id: 'gesture:create' }) }),
      expect.objectContaining({ relationshipReversal: { id: 'gesture:remove', reverses: 'gesture:create',
        targetId: second.id, source: 'user-reversed-link' } }),
    ]))
    expect(() => removeThoughtConnection(removed, 'relationship:confirmed:gesture:create')).toThrow('no longer available')
    const reloaded = legacyUiProjection(serializeState(removed))
    expect(confirmedConnectionGraph(reloaded).links).toEqual([])
    expect(reloaded.objects.find(item => item.id === first.id)?.history).toEqual(expect.arrayContaining([
      expect.objectContaining({ relationshipReversal: expect.objectContaining({ id: 'gesture:remove' }) }),
    ]))
    const account = validateData(accountData(reloaded, defaultSettings, { enabled: false }))
    expect(confirmedConnectionGraph(legacyUiProjection(account.model)).links).toEqual([])
    const reconnected = connectThoughts(removed, first.id, second.id, 'gesture:again', '2026-10-10T12:02:00.000Z')
    expect(confirmedConnectionGraph(reconnected).links.map(link => link.id)).toEqual(['relationship:confirmed:gesture:again'])
    expect(isPersistedState(serializeState(reconnected))).toBe(true)
  })

  it('survives local reload and the existing account model round-trip', () => {
    const { first, second } = thoughts()
    const baseline = migrateLegacyState({ objects: [first, second], canvas: [] })
    let raw: string | null = JSON.stringify(baseline)
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const linked = connectThoughts(loadStateResult().state, first.id, second.id, 'gesture:roundtrip', '2026-10-10T12:00:00.000Z')
    expect(saveState(linked)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(confirmedConnectionGraph(reloaded.state).links).toHaveLength(1)
    const account = validateData(accountData(reloaded.state, defaultSettings, { enabled: false }))
    expect(confirmedConnectionGraph(legacyUiProjection(account.model)).links).toHaveLength(1)
    const baseAccount = accountData(legacyUiProjection(baseline), defaultSettings, { enabled: false })
    const accountBefore = structuredClone(baseAccount)
    const linkedBefore = structuredClone(account)
    expect(() => mergeAccountData(baseAccount, account, { settings: 'account', digest: 'account' })).toThrow('Merge stopped:')
    expect(baseAccount).toEqual(accountBefore)
    expect(account).toEqual(linkedBefore)
    vi.unstubAllGlobals()
  })
})
