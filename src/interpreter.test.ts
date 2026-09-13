import { afterEach, describe, expect, it, vi } from 'vitest'
import { commitCanvas, redoCanvas, undoCanvas, type CanvasHistory } from './canvasHistory'
import type { ObjectKind, ThoughtObject } from './domain'
import { interpret } from './interpreter'
import { buildMorningDigest } from './morningDigest'
import { dependencyCandidates } from './dependencies'
import { projectChildren } from './objectWorkflow'
import { activeObjects, canvasObjectDraft, confirmedActions, fixedCommitments, confirmObject, parentCandidates, parentObject, setBelongsTo, setObjectKind, updateObject } from './objectWorkflow'
import { isAppState, loadStateResult, saveState } from './store'

describe('storage failures', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('distinguishes a new workspace from unreadable saved thoughts without overwriting them', () => {
    const setItem = vi.fn()
    const getItem = vi.fn().mockReturnValue(null)
    vi.stubGlobal('localStorage', { getItem, setItem })
    expect(loadStateResult().error).toBeUndefined()
    getItem.mockReturnValue('{broken')
    expect(loadStateResult().error).toBeTruthy()
    getItem.mockReturnValue('{"objects": []}')
    expect(loadStateResult().error).toBeTruthy()
    expect(setItem).not.toHaveBeenCalled()
  })

  it('reports unavailable storage and lets a failed write be retried', () => {
    const setItem = vi.fn().mockImplementationOnce(() => { throw new Error('Quota exceeded') })
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('Storage denied') }, setItem })
    expect(loadStateResult().error).toBeTruthy()
    const state = { objects: [object()], canvas: [] }
    expect(saveState(state)).toContain('only in this open tab')
    expect(saveState(state)).toBeUndefined()
    expect(JSON.parse(setItem.mock.calls[1][1])).toEqual(state)
  })
})

