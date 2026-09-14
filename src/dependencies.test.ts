import { describe, expect, it } from 'vitest'
import type { ObjectKind, ObjectStatus, SemanticRelationship, ThoughtObject } from './domain'
import { dependencyCandidates, unresolvedDependencies } from './dependencies'
import { confirmObject, confirmedActions } from './objectWorkflow'

const thought = (id: string, patch: Partial<ThoughtObject> = {}): ThoughtObject => ({
  id, originalContent: `content:${id}`, source: 'text', createdAt: '2026-09-14T10:00:00Z',
  kind: 'action', confidence: .9, status: 'review',
  interpretation: { summary: `summary:${id}`, suggestedKind: 'action', rationale: 'because' },
  metadata: {}, history: [{ at: '2026-09-14T10:00:00Z', event: 'Captured' }], relationships: [], ...patch
})

let relCounter = 0
const rel = (sourceId: string, targetId: string, type: SemanticRelationship['type'] = 'depends_on'): SemanticRelationship => ({
  id: `relationship:${relCounter++}`, sourceId, targetId, type, scope: 'semantic',
  provenance: { interpretationId: `interpretation:${sourceId}:1`, evidence: 'legacy-unverified' }
})

describe('unresolvedDependencies', () => {
  it('reports a depends_on link whose target is not complete', () => {
    const objects = [thought('a'), thought('b', { status: 'confirmed' })]
    const relationships = [rel('a', 'b')]
    expect(unresolvedDependencies(objects[0], relationships, objects)).toHaveLength(1)
  })

  it('excludes a depends_on link once its target is complete', () => {
    const objects = [thought('a'), thought('b', { kind: 'idea', status: 'complete' })]
    const relationships = [rel('a', 'b')]
    expect(unresolvedDependencies(objects[0], relationships, objects)).toEqual([])
  })

  it('treats a dependency on a missing/removed target as unresolved rather than silently satisfied', () => {
    const objects = [thought('a')]
    const relationships = [rel('a', 'ghost')]
    expect(unresolvedDependencies(objects[0], relationships, objects)).toHaveLength(1)
  })

  it('ignores non-depends_on relationship types', () => {
    const objects = [thought('a'), thought('b', { status: 'confirmed' })]
    const relationships = [rel('a', 'b', 'relates_to'), rel('a', 'b', 'supports'), rel('a', 'b', 'belongs_to')]
    expect(unresolvedDependencies(objects[0], relationships, objects)).toEqual([])
  })

  it('respects relationship direction: an incoming depends_on link (others depend on this object) is not this object\'s own dependency', () => {
    const objects = [thought('a'), thought('b')]
    // b depends on a; from a's perspective this is not something a depends on.
    const relationships = [rel('b', 'a')]
    expect(unresolvedDependencies(objects[0], relationships, objects)).toEqual([])
    expect(unresolvedDependencies(objects[1], relationships, objects)).toHaveLength(1)
  })
})

describe('dependencyCandidates', () => {
  it('excludes a direct cycle: if B depends on A, A cannot also depend on B', () => {
    const a = thought('a')
    const b = thought('b')
    const objects = [a, b]
    const relationships = [rel('b', 'a')]
    expect(dependencyCandidates(a, relationships, objects).map(o => o.id)).not.toContain('b')
  })

  it('excludes an indirect/transitive cycle: if C depends on B depends on A, A cannot depend on C', () => {
    const a = thought('a')
    const b = thought('b')
    const c = thought('c')
    const objects = [a, b, c]
    const relationships = [rel('c', 'b'), rel('b', 'a')]
    expect(dependencyCandidates(a, relationships, objects).map(o => o.id)).not.toContain('c')
    // b is a direct dependent of a's chain too (b -> a would still be reachable) so it must also be excluded.
    expect(dependencyCandidates(a, relationships, objects).map(o => o.id)).not.toContain('b')
  })

  it('excludes an object depending on itself', () => {
    const a = thought('a')
    const objects = [a]
    expect(dependencyCandidates(a, [], objects).map(o => o.id)).not.toContain('a')
  })

  it('excludes a target that is already a direct dependency', () => {
    const a = thought('a')
    const b = thought('b')
    const objects = [a, b]
    const relationships = [rel('a', 'b')]
    expect(dependencyCandidates(a, relationships, objects).map(o => o.id)).not.toContain('b')
  })

  it('excludes archived objects and non-work kinds, and allows unrelated eligible objects', () => {
    const a = thought('a')
    const archived = thought('archived-action', { status: 'archived' })
    const idea = thought('idea', { kind: 'idea' })
    const person = thought('person', { kind: 'person' })
    const project = thought('project', { kind: 'project' })
    const commitment = thought('commitment', { kind: 'commitment' })
    const objects = [a, archived, idea, person, project, commitment]
    const candidateIds = dependencyCandidates(a, [], objects).map(o => o.id)
    expect(candidateIds).not.toContain('archived-action')
    expect(candidateIds).not.toContain('idea')
    expect(candidateIds).not.toContain('person')
    expect(candidateIds).toContain('project')
    expect(candidateIds).toContain('commitment')
  })

  it('does not let an unrelated incoming depends_on edge block an otherwise-safe candidate', () => {
    const a = thought('a')
    const b = thought('b')
    const unrelated = thought('unrelated')
    const objects = [a, b, unrelated]
    // unrelated depends on b, but neither relates to a; b should remain a safe candidate for a.
    const relationships = [rel('unrelated', 'b')]
    expect(dependencyCandidates(a, relationships, objects).map(o => o.id)).toContain('b')
  })
})

describe('confirmedActions is dependency-aware while preserving explicit confirmation (D-009)', () => {
  const withStatus = (id: string, kind: ObjectKind, status: ObjectStatus) => thought(id, { kind, status })

  it('excludes a confirmed action with an unresolved dependency', () => {
    const blocker = withStatus('blocker', 'action', 'confirmed')
    const action = confirmObject(thought('action'))
    const relationships = [rel('action', 'blocker')]
    expect(confirmedActions([action, blocker], relationships)).toEqual([])
  })

  it('includes the action once its dependency is complete', () => {
    const blocker = withStatus('blocker', 'idea', 'complete')
    const action = confirmObject(thought('action'))
    const relationships = [rel('action', 'blocker')]
    expect(confirmedActions([action, blocker], relationships).map(o => o.id)).toEqual(['action'])
  })

  it('does not resurrect an unconfirmed action just because it has no dependencies', () => {
    // Same object shape as an eligible action, but never ran through the explicit confirmation gesture.
    const unconfirmed = { ...thought('action'), status: 'confirmed' as const }
    expect(confirmedActions([unconfirmed], [])).toEqual([])
  })

  it('requires both a resolved dependency graph and an explicit confirmation gesture; either gap alone blocks eligibility', () => {
    const blocker = withStatus('blocker', 'action', 'confirmed')
    const confirmedButBlocked = confirmObject(thought('blocked-action'))
    const unconfirmedButFree = { ...thought('free-action'), status: 'confirmed' as const }
    const eligible = confirmObject(thought('eligible-action'))
    const relationships = [rel('blocked-action', 'blocker')]
    const result = confirmedActions([blocker, confirmedButBlocked, unconfirmedButFree, eligible], relationships)
    expect(result.map(o => o.id)).toEqual(['eligible-action'])
  })

  it('omits relationships entirely without throwing, defaulting to no dependency constraints', () => {
    const action = confirmObject(thought('action'))
    expect(confirmedActions([action])).toHaveLength(1)
  })
})
