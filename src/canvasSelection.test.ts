import { describe, expect, it } from 'vitest'
import { removeCanvasNode } from './canvasGroups'
import { canvasObjectSelection } from './canvasSelection'
import { removeSelectedCanvasStrokes } from './canvasStrokes'

describe('canvas selection ownership', () => {
  it('lets a newly added node win over a prior lasso stroke selection when Delete is pressed', () => {
    const elements = [
      { id: 'stroke', type: 'freehand' as const, x: 0, y: 0, rawPoints: [{ x: 0, y: 0 }, { x: 20, y: 20 }] },
      { id: 'new-node', type: 'text' as const, x: 30, y: 30, text: 'New thought' },
    ]
    const lassoSelection = { selectedId: null, selectedStrokeIds: new Set(['stroke']), refinementCandidateId: 'stroke' }
    expect(removeSelectedCanvasStrokes(elements, lassoSelection.selectedStrokeIds).map(item => item.id)).toEqual(['new-node'])

    const selected = canvasObjectSelection('new-node')
    expect(selected).toEqual({ selectedId: 'new-node', selectedStrokeIds: new Set(), refinementCandidateId: null })
    const remaining = selected.selectedStrokeIds.size > 0
      ? removeSelectedCanvasStrokes(elements, selected.selectedStrokeIds)
      : removeCanvasNode(elements, selected.selectedId)
    expect(remaining.map(item => item.id)).toEqual(['stroke'])
  })
})
