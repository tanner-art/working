import { describe, expect, it } from 'vitest'
import type { ObjectKind, ThoughtObject } from './domain'
import { interpret } from './interpreter'
import { activeObjects, confirmedActions, fixedCommitments, confirmObject, updateObject } from './objectWorkflow'
import { isAppState } from './store'

describe('interpret', () => {
  it('recognizes an explicit action with high confidence', () => {
    const result = interpret('Give marketing guys access')
    expect(result.kind).toBe('action')
    expect(result.confidence).toBeGreaterThanOrEqual(.8)
  })

  it('routes ambiguous topic captures through review confidence', () => {
    const result = interpret('AI sales training')
    expect(result.kind).toBe('idea')
    expect(result.confidence).toBeLessThan(.8)
  })
})

describe('persisted state validation', () => {
  it('accepts complete object and canvas collections', () => {
    expect(isAppState({ objects: [object({ id: 'a', status: 'review' })], canvas: [{ id: 'b', type: 'text', x: 10, y: 20 }] })).toBe(true)
  })

  it('rejects malformed saved state instead of loading it', () => {
    expect(isAppState({ objects: [{ originalContent: 'Missing id' }], canvas: null })).toBe(false)
  })

  it('rejects unknown object kinds and statuses', () => {
    expect(isAppState({ objects: [{ ...object({ id: 'a' }), kind: 'task' }], canvas: [] })).toBe(false)
    expect(isAppState({ objects: [{ ...object({ id: 'b' }), status: 'later' }], canvas: [] })).toBe(false)
  })

  it('rejects canvas arrows without endpoints', () => {
    expect(isAppState({ objects: [], canvas: [{ id: 'arrow', type: 'arrow', x: 0, y: 0 }] })).toBe(false)
  })
})

describe('object workflow', () => {
  it('keeps archived objects out of active workbench lists', () => {
    expect(activeObjects([object({ id: 'visible' }), object({ id: 'hidden', status: 'archived' })]).map(item => item.id)).toEqual(['visible'])
  })

  it('ranks confirmed actions by independent priority dimensions', () => {
    const lowAttention = object({ id: 'low', kind: 'action', metadata: { strategicImportance: 4, urgency: 3, effort: 'small', attentionLoad: 'low' } })
    const heavy = object({ id: 'heavy', kind: 'action', metadata: { strategicImportance: 2, urgency: 3, effort: 'large', attentionLoad: 'high' } })
    expect(confirmedActions([heavy, lowAttention]).map(item => item.id)).toEqual(['low', 'heavy'])
  })

  it('only treats confirmed reminders and commitments as fixed calendar items', () => {
    const reminder = object({ id: 'reminder', kind: 'reminder' })
    const uncertain = object({ id: 'uncertain', kind: 'commitment', status: 'review' })
    expect(fixedCommitments([reminder, uncertain]).map(item => item.id)).toEqual(['reminder'])
  })

  it('preserves object history when confirming and editing', () => {
    const confirmed = confirmObject(object({ status: 'review' }), 'project')
    const edited = updateObject(confirmed, { ...confirmed, context: 'Carvers' })
    expect(confirmed.status).toBe('confirmed')
    expect(confirmed.kind).toBe('project')
    expect(edited.history).toHaveLength(3)
    expect(edited.history.at(-1)?.event).toContain('context')
  })
})

function object(overrides: Partial<ThoughtObject> & { id?: string; kind?: ObjectKind } = {}): ThoughtObject {
  return {
    id: overrides.id ?? 'object',
    kind: overrides.kind ?? 'idea',
    originalContent: 'Captured thought',
    source: 'text',
    createdAt: overrides.createdAt ?? '2026-09-13T00:00:00.000Z',
    interpretation: { summary: 'Captured thought', suggestedKind: overrides.kind ?? 'idea', rationale: 'test object' },
    confidence: .9,
    relationships: [],
    history: [{ at: '2026-09-13T00:00:00.000Z', event: 'Captured' }],
    status: overrides.status ?? 'confirmed',
    metadata: overrides.metadata ?? {},
    context: overrides.context
  }
}