describe('interpret', () => {
  it('keeps tentative, conditional, negative, and questioned actions in review', () => {
    for (const content of ['Maybe send the proposal', 'If approved, buy the monitor', "Don’t email the client", 'Should I call Ahmed?', 'Cancel the call']) {
      expect(interpret(content).confidence, content).toBeLessThan(.8)
    }
  })

  it('treats explicit reminder requests as proposals requiring timing review', () => {
    const result = interpret('Remind me to buy screws tomorrow')
    expect(result.kind).toBe('reminder')
    expect(result.confidence).toBeLessThan(.8)
  })

  it('does not mistake a numeric date for a project cluster', () => {
    expect(interpret('Call Ahmed 9/15').kind).toBe('reminder')
  })
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

  it('routes clustered captures to review as a possible project', () => {
    const result = interpret('Screws for monitor / selling arm things / better keyboard')
    expect(result.kind).toBe('project')
    expect(result.confidence).toBeLessThan(.8)
  })

  it('does not silently create hard commitments from ambiguous timing', () => {
    const result = interpret('Ahmed Monday convo')
    expect(result.kind).toBe('reminder')
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

  it('validates optional resource and ROI dimensions', () => {
    expect(isAppState({ objects: [object({ metadata: { resourceCost: 'low', roi: 5 } })], canvas: [] })).toBe(true)
    expect(isAppState({ objects: [object({ metadata: { resourceCost: 'expensive' as 'high', roi: 9 as 5 } })], canvas: [] })).toBe(false)
  })
})

describe('object workflow', () => {
  it('shows direct project contents across types without archived or unrelated thoughts', () => {
    const linked = (id: string, kind: ObjectKind, status: ThoughtObject['status'] = 'confirmed') => object({ id, kind, status, relationships: [{ type: 'belongs_to', targetId: 'project' }] })
    const items = [linked('idea', 'idea'), linked('done', 'action', 'complete'), linked('hidden', 'reference', 'archived'), object({ id: 'related', relationships: [{ type: 'relates_to', targetId: 'project' }] }), object({ id: 'grandchild', relationships: [{ type: 'belongs_to', targetId: 'idea' }] })]
    expect(projectChildren(items, 'project').map(item => item.id)).toEqual(['idea', 'done'])
    expect(projectChildren(items, 'idea').map(item => item.id)).toEqual(['grandchild'])
  })
  it('withholds blocked actions until every prerequisite is complete', () => {
    const task = object({ id: 'task', kind: 'action', relationships: [{ type: 'depends_on', targetId: 'prerequisite' }] })
    expect(confirmedActions([task])).toEqual([])
    for (const status of ['review', 'confirmed', 'archived'] as const) {
      expect(confirmedActions([task, object({ id: 'prerequisite', status })])).toEqual([])
    }
    expect(confirmedActions([task, object({ id: 'prerequisite', status: 'complete' })]).map(item => item.id)).toEqual(['task'])
  })

  it('prevents duplicate and circular dependency choices', () => {
    const root = object({ id: 'root', kind: 'action', relationships: [{ type: 'depends_on', targetId: 'already' }] })
    const items = [root,
      object({ id: 'already', kind: 'action' }),
      object({ id: 'child', kind: 'action', relationships: [{ type: 'depends_on', targetId: 'root' }] }),
      object({ id: 'grandchild', kind: 'action', relationships: [{ type: 'depends_on', targetId: 'child' }] }),
      object({ id: 'safe', kind: 'project' })]
    expect(dependencyCandidates(root, items).map(item => item.id)).toEqual(['safe'])
    expect(updateObject(root, { ...root, relationships: [] }).history.at(-1)?.event).toContain('dependencies')
  })
  it('keeps archived objects out of active workbench lists', () => {
    expect(activeObjects([object({ id: 'visible' }), object({ id: 'hidden', status: 'archived' })]).map(item => item.id)).toEqual(['visible'])
  })

  it('ranks confirmed actions by independent priority dimensions', () => {
    const lowAttention = object({ id: 'low', kind: 'action', metadata: { strategicImportance: 4, urgency: 3, effort: 'small', attentionLoad: 'low', resourceCost: 'low', roi: 4 } })
    const heavy = object({ id: 'heavy', kind: 'action', metadata: { strategicImportance: 2, urgency: 3, effort: 'large', attentionLoad: 'high', resourceCost: 'high', roi: 2 } })
    expect(confirmedActions([heavy, lowAttention]).map(item => item.id)).toEqual(['low', 'heavy'])
  })

  it('only treats confirmed reminders and commitments as fixed calendar items', () => {
    const reminder = object({ id: 'reminder', kind: 'reminder' })
    const uncertain = object({ id: 'uncertain', kind: 'commitment', status: 'review' })
    expect(fixedCommitments([reminder, uncertain]).map(item => item.id)).toEqual(['reminder'])
  })

  it('preserves object history when confirming and editing', () => {
    const uncertain = { ...object({ kind: 'idea', status: 'review' }), confidence: .64 }
    const corrected = confirmObject(setObjectKind(uncertain, 'action'))
    expect(corrected.confidence).toBe(.64)
    expect(corrected.interpretation).toEqual(uncertain.interpretation)
    expect(corrected.originalContent).toBe(uncertain.originalContent)
    expect(corrected.kind).toBe('action')
    expect(corrected.status).toBe('confirmed')
    const confirmed = confirmObject(object({ status: 'review' }), 'project')
    const edited = updateObject(confirmed, { ...confirmed, context: 'Carvers' })
    expect(confirmed.status).toBe('confirmed')
    expect(confirmed.kind).toBe('project')
    expect(edited.history).toHaveLength(3)
    expect(edited.history.at(-1)?.event).toContain('context')
  })

  it('lets review change the proposed type without rewriting original content', () => {
    const original = object({ kind: 'idea', originalContent: 'AI sales training', status: 'review' })
    const changed = setObjectKind(original, 'project')
    expect(changed.originalContent).toBe('AI sales training')
    expect(changed.kind).toBe('project')
    expect(changed.interpretation.suggestedKind).toBe('idea')
    expect(changed.history.at(-1)?.event).toContain('Changed type')
  })

  it('creates a reviewable semantic draft from canvas text without changing the canvas', () => {
    const draft = canvasObjectDraft({ id: 'node', type: 'text', x: 10, y: 20, text: 'AI sales training' })
    expect(draft).toMatchObject({ kind: 'idea', originalContent: 'AI sales training', source: 'canvas', confidence: .72 })
    expect(draft?.interpretation.rationale).toContain('Captured from canvas')
  })

  it('does not create semantic drafts from empty nodes or arrows', () => {
    expect(canvasObjectDraft({ id: 'empty', type: 'text', x: 0, y: 0, text: ' ' })).toBeNull()
    expect(canvasObjectDraft({ id: 'arrow', type: 'arrow', x: 0, y: 0, fromId: 'a', toId: 'b' })).toBeNull()
  })

  it('links objects to one parent without duplicating belongs-to relationships', () => {
    const linked = setBelongsTo(object({ id: 'action', kind: 'action' }), 'project')
    const relinked = setBelongsTo(linked, 'objective')
    expect(relinked.relationships).toEqual([{ targetId: 'objective', type: 'belongs_to' }])
  })

  it('offers only active projects and objectives as parent candidates', () => {
    const candidates = parentCandidates([
      object({ id: 'self', kind: 'action' }),
      object({ id: 'project', kind: 'project' }),
      object({ id: 'objective', kind: 'objective' }),
      object({ id: 'archived-project', kind: 'project', status: 'archived' }),
      object({ id: 'idea', kind: 'idea' })
    ], 'self')
    expect(candidates.map(item => item.id)).toEqual(['project', 'objective'])
  })

  it('resolves a visible parent object from belongs-to relationships', () => {
    const project = object({ id: 'project', kind: 'project', originalContent: 'Carvers' })
    const action = object({ id: 'action', kind: 'action', relationships: [{ targetId: 'project', type: 'belongs_to' }] })
    expect(parentObject([project, action], action)?.originalContent).toBe('Carvers')
  })

  it('prevents a project from belonging to itself or its descendants, including through archived ancestors', () => {
    const projects = [
      object({ id: 'root', kind: 'project' }),
      object({ id: 'child', kind: 'project', status: 'archived', relationships: [{ type: 'belongs_to', targetId: 'root' }] }),
      object({ id: 'grandchild', kind: 'project', relationships: [{ type: 'belongs_to', targetId: 'child' }] }),
      object({ id: 'unrelated', kind: 'objective' })
    ]
    expect(parentCandidates(projects, 'root').map(item => item.id)).toEqual(['unrelated'])
    expect(parentCandidates(projects, 'grandchild').map(item => item.id)).toEqual(['root', 'unrelated'])
  })

  it('excludes existing circular ancestry without hanging the parent selector', () => {
    const projects = [
      object({ id: 'a', kind: 'project', relationships: [{ type: 'belongs_to', targetId: 'b' }] }),
      object({ id: 'b', kind: 'project', relationships: [{ type: 'belongs_to', targetId: 'a' }] }),
      object({ id: 'safe', kind: 'project' })
    ]
    expect(parentCandidates(projects, 'new').map(item => item.id)).toEqual(['safe'])
  })

  it('records parent-link changes as one edit event', () => {
    const original = object({ id: 'action', kind: 'action' })
    const edited = updateObject(original, { ...original, relationships: [{ targetId: 'project', type: 'belongs_to' }] })
    expect(edited.history).toHaveLength(2)
    expect(edited.history.at(-1)?.event).toContain('parent link')
  })
})

describe('canvas history', () => {
  it('undoes and redoes committed canvas changes', () => {
    const first = [{ id: 'a', type: 'text' as const, x: 0, y: 0, text: 'A' }]
    const second = [{ ...first[0], x: 40 }]
    const committed = commitCanvas({ past: [], present: first, future: [] }, second)
    const undone = undoCanvas(committed)
    const redone = redoCanvas(undone)
    expect(undone.present[0].x).toBe(0)
    expect(redone.present[0].x).toBe(40)
  })

  it('does not add history for unchanged canvas state', () => {
    const present = [{ id: 'a', type: 'text' as const, x: 0, y: 0 }]
    expect(commitCanvas({ past: [], present, future: [] }, present).past).toHaveLength(0)
  })

  it('caps undo history so long canvas sessions stay bounded', () => {
    const present = [{ id: 'start', type: 'text' as const, x: 0, y: 0 }]
    const initial: CanvasHistory = { past: [], present, future: [] }
    const history = Array.from({ length: 30 }).reduce<CanvasHistory>((current, _, index) =>
      commitCanvas(current, [{ id: `${index}`, type: 'text', x: index, y: 0 }]),
    initial)
    expect(history.past.length).toBeLessThanOrEqual(25)
  })
})

describe('morning digest', () => {
  it('uses an edited deadline instead of an older proposed date', () => {
    const digest = buildMorningDigest([
      object({ id: 'rescheduled', kind: 'commitment', metadata: { deadline: '2026-09-16' }, interpretation: { summary: 'Meeting', suggestedKind: 'commitment', rationale: 'Meeting', suggestedDate: '2026-09-13' } })
    ], new Date(2026, 8, 13, 7))
    expect(digest.fixedToday).toEqual([])
    expect(digest.upcoming.map(item => item.id)).toEqual(['rescheduled'])
  })

  it('shows the nearest three upcoming dates and excludes unresolved or invalid dates', () => {
    const items = ['2026-12-01', 'Tuesday', '2026-09-31', '2026-09-16', '2026-09-14', '2026-09-15'].map(date => object({ id: date, kind: 'commitment', metadata: { deadline: date } }))
    expect(buildMorningDigest(items, new Date(2026, 8, 13, 7)).upcoming.map(item => item.id)).toEqual(['2026-09-14', '2026-09-15', '2026-09-16'])
  })
  it('keeps fixed commitments separate from flexible execution picks', () => {
    const digest = buildMorningDigest([
      object({ id: 'fixed', kind: 'commitment', metadata: { deadline: '2026-09-13' }, interpretation: { summary: 'fixed', suggestedKind: 'commitment', rationale: 'fixed', suggestedDate: '2026-09-13' } }),
      object({ id: 'action', kind: 'action', metadata: { strategicImportance: 5, urgency: 4 } }),
      object({ id: 'review', kind: 'idea', status: 'review' })
    ], new Date('2026-09-13T07:00:00.000Z'))
    expect(digest.fixedToday.map(item => item.id)).toEqual(['fixed'])
    expect(digest.recommended.map(item => item.id)).toEqual(['action'])
    expect(digest.needsReview.map(item => item.id)).toEqual(['review'])
  })

  it('surfaces upcoming commitments without treating them as today', () => {
    const digest = buildMorningDigest([
      object({ id: 'future', kind: 'reminder', metadata: { deadline: '2026-09-15' } })
    ], new Date('2026-09-13T07:00:00.000Z'))
    expect(digest.fixedToday).toHaveLength(0)
    expect(digest.upcoming.map(item => item.id)).toEqual(['future'])
  })

  it('uses the local calendar day for today matching', () => {
    const digest = buildMorningDigest([
      object({ id: 'local', kind: 'commitment', metadata: { deadline: '2026-09-13' } })
    ], new Date(2026, 8, 13, 0, 5))
    expect(digest.fixedToday.map(item => item.id)).toEqual(['local'])
  })
})

function object(overrides: Partial<ThoughtObject> & { id?: string; kind?: ObjectKind } = {}): ThoughtObject {
  return {
    id: overrides.id ?? 'object',
    kind: overrides.kind ?? 'idea',
    originalContent: overrides.originalContent ?? 'Captured thought',
    source: 'text',
    createdAt: overrides.createdAt ?? '2026-09-13T00:00:00.000Z',
    interpretation: overrides.interpretation ?? { summary: 'Captured thought', suggestedKind: overrides.kind ?? 'idea', rationale: 'test object' },
    confidence: .9,
    relationships: overrides.relationships ?? [],
    history: [{ at: '2026-09-13T00:00:00.000Z', event: 'Captured' }],
    status: overrides.status ?? 'confirmed',
    metadata: overrides.metadata ?? {},
    context: overrides.context
  }
}
