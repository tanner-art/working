import type { SemanticRelationship, ThoughtObject } from './domain'

/** `depends_on` links are graph constraints, not scores; unresolved ones must surface, not hide. */
export function unresolvedDependencies(object: ThoughtObject, relationships: SemanticRelationship[], objects: ThoughtObject[]): SemanticRelationship[] {
  return relationships.filter(link => link.sourceId === object.id && link.type === 'depends_on' &&
    objects.find(item => item.id === link.targetId)?.status !== 'complete')
}

/** Cycle-safe candidates to add as a prerequisite of `object`, walking explicit sourceId/targetId edges. */
export function dependencyCandidates(object: ThoughtObject, relationships: SemanticRelationship[], objects: ThoughtObject[]): ThoughtObject[] {
  const dependsOnEdges = relationships.filter(link => link.type === 'depends_on')
  const outgoing = new Map<string, string[]>()
  for (const link of dependsOnEdges) outgoing.set(link.sourceId, [...(outgoing.get(link.sourceId) ?? []), link.targetId])
  const wouldCycle = (id: string) => {
    const pending = [id]
    const seen = new Set<string>()
    while (pending.length) {
      const next = pending.pop()!
      if (next === object.id) return true
      if (seen.has(next)) continue
      seen.add(next)
      pending.push(...(outgoing.get(next) ?? []))
    }
    return false
  }
  const existing = new Set(dependsOnEdges.filter(link => link.sourceId === object.id).map(link => link.targetId))
  return objects.filter(item => item.status !== 'archived' &&
    (item.kind === 'action' || item.kind === 'project' || item.kind === 'commitment') &&
    !existing.has(item.id) && !wouldCycle(item.id))
}
