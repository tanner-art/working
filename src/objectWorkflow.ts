import type { CanvasElement, ObjectKind, ObjectStatus, ThoughtObject } from './domain'

export const activeObjects = (objects: ThoughtObject[]) =>
  objects.filter(item => item.status !== 'archived')

export const confirmedActions = (objects: ThoughtObject[]) =>
  activeObjects(objects)
    .filter(item => item.kind === 'action' && item.status === 'confirmed')
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
  return withHistory({ ...object, kind, status: 'confirmed', confidence: 1 }, `Confirmed as ${kind}`)
}

export function updateObject(original: ThoughtObject, draft: ThoughtObject): ThoughtObject {
  const changes = describeChanges(original, draft)
  return withHistory(draft, changes.length ? `Edited ${changes.join(', ')}` : 'Edited')
}

export function setObjectStatus(object: ThoughtObject, status: ObjectStatus): ThoughtObject {
  return withHistory({ ...object, status }, `Marked ${status}`)
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
  return importance * 4 + urgency * 3 + effort + attention
}

function withHistory(object: ThoughtObject, event: string): ThoughtObject {
  return { ...object, history: [...object.history, { at: new Date().toISOString(), event }] }
}

function describeChanges(original: ThoughtObject, draft: ThoughtObject) {
  const changes: string[] = []
  if (original.kind !== draft.kind) changes.push(`type to ${draft.kind}`)
  if (original.status !== draft.status) changes.push(`status to ${draft.status}`)
  if ((original.context ?? '') !== (draft.context ?? '')) changes.push('context')
  if ((original.metadata.deadline ?? '') !== (draft.metadata.deadline ?? '')) changes.push('deadline')
  if ((original.metadata.effort ?? '') !== (draft.metadata.effort ?? '')) changes.push('effort')
  if ((original.metadata.attentionLoad ?? '') !== (draft.metadata.attentionLoad ?? '')) changes.push('attention load')
  if ((original.metadata.strategicImportance ?? '') !== (draft.metadata.strategicImportance ?? '')) changes.push('importance')
  return changes
}
