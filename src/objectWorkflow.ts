import type { CanvasElement, ObjectKind, ObjectStatus, ThoughtObject } from './domain'
import { unresolvedDependencies } from './dependencies'

export const activeObjects = (objects: ThoughtObject[]) =>
  objects.filter(item => item.status !== 'archived')

export const confirmedActions = (objects: ThoughtObject[]) =>
  activeObjects(objects)
    .filter(item => item.kind === 'action' && item.status === 'confirmed' && unresolvedDependencies(item, objects).length === 0)
    .sort((left, right) => focusScore(right) - focusScore(left))

export const fixedCommitments = (objects: ThoughtObject[]) =>
  activeObjects(objects).filter(item =>
    (item.kind === 'commitment' || item.kind === 'reminder') && item.status === 'confirmed'
  )

export const recentObjects = (objects: ThoughtObject[], limit = 6) =>
  activeObjects(objects)
    .slice()
    .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))
    .slice(0, limit)

export function confirmObject(object: ThoughtObject, kind: ObjectKind = object.kind): ThoughtObject {
  return withHistory({ ...object, kind, status: 'confirmed' }, `Confirmed as ${kind}`)
}

export function updateObject(original: ThoughtObject, draft: ThoughtObject): ThoughtObject {
  const changes = describeChanges(original, draft)
  return withHistory(draft, changes.length ? `Edited ${changes.join(', ')}` : 'Edited')
}

export function setObjectStatus(object: ThoughtObject, status: ObjectStatus): ThoughtObject {
  return withHistory({ ...object, status }, `Marked ${status}`)
}

export function setObjectKind(object: ThoughtObject, kind: ObjectKind): ThoughtObject {
  return withHistory({ ...object, kind }, `Changed type to ${kind}`)
}

export function setBelongsTo(object: ThoughtObject, targetId?: string): ThoughtObject {
  const relationships = object.relationships.filter(item => item.type !== 'belongs_to')
  const next = targetId ? [...relationships, { targetId, type: 'belongs_to' as const }] : relationships
  return withHistory({ ...object, relationships: next }, targetId ? 'Linked to parent' : 'Cleared parent link')
}

export function parentCandidates(objects: ThoughtObject[], objectId: string) {
  const byId = new Map(objects.map(item => [item.id, item]))
  const hasUnsafeAncestry = (candidateId: string) => {
    const visiting = new Set<string>()
    const checked = new Set<string>()
    const visit = (id: string): boolean => {
      if (id === objectId || visiting.has(id)) return true
      if (checked.has(id)) return false
      visiting.add(id)
      const unsafe = byId.get(id)?.relationships.some(link => link.type === 'belongs_to' && visit(link.targetId)) ?? false
      visiting.delete(id)
      checked.add(id)
      return unsafe
    }
    return visit(candidateId)
  }
  return activeObjects(objects).filter(item =>
    (item.kind === 'project' || item.kind === 'objective') && !hasUnsafeAncestry(item.id)
  )
}

export function parentObject(objects: ThoughtObject[], object: ThoughtObject) {
  const parentId = object.relationships.find(item => item.type === 'belongs_to')?.targetId
  return parentId ? activeObjects(objects).find(item => item.id === parentId) : undefined
}

export function projectChildren(objects: ThoughtObject[], parentId: string) {
  return activeObjects(objects).filter(item => item.id !== parentId && item.relationships.some(link => link.type === 'belongs_to' && link.targetId === parentId))
}

export function canvasObjectDraft(element: CanvasElement) {
  const originalContent = element.text?.trim()
  if (!originalContent || element.type === 'arrow') return null
  return {
    kind: 'idea' as ObjectKind,
    originalContent,
    source: 'canvas' as const,
    confidence: .72,
    interpretation: {
      summary: originalContent.length > 84 ? `${originalContent.slice(0, 81)}...` : originalContent,
      suggestedKind: 'idea' as ObjectKind,
      rationale: 'Captured from canvas; review before turning spatial thought into structure.'
    }
  }
}

function focusScore(object: ThoughtObject) {
  const importance = object.metadata.strategicImportance ?? 3
  const urgency = object.metadata.urgency ?? 3
  const effort = object.metadata.effort === 'small' ? 2 : object.metadata.effort === 'medium' ? 1 : 0
  const attention = object.metadata.attentionLoad === 'low' ? 2 : object.metadata.attentionLoad === 'medium' ? 1 : 0
  const roi = object.metadata.roi ?? 3
  const resourceCost = object.metadata.resourceCost === 'low' ? 2 : object.metadata.resourceCost === 'medium' ? 1 : 0
  return importance * 4 + urgency * 3 + roi * 2 + effort + attention + resourceCost
}

function withHistory(object: ThoughtObject, event: string): ThoughtObject {
  return { ...object, history: [...object.history, { at: new Date().toISOString(), event }] }
}

function describeChanges(original: ThoughtObject, draft: ThoughtObject) {
  const changes: string[] = []
  if (original.kind !== draft.kind) changes.push(`type to ${draft.kind}`)
  if (original.status !== draft.status) changes.push(`status to ${draft.status}`)
  const dependencyIds = (item: ThoughtObject) => item.relationships.filter(link => link.type === 'depends_on').map(link => link.targetId).sort().join('\n')
  if (dependencyIds(original) !== dependencyIds(draft)) changes.push('dependencies')
  if ((original.context ?? '') !== (draft.context ?? '')) changes.push('context')
  if ((original.metadata.deadline ?? '') !== (draft.metadata.deadline ?? '')) changes.push('deadline')
  if ((original.metadata.effort ?? '') !== (draft.metadata.effort ?? '')) changes.push('effort')
  if ((original.metadata.attentionLoad ?? '') !== (draft.metadata.attentionLoad ?? '')) changes.push('attention load')
  if ((original.metadata.strategicImportance ?? '') !== (draft.metadata.strategicImportance ?? '')) changes.push('importance')
  if ((original.metadata.urgency ?? '') !== (draft.metadata.urgency ?? '')) changes.push('urgency')
  if ((original.metadata.resourceCost ?? '') !== (draft.metadata.resourceCost ?? '')) changes.push('resource cost')
  if ((original.metadata.roi ?? '') !== (draft.metadata.roi ?? '')) changes.push('ROI')
  if ((original.relationships.find(item => item.type === 'belongs_to')?.targetId ?? '') !== (draft.relationships.find(item => item.type === 'belongs_to')?.targetId ?? '')) changes.push('parent link')
  return changes
}
