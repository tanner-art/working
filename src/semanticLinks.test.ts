import { describe, expect, it, vi } from 'vitest'
import { accountData, validateData } from './accountStorage'
import { isPersistedState, legacyUiProjection, migrateLegacyState } from './migration'
import { confirmObject, setObjectStatus } from './objectWorkflow'
import { connectThoughts, confirmedConnectionGraph } from './semanticLinks'
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
    vi.unstubAllGlobals()
  })
})
