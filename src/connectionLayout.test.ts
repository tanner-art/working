import { describe, expect, it } from 'vitest'
import { connectionLayout } from './connectionLayout'
import type { ConnectionGraph } from './semanticLinks'

const pointOnCurve = (source: { x: number; y: number }, control: { x: number; y: number }, target: { x: number; y: number }, t: number) => ({
  x: (1 - t) ** 2 * source.x + 2 * (1 - t) * t * control.x + t ** 2 * target.x,
  y: (1 - t) ** 2 * source.y + 2 * (1 - t) * t * control.y + t ** 2 * target.y,
})

describe('connection graph layout', () => {
  it('keeps a nonadjacent A–C edge clear of unrelated node B', () => {
    const graph: ConnectionGraph = { candidates: [], hiddenCount: 0,
      nodes: ['A', 'B', 'C'].map(id => ({ id, label: id, kind: 'idea' })),
      links: [{ id: 'A-B', sourceId: 'A', targetId: 'B' }, { id: 'A-C', sourceId: 'A', targetId: 'C' }] }
    const layout = connectionLayout(graph)
    const across = layout.paths.find(path => path.id === 'A-C')!
    const other = layout.positions.get('B')!
    for (let step = 0; step <= 100; step++) {
      const point = pointOnCurve(across.source, across.control, across.target, step / 100)
      expect(Math.hypot(point.x - other.x, point.y - other.y)).toBeGreaterThan(46)
    }
    expect(across.d).toContain(' Q ')
  })

  it('keeps every tested edge clear of unrelated nodes as the graph grows', () => {
    for (const count of [4, 5, 8, 12, 20]) {
      const nodes = Array.from({ length: count }, (_, index) => ({ id: `N${index}`, label: `${index}`, kind: 'idea' }))
      const links = nodes.flatMap((source, index) => nodes.slice(index + 1).map(target => ({
        id: `${source.id}-${target.id}`, sourceId: source.id, targetId: target.id,
      })))
      const layout = connectionLayout({ candidates: nodes, nodes, links, hiddenCount: 0 })
      for (const path of layout.paths) for (const node of nodes) {
        if (node.id === path.id.split('-')[0] || node.id === path.id.split('-')[1]) continue
        const other = layout.positions.get(node.id)!
        for (let step = 0; step <= 40; step++) {
          const point = pointOnCurve(path.source, path.control, path.target, step / 40)
          expect(Math.hypot(point.x - other.x, point.y - other.y)).toBeGreaterThan(46)
        }
      }
    }
  })
})
