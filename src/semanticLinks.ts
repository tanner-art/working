import type { AppState, SemanticRelationship, ThoughtObject } from './domain'
import { serializeState } from './store'

export interface ConnectionNode { id: string; label: string; kind: string }
export interface ConnectionGraph { candidates: ConnectionNode[]; nodes: ConnectionNode[]; links: { id: string; sourceId: string; targetId: string }[] }

const connectable = (state: AppState) => {
  const model = serializeState(state)
  const latest = new Map(model.interpretations.map(reading => [reading.legacy.id, reading]))
  const accepted = new Set([...latest.values()].filter(reading => reading.reviewState === 'accepted')
    .filter(reading => model.semanticObjects.some(object => object.id === reading.legacy.id &&
      (object.status === 'confirmed' || object.status === 'complete'))).map(reading => reading.legacy.id))
  return { model, accepted }
}

/** Only a user's recorded semantic gesture can enter this graph. Canvas geometry and
 * imported legacy relationship hints are deliberately excluded. */
export function confirmedConnectionGraph(state: AppState): ConnectionGraph {
  const { model, accepted } = connectable(state)
  const links = model.relationships.filter(link => link.provenance.evidence === 'user-confirmed' &&
    accepted.has(link.sourceId) && accepted.has(link.targetId))
    .map(link => ({ id: link.id, sourceId: link.sourceId, targetId: link.targetId }))
  const visible = new Set(links.flatMap(link => [link.sourceId, link.targetId]))
  const candidates = state.objects.filter(item => accepted.has(item.id)).map(item => ({ id: item.id,
    label: item.interpretation.summary || item.currentContent || item.originalContent, kind: item.kind }))
  const nodes = candidates.filter(item => visible.has(item.id))
  return { candidates, nodes, links }
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
