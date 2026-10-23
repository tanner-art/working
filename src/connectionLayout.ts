import type { ConnectionGraph } from './semanticLinks'

export interface Point { x: number; y: number }
export interface ConnectionPath { id: string; source: Point; control: Point; target: Point; d: string }

/** Place nodes on a spaced perimeter and bow every edge toward the empty centre.
 * Unlike a row/column layout, a nonadjacent edge cannot run behind another node. */
export function connectionLayout(graph: ConnectionGraph): {
  size: number; positions: Map<string, Point>; paths: ConnectionPath[]
} {
  const radius = Math.max(180, graph.nodes.length * 120 / (2 * Math.PI))
  const centre = { x: radius + 100, y: radius + 100 }
  const positions = new Map(graph.nodes.map((node, index) => {
    const angle = -Math.PI / 2 + index * 2 * Math.PI / graph.nodes.length
    return [node.id, { x: centre.x + radius * Math.cos(angle), y: centre.y + radius * Math.sin(angle) }]
  }))
  const paths = graph.links.flatMap(link => {
    const source = positions.get(link.sourceId)
    const target = positions.get(link.targetId)
    return source && target ? [{ id: link.id, source, control: centre, target,
      d: `M ${source.x.toFixed(2)} ${source.y.toFixed(2)} Q ${centre.x.toFixed(2)} ${centre.y.toFixed(2)} ${target.x.toFixed(2)} ${target.y.toFixed(2)}` }] : []
  })
  return { size: centre.x * 2, positions, paths }
}
