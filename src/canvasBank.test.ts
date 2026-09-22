import { describe, expect, it } from 'vitest'
import { bankFromLegacy, createCanvasRecord, isCanvasBank, listCanvases } from './canvasBank'
import { mergeCanvasBanks } from './canvasBankMerge'

describe('Canvas Bank domain', () => {
  it('validates strict, unique records and rejects invalid titles or documents', () => {
    const record = createCanvasRecord('2026-09-22T01:00:00.000Z', 'canvas:a')
    expect(isCanvasBank({ canvases: [record] })).toBe(true)
    expect(isCanvasBank({ canvases: [record, record] })).toBe(false)
    expect(isCanvasBank({ canvases: [{ ...record, title: '' }] })).toBe(false)
    expect(isCanvasBank({ canvases: [{ ...record, title: ' padded ' }] })).toBe(false)
    expect(isCanvasBank({ canvases: [{ ...record, extra: true }] })).toBe(false)
    expect(isCanvasBank({ canvases: [{ ...record, viewport: { x: 0, y: 0, scale: 8 } }] })).toBe(false)
  })

  it('migrates the legacy document deterministically and preserves every expression field', () => {
    const elements = [
      { id: 'group', type: 'container' as const, x: -3, y: 8, width: 320, height: 210, text: 'Group' },
      { id: 'node', type: 'text' as const, shape: 'diamond' as const, x: 22, y: 44, text: 'Thought', groupId: 'group' },
      { id: 'edge', type: 'arrow' as const, x: 0, y: 0, fromId: 'node', toId: 'group', connectionPath: 'curved' as const, connectionPattern: 'dashed' as const },
    ]
    const viewport = { x: -90, y: 144, scale: .7 }
    expect(bankFromLegacy(elements, viewport)).toEqual(bankFromLegacy(structuredClone(elements), structuredClone(viewport)))
    expect(bankFromLegacy(elements, viewport).canvases[0]).toMatchObject({ id: 'canvas:legacy', elements, viewport })
    expect(bankFromLegacy([], { x: 0, y: 0, scale: 1 })).toEqual({ canvases: [] })
  })

  it('sorts by edit time without using clocks to resolve content', () => {
    const older = { ...createCanvasRecord('2026-09-22T01:00:00.000Z', 'canvas:older'), title: 'Older' }
    const newer = { ...createCanvasRecord('2026-09-22T02:00:00.000Z', 'canvas:newer'), title: 'Newer' }
    expect(listCanvases({ canvases: [older, newer] }).map(item => item.id)).toEqual(['canvas:newer', 'canvas:older'])
  })

  it('unions disjoint canvases, deduplicates identical content, and keeps the account viewport', () => {
    const account = { ...createCanvasRecord('2026-09-22T02:00:00.000Z', 'canvas:a'), title: 'Map', viewport: { x: 5, y: 8, scale: 1.2 } }
    const device = { ...account, createdAt: '2026-09-22T01:00:00.000Z', updatedAt: '2026-09-22T03:00:00.000Z', viewport: { x: -30, y: 10, scale: .8 } }
    const other = { ...createCanvasRecord('2026-09-22T04:00:00.000Z', 'canvas:b'), title: 'Other' }
    const result = mergeCanvasBanks({ canvases: [account] }, { canvases: [device, other] })
    expect(result).toMatchObject({ added: 1, duplicates: 1 })
    expect(result.merged.canvases[0]).toMatchObject({ createdAt: device.createdAt, updatedAt: device.updatedAt, viewport: account.viewport })
    expect(result.merged.canvases.map(item => item.id)).toEqual(['canvas:a', 'canvas:b'])
  })

  it('stops a same-id title or element conflict without mutating either source', () => {
    const record = { ...createCanvasRecord('2026-09-22T01:00:00.000Z', 'canvas:a'), title: 'Account' }
    const account = { canvases: [record] }
    for (const conflict of [{ ...record, title: 'Device' }, { ...record, elements: [{ id: 'n', type: 'text' as const, x: 0, y: 0 }] }]) {
      const device = { canvases: [conflict] }
      const before = structuredClone({ account, device })
      expect(() => mergeCanvasBanks(account, device)).toThrow('Merge stopped: canvas identity')
      expect({ account, device }).toEqual(before)
    }
  })
})
