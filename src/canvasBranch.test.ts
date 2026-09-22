import { describe, expect, it } from 'vitest'
import type { CanvasElement } from './domain'
import { branchCanvasChild } from './canvasBranch'
import { canvasSize, convertCanvasNode, resizeCanvasNode } from './canvasGeometry'
import { removeCanvasNode } from './canvasGroups'
import { commitCanvas, emptyCanvasHistory, redoCanvas, undoCanvas } from './canvasHistory'

const parent: CanvasElement = { id: 'parent', type: 'text', x: 20, y: 40, text: 'Parent' }

describe('canvas branching', () => {
  it('adds one independent text child and one visual arrow at a deterministic open offset', () => {
    const blocker: CanvasElement = { id: 'blocker', type: 'text', x: 282, y: 40, text: 'Occupied' }
    const branch = branchCanvasChild([parent, blocker], parent.id, (() => {
      const ids = ['child', 'arrow']
      return () => ids.shift()!
    })())!

    expect(branch.childId).toBe('child')
    expect(branch.arrowId).toBe('arrow')
    expect(branch.elements).toEqual([
      parent, blocker,
      { id: 'child', type: 'text', x: 282, y: 188, width: 190, height: 100, text: 'New thought' },
      { id: 'arrow', type: 'arrow', x: 0, y: 0, fromId: 'parent', toId: 'child' },
    ])
    expect(canvasSize(branch.elements[2])).toEqual({ width: 190, height: 100 })
  })

  it('is one history step and leaves the child independently editable, resizable, and shape-convertible', () => {
    const branch = branchCanvasChild([parent], parent.id, (() => {
      const ids = ['child', 'arrow']
      return () => ids.shift()!
    })())!
    const history = commitCanvas(emptyCanvasHistory([parent]), branch.elements)
    expect(history.past).toHaveLength(1)
    expect(undoCanvas(history).present).toEqual([parent])
    expect(redoCanvas(undoCanvas(history)).present).toEqual(branch.elements)
    const resized = resizeCanvasNode(branch.elements, branch.childId, 300, 180)
    const converted = convertCanvasNode(resized, branch.childId, 'ellipse')
    expect(converted.find(item => item.id === branch.childId)).toMatchObject({ type: 'text', shape: 'ellipse', width: 300, height: 180 })
    expect(converted.find(item => item.id === branch.arrowId)).toMatchObject({ fromId: parent.id, toId: branch.childId })
  })

  it('refuses arrows and bad generated IDs, and deletion never leaves a dangling branch arrow', () => {
    const arrow: CanvasElement = { id: 'existing-arrow', type: 'arrow', x: 0, y: 0, fromId: 'parent', toId: 'parent' }
    expect(branchCanvasChild([parent, arrow], arrow.id, () => 'unused')).toBeUndefined()
    expect(branchCanvasChild([parent], parent.id, () => parent.id)).toBeUndefined()
    const branch = branchCanvasChild([parent], parent.id, (() => {
      const ids = ['child', 'arrow']
      return () => ids.shift()!
    })())!
    const parentDeleted = removeCanvasNode(branch.elements, parent.id)
    const childDeleted = removeCanvasNode(branch.elements, branch.childId)
    expect(parentDeleted).toEqual([branch.elements[1]])
    expect(childDeleted).toEqual([parent])
    const deletedHistory = commitCanvas(commitCanvas(emptyCanvasHistory([parent]), branch.elements), childDeleted)
    expect(undoCanvas(deletedHistory).present).toEqual(branch.elements)
    expect(redoCanvas(undoCanvas(deletedHistory)).present).toEqual(childDeleted)
    expect(childDeleted.some(item => item.type === 'arrow')).toBe(false)
  })
})
