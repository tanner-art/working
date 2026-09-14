import type { CanvasElement, ObjectKind, ObjectStatus, ThoughtObject } from './domain'
import { hasConfirmation } from './migration'

export { hasConfirmation } from './migration'

export const activeObjects = (objects: ThoughtObject[]) =>
  objects.filter(item => item.status !== 'archived')

export const confirmedActions = (objects: ThoughtObject[]) =>
  activeObjects(objects)
    .filter(item => item.kind === 'action' && item.status === 'confirmed' && hasConfirmation(item))
    .sort((left, right) => focusScore(right) - focusScore(left))

/** Legacy calendar surface cannot project CalendarEvents yet. An unscheduled promise is not fixed time. */
export const fixedCommitments = (_objects: ThoughtObject[]): ThoughtObject[] => []

export const recentObjects = (objects: ThoughtObject[], limit = 6) =>
  activeObjects(objects)
    .slice()
    .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))
    .slice(0, limit)

/** The dedicated Review gesture authorizes only the displayed classification and summary. */
export function confirmObject(object: ThoughtObject, kind: ObjectKind = object.kind): ThoughtObject {
  if (kind !== object.kind) return setObjectKind(object, kind)
  if (kind === 'reminder' || (object.status === 'confirmed' && hasConfirmation(object))) return object
  return { ...object, status: 'confirmed', history: [...object.history, {
    at: new Date().toISOString(), event: `Confirmed as ${kind}`,
    confirmation: { objectId: object.id, transition: kind, summary: object.interpretation.summary, source: 'review-confirmation' }
  }] }
}

export function updateObject(original: ThoughtObject, draft: ThoughtObject): ThoughtObject {
  const status = draft.kind !== original.kind ? 'review' : compatibleStatus(original, draft.status)
  const changes = describeChanges(original, { ...draft, status })
  // A generic save accepts editable fields only. It cannot import a draft's gesture/history or source evidence.
  return withHistory({ ...original, kind: draft.kind, context: draft.context, metadata: draft.metadata, status },
    changes.length ? `Edited ${changes.join(', ')}` : 'Edited')
}

export function setObjectStatus(object: ThoughtObject, status: ObjectStatus): ThoughtObject {
  const safeStatus = compatibleStatus(object, status)
  return withHistory({ ...object, status: safeStatus }, safeStatus === status ? `Marked ${status}` : `Kept in review; ${status} requires confirmation`)
}

function compatibleStatus(object: ThoughtObject, status: ObjectStatus): ObjectStatus {
  return (['complete', 'archived'].includes(object.status) && status === 'confirmed') || object.status === 'review' || object.status === 'inbox' ||
    ((object.kind === 'action' || object.kind === 'commitment') && !hasConfirmation(object)) ? 'review' : status
}

export function setObjectKind(object: ThoughtObject, kind: ObjectKind): ThoughtObject {
  return { ...object, kind, status: 'review', history: [...object.history, {
    at: new Date().toISOString(), event: `Changed type to ${kind}`, reviewDecision: 'superseded'
  }] }
}

/** Withdraw only this item's current interpretation. Never claim to undo external effects. */
export function reverseObject(object: ThoughtObject, decision: 'rejected' | 'reversed' = 'reversed'): ThoughtObject {
  return { ...object, status: 'review', history: [...object.history, {
    at: new Date().toISOString(), event: decision === 'rejected' ? 'Rejected interpretation; retained for review' : 'Reversed confirmation; external effects unchanged',
    reviewDecision: decision
  }] }
}

export function canvasObjectDraft(element: CanvasElement) {
  const originalContent = element.text
  if (!originalContent?.trim() || element.type === 'arrow') return null
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
  if ((original.context ?? '') !== (draft.context ?? '')) changes.push('context')
  if ((original.metadata.deadline ?? '') !== (draft.metadata.deadline ?? '')) changes.push('deadline')
  if ((original.metadata.effort ?? '') !== (draft.metadata.effort ?? '')) changes.push('effort')
  if ((original.metadata.attentionLoad ?? '') !== (draft.metadata.attentionLoad ?? '')) changes.push('attention load')
  if ((original.metadata.strategicImportance ?? '') !== (draft.metadata.strategicImportance ?? '')) changes.push('importance')
  if ((original.metadata.urgency ?? '') !== (draft.metadata.urgency ?? '')) changes.push('urgency')
  if ((original.metadata.resourceCost ?? '') !== (draft.metadata.resourceCost ?? '')) changes.push('resource cost')
  if ((original.metadata.roi ?? '') !== (draft.metadata.roi ?? '')) changes.push('ROI')
  return changes
}
