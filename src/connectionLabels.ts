import type { ConnectionNode } from './semanticLinks'

const normalizedLabel = (label: string) => label.replace(/\s+/g, ' ').trim() || 'Untitled thought'
const shortLabel = (label: string) => label.length <= 24 ? label : `${label.slice(0, 23)}…`

/** Derive labels from structured node identity, not title syntax. Reserve every
 * unique literal title before suffixing duplicates, so a title that happens to
 * look like a generated suffix cannot collide with one. */
function connectionLabels(nodes: ConnectionNode[], shorten: boolean): Map<string, string> {
  const bases = new Map(nodes.map(node => {
    const normalized = normalizedLabel(node.label)
    return [node.id, shorten ? shortLabel(normalized) : normalized]
  }))
  const counts = new Map<string, number>()
  for (const base of bases.values()) counts.set(base, (counts.get(base) ?? 0) + 1)
  const labels = new Map<string, string>()
  const used = new Set<string>()
  for (const node of nodes) {
    const base = bases.get(node.id)!
    if (counts.get(base) === 1) { labels.set(node.id, base); used.add(base) }
  }
  for (const node of [...nodes].sort((left, right) => left.id.localeCompare(right.id))) {
    const base = bases.get(node.id)!
    if (counts.get(base) === 1) continue
    const suffix = node.id.slice(-4)
    let label = `${base} ·${suffix}`
    let sequence = 2
    while (used.has(label)) label = `${base} ·${suffix}-${sequence++}`
    labels.set(node.id, label)
    used.add(label)
  }
  return labels
}

/** Full, collision-safe labels for every navigable choice and link action. */
export function connectionFullLabels(nodes: ConnectionNode[]): Map<string, string> {
  return connectionLabels(nodes, false)
}

/** Compact graph labels obey the same identity rule after visual truncation. */
export function connectionDisplayLabels(nodes: ConnectionNode[]): Map<string, string> {
  return connectionLabels(nodes, true)
}
