import type { ThoughtObject } from './domain'

export function unresolvedDependencies(object: ThoughtObject, objects: ThoughtObject[]) {
  return object.relationships.filter(link => link.type === 'depends_on' &&
    objects.find(item => item.id === link.targetId)?.status !== 'complete')
}

export function dependencyCandidates(object: ThoughtObject, objects: ThoughtObject[]) {
  const byId = new Map(objects.map(item => [item.id, item]))
  const wouldCycle = (id: string) => {
    const pending = [id]
    const seen = new Set<string>()
    while (pending.length) {
      const next = pending.pop()!
      if (next === object.id) return true
      if (seen.has(next)) continue
      seen.add(next)
      pending.push(...(byId.get(next)?.relationships.filter(link => link.type === 'depends_on').map(link => link.targetId) ?? []))
    }
    return false
  }
  return objects.filter(item => item.status !== 'archived' &&
    (item.kind === 'action' || item.kind === 'project' || item.kind === 'commitment') &&
    !object.relationships.some(link => link.type === 'depends_on' && link.targetId === item.id) &&
    !wouldCycle(item.id))
}
