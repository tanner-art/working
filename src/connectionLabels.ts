import type { ConnectionNode } from './semanticLinks'

const shortLabel = (label: string) => {
  const clean = label.replace(/\s+/g, ' ').trim() || 'Untitled thought'
  return clean.length <= 24 ? clean : `${clean.slice(0, 23)}…`
}

/** Visual labels are derived from node identities, never guessed from title syntax.
 * The full, navigable list below the graph retains the unshortened labels. */
export function connectionDisplayLabels(nodes: ConnectionNode[]): Map<string, string> {
  const bases = nodes.map(node => shortLabel(node.label))
  const counts = new Map<string, number>()
  bases.forEach(base => counts.set(base, (counts.get(base) ?? 0) + 1))
  const labels = nodes.map((node, index) => {
    const base = bases[index]
    if (counts.get(base) === 1) return base
    const peers = nodes.filter((_, peerIndex) => bases[peerIndex] === base && peerIndex !== index)
    let length = 4
    while (length < node.id.length && peers.some(peer => peer.id.slice(-length) === node.id.slice(-length))) length++
    return `${base} ·${node.id.slice(-length)}`
  })
  // A literal title can itself resemble a generated suffix. If that happens,
  // use deterministic ordinals for every node rather than showing duplicates.
  if (new Set(labels).size !== labels.length) {
    const orderedIds = [...nodes].map(node => node.id).sort()
    return new Map(nodes.map((node, index) => [node.id, `${bases[index]} ·${orderedIds.indexOf(node.id) + 1}`]))
  }
  return new Map(nodes.map((node, index) => [node.id, labels[index]]))
}
