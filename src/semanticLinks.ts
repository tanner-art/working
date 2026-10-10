import type { AppState, SemanticRelationship, ThoughtObject } from './domain'
import { serializeState } from './store'

export interface ConnectionNode { id: string; label: string; kind: string }
export interface ConnectionGraph { candidates: ConnectionNode[]; nodes: ConnectionNode[]; links: { id: string; sourceId: string; targetId: string }[]; hiddenCount: number }

const connectable = (state: AppState) => {
  const model = serializeState(state)
  const latest = new Map(model.interpretations.map(reading => [reading.legacy.id, reading]))
  const objects = new Map(model.semanticObjects.map(object => [object.id, object]))
  const accepted = new Set([...latest.values()].filter(reading => reading.reviewState === 'accepted')
    .filter(reading => ['confirmed', 'complete'].includes(objects.get(reading.legacy.id)?.status ?? ''))
    .map(reading => reading.legacy.id))
  return { model, accepted }
}

/** Only a user's recorded semantic gesture can enter this graph. Canvas geometry and
 * imported legacy relationship hints are deliberately excluded. */
export function confirmedConnectionGraph(state: AppState): ConnectionGraph {
  const { model, accepted } = connectable(state)
  const confirmed = model.relationships.filter(link => link.provenance.evidence === 'user-confirmed')
  const links = confirmed.filter(link =>
    accepted.has(link.sourceId) && accepted.has(link.targetId))
    .map(link => ({ id: link.id, sourceId: link.sourceId, targetId: link.targetId }))
  const visible = new Set(links.flatMap(link => [link.sourceId, link.targetId]))
  const rawCandidates = state.objects.filter(item => accepted.has(item.id)).map(item => ({ id: item.id,
    label: item.interpretation.summary || item.currentContent || item.originalContent, kind: item.kind }))
  const labelCounts = new Map<string, number>()
  for (const node of rawCandidates) labelCounts.set(node.label, (labelCounts.get(node.label) ?? 0) + 1)
  const candidates = rawCandidates.map(node => {
    if (labelCounts.get(node.label) === 1) return node
    const peers = rawCandidates.filter(other => other.label === node.label && other.id !== node.id)
    let length = 4
    while (length < node.id.length && peers.some(other => other.id.slice(-length) === node.id.slice(-length))) length++
    return { ...node, label: `${node.label} (${node.kind} ${node.id.slice(-length)})` }
  })
  const nodes = candidates.filter(item => visible.has(item.id))
  return { candidates, nodes, links, hiddenCount: confirmed.length - links.length }
}

export function safeConnectionGraph(state: AppState): { graph?: ConnectionGraph; unavailable: boolean } {
  try { return { graph: confirmedConnectionGraph(state), unavailable: false } }
  catch { return { unavailable: true } }
}

export function connectThoughts(state: AppState, sourceId: string, targetId: string,
  gestureId: string = crypto.randomUUID(), at = new Date().toISOString()): AppState {
  const { model, accepted } = connectable(state)
  if (!accepted.has(sourceId) || !accepted.has(targetId) || sourceId === targetId || !gestureId ||
    !Number.isFinite(Date.parse(at))) throw Error('Choose two resolved thoughts to connect.')
  if (model.relationships.some((link: SemanticRelationship) => link.provenance.evidence === 'user-confirmed' &&
    ((link.sourceId === sourceId && link.targetId === targetId) ||
      (link.sourceId === targetId && link.targetId === sourceId)))) throw Error('These thoughts are already connected.')
  if (model.relationships.some(link => link.provenance.gestureId === gestureId)) throw Error('This connection was already recorded.')
  const objects: ThoughtObject[] = state.objects.map(item => item.id !== sourceId ? item : {
    ...item, history: [...item.history, { at, event: 'Connected thoughts',
      relationshipConfirmation: { id: gestureId, targetId, type: 'relates_to' as const, source: 'user-confirmed-link' as const } }],
  })
  const updated = { ...state, objects }
  // Validate the entire resulting canonical model before publishing the optimistic UI update.
  serializeState(updated)
  return updated
}

export function removeThoughtConnection(state: AppState, relationshipId: string,
  decisionId: string = crypto.randomUUID(), at = new Date().toISOString()): AppState {
  const { model } = connectable(state)
  const link = model.relationships.find(candidate => candidate.id === relationshipId &&
    candidate.provenance.evidence === 'user-confirmed')
  if (!link?.provenance.gestureId || !decisionId || !Number.isFinite(Date.parse(at))) {
    throw Error('This confirmed connection is no longer available to remove.')
  }
  const objects: ThoughtObject[] = state.objects.map(item => item.id !== link.sourceId ? item : {
    ...item, history: [...item.history, { at, event: 'Removed connection',
      relationshipReversal: { id: decisionId, reverses: link.provenance.gestureId!, targetId: link.targetId,
        source: 'user-reversed-link' as const } }],
  })
  const updated = { ...state, objects }
  serializeState(updated)
  return updated
}
