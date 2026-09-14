import { describe, expect, it } from 'vitest'
import type { CanvasElement } from './domain'
import { attachBlocksInside, moveCanvasNode, removeCanvasNode, setCanvasGroup } from './canvasGroups'
import { convertCanvasNode, resizeCanvasNode } from './canvasGeometry'
import { isAppState } from './store'

const canvas: CanvasElement[] = [
  { id: 'group', type: 'container', x: 100, y: 100, width: 400, height: 300, text: 'Plan' },
  { id: 'inside', type: 'text', x: 150, y: 170, width: 120, height: 100, text: 'Inside' },
  { id: 'outside', type: 'text', x: 600, y: 170, width: 120, height: 100, text: 'Outside' },
  { id: 'arrow', type: 'arrow', x: 0, y: 0, fromId: 'inside', toId: 'outside' },
]

describe('canvas group containment', () => {
  it('attaches only text blocks fully inside the selected group', () => {
    const next = attachBlocksInside(canvas, 'group')
    expect(next.find(item => item.id === 'inside')?.groupId).toBe('group')
    expect(next.find(item => item.id === 'outside')?.groupId).toBeUndefined()
  })

  it('moves a group and its attached blocks as one atomic canvas result', () => {
    const attached = setCanvasGroup(canvas, 'inside', 'group')
    const moved = moveCanvasNode(attached, 'group', 175, 65)
    expect(moved.find(item => item.id === 'group')).toMatchObject({ x: 175, y: 65 })
    expect(moved.find(item => item.id === 'inside')).toMatchObject({ x: 225, y: 135, groupId: 'group' })
    expect(moved.find(item => item.id === 'outside')).toMatchObject({ x: 600, y: 170 })
  })

  it('supports explicit opt-out and rejects arrows, groups, and missing group targets', () => {
    const attached = setCanvasGroup(canvas, 'inside', 'group')
    expect(setCanvasGroup(attached, 'inside')[1].groupId).toBeUndefined()
    expect(setCanvasGroup(canvas, 'group', 'group')).toBe(canvas)
    expect(setCanvasGroup(canvas, 'arrow', 'group')).toBe(canvas)
    expect(setCanvasGroup(canvas, 'inside', 'missing')).toBe(canvas)
  })

  it('keeps membership through resizing even when a member ends outside the new bounds', () => {
    const attached = setCanvasGroup(canvas, 'inside', 'group')
    expect(resizeCanvasNode(attached, 'group', 120, 100).find(item => item.id === 'inside')?.groupId).toBe('group')
  })

  it('detaches members when deleting or converting their group', () => {
    const attached = setCanvasGroup(canvas, 'inside', 'group')
    expect(removeCanvasNode(attached, 'group').find(item => item.id === 'inside')?.groupId).toBeUndefined()
    expect(convertCanvasNode(attached, 'group', 'text').find(item => item.id === 'inside')?.groupId).toBeUndefined()
  })

  it('validates persisted membership while accepting legacy canvases without it', () => {
    expect(isAppState({ objects: [], canvas })).toBe(true)
    expect(isAppState({ objects: [], canvas: setCanvasGroup(canvas, 'inside', 'group') })).toBe(true)
    expect(isAppState({ objects: [], canvas: [{ ...canvas[1], groupId: 'missing' }] })).toBe(false)
    expect(isAppState({ objects: [], canvas: [{ ...canvas[0], groupId: 'group' }] })).toBe(false)
  })
})
