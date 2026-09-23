import { describe, expect, it } from 'vitest'
import type { AppState } from './domain'
import { buildHomeBeta } from './homeBeta'
import { makeObject } from './store'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject } from './objectWorkflow'

describe('homeBeta model', () => {
  it('counts captures from the persisted model, not from legacy objects array length', () => {
    const item1 = makeObject({ kind: 'idea', source: 'text', originalContent: 'Idea 1', confidence: 0.9,
      interpretation: { summary: 'Idea', rationale: 'test', suggestedKind: 'idea' } })
    const item2 = makeObject({ kind: 'idea', source: 'text', originalContent: 'Idea 2', confidence: 0.7,
      interpretation: { summary: 'Idea 2', rationale: 'test', suggestedKind: 'idea' } })
    const state: AppState = { objects: [item1, item2], canvas: [] }
    const model = buildHomeBeta(state)
    expect(model.captureCount).toBe(2)
  })

  it('counts confirmed interpretations by reading from PersistedState, not AppState.objects count', () => {
    const item1 = makeObject({ kind: 'action', source: 'text', originalContent: 'Task A', confidence: 0.9,
      interpretation: { summary: 'Do A', rationale: 'test', suggestedKind: 'action' } })
    const item2 = makeObject({ kind: 'idea', source: 'text', originalContent: 'Idea B', confidence: 0.5,
      interpretation: { summary: 'Think B', rationale: 'test', suggestedKind: 'idea' } })
    let state: AppState = { objects: [item1, item2], canvas: [] }

    const ui = legacyUiProjection(migrateLegacyState(state))
    ui.objects[0] = confirmObject(ui.objects[0])
    state = ui

    const model = buildHomeBeta(state)
    expect(model.confirmationCount).toBe(1)
  })

  it('counts confirmed commitments from semantic objects, not legacy kind matching', () => {
    const item = makeObject({ kind: 'commitment', source: 'text', originalContent: 'Call Alex', confidence: 0.95,
      interpretation: { summary: 'Call Alex', rationale: 'commitment', suggestedKind: 'commitment' } })
    const proposed = legacyUiProjection(migrateLegacyState({ objects: [item], canvas: [] }))
    proposed.objects[0] = confirmObject(proposed.objects[0])
    const state = legacyUiProjection(reconcileLegacyUi(proposed))
    const model = buildHomeBeta(state)
    expect(model.commitmentCount).toBe(1)
  })

  it('counts confirmed actions separately from commitments', () => {
    const item = makeObject({ kind: 'action', source: 'text', originalContent: 'Write report', confidence: 0.9,
      interpretation: { summary: 'Write report', rationale: 'action', suggestedKind: 'action' } })
    const proposed = legacyUiProjection(migrateLegacyState({ objects: [item], canvas: [] }))
    proposed.objects[0] = confirmObject(proposed.objects[0])
    const state = legacyUiProjection(reconcileLegacyUi(proposed))
    const model = buildHomeBeta(state)
    expect(model.actionCount).toBe(1)
    expect(model.commitmentCount).toBe(0)
  })

  it('counts canvas elements from the current canvas, not from canvasBank documents', () => {
    const state: AppState = {
      objects: [],
      canvas: [
        { id: 'text-1', type: 'text', x: 0, y: 0, text: 'Node 1' },
        { id: 'arrow-1', type: 'arrow', x: 0, y: 0, fromId: 'text-1', toId: 'text-2' }
      ],
      canvasBank: {
        canvases: [
          { id: 'doc-1', title: 'First doc', createdAt: '2026-09-14T00:00:00Z', updatedAt: '2026-09-14T00:00:00Z',
            elements: [{ id: 'saved-text', type: 'text', x: 10, y: 10, text: 'Saved node' }], viewport: { x: 0, y: 0, scale: 1 } }
        ]
      }
    }
    const model = buildHomeBeta(state)
    expect(model.canvasElementCount).toBe(2)
  })

  it('counts canvas bank documents accurately including zero when no bank exists', () => {
    const state: AppState = { objects: [], canvas: [] }
    expect(buildHomeBeta(state).canvasBankDocCount).toBe(0)

    state.canvasBank = { canvases: [
      { id: 'doc-1', title: 'Doc 1', createdAt: '2026-09-14T00:00:00Z', updatedAt: '2026-09-14T00:00:00Z', elements: [], viewport: { x: 0, y: 0, scale: 1 } },
      { id: 'doc-2', title: 'Doc 2', createdAt: '2026-09-14T00:00:00Z', updatedAt: '2026-09-14T00:00:00Z', elements: [], viewport: { x: 0, y: 0, scale: 1 } }
    ] }
    expect(buildHomeBeta(state).canvasBankDocCount).toBe(2)
  })

  it('preserves data immutability and does not mutate input state', () => {
    const state: AppState = {
      objects: [makeObject({ kind: 'action', source: 'text', originalContent: 'Test', confidence: 0.8,
        interpretation: { summary: 'Test task', rationale: 'test', suggestedKind: 'action' } })],
      canvas: [{ id: 'elem-1', type: 'text', x: 0, y: 0, text: 'Node' }]
    }
    const before = JSON.stringify(state)
    buildHomeBeta(state)
    expect(JSON.stringify(state)).toBe(before)
  })
})
