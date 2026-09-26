import { describe, expect, it } from 'vitest'
import { createCanvasRecord, listCanvases } from './canvasBank'
import { filterCanvasesByTitle } from './canvasBankSearch'

const canvas = (id: string, title: string, updatedAt: string) => ({
  ...createCanvasRecord('2026-09-26T08:00:00.000Z', id),
  title,
  updatedAt,
})

describe('filterCanvasesByTitle', () => {
  const productMap = canvas('canvas:product', 'Product map', '2026-09-26T10:00:00.000Z')
  const launchPlan = canvas('canvas:launch', 'Launch plan', '2026-09-26T09:00:00.000Z')
  const researchMap = canvas('canvas:research', 'Research Map', '2026-09-26T08:00:00.000Z')
  const orderedCanvases = listCanvases({ canvases: [launchPlan, researchMap, productMap] })

  it('finds title matches case-insensitively after trimming the query', () => {
    expect(filterCanvasesByTitle(orderedCanvases, '  MAP ')).toEqual([productMap, researchMap])
  })

  it('returns every canvas for an empty or whitespace-only query', () => {
    expect(filterCanvasesByTitle(orderedCanvases, '')).toEqual(orderedCanvases)
    expect(filterCanvasesByTitle(orderedCanvases, '   ')).toEqual(orderedCanvases)
  })

  it('returns no canvases when no title matches', () => {
    expect(filterCanvasesByTitle(orderedCanvases, 'finance')).toEqual([])
  })

  it('keeps the supplied order and does not mutate canvas content', () => {
    const before = structuredClone(orderedCanvases)
    const matches = filterCanvasesByTitle(orderedCanvases, 'map')

    expect(matches.map(canvas => canvas.id)).toEqual(['canvas:product', 'canvas:research'])
    expect(orderedCanvases).toEqual(before)
    expect(matches[0]).toBe(orderedCanvases[0])
  })
})
