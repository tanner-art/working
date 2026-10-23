import type { CanvasElement, ObjectKind, ObjectStatus, SemanticRelationship, ThoughtObject } from './domain'
import { unresolvedDependencies } from './dependencies'
import { hasConfirmation } from './migration'

export { hasConfirmation } from './migration'

/** Review's explicit Action-staging gesture resolves classification without
 * granting execution eligibility. It also permits later user lifecycle edits. */
export function hasStagedActionResolution(object: ThoughtObject): boolean {
  if (object.kind !== 'action' || object.status === 'review' || object.status === 'inbox') return false
  const stageIndex = object.history.findIndex(entry => entry.event === 'Staged as Action' &&
    entry.actionStage?.source === 'review-action-staging' && Number.isFinite(Date.parse(entry.at)))
  return stageIndex >= 0 && !object.history.slice(stageIndex + 1).some(entry =>
    entry.reviewDecision || entry.reviewRevision || entry.event.startsWith('Changed type') ||
    entry.event === 'Marked review' || entry.event === 'Marked inbox' ||
    entry.event.includes('status to review') || entry.event.includes('status to inbox'))
}

export const activeObjects = (objects: ThoughtObject[]) =>
  objects.filter(item => item.status !== 'archived')

/** Rejected proposals retain their evidence but leave the pending decisions queue. */
export const reviewObjects = (objects: ThoughtObject[]) => objects.filter(item =>
  item.status === 'review' && !hasCreatedReminderInstruction(item) &&
  item.history.slice().reverse().find(entry => entry.reviewDecision || entry.confirmation)?.reviewDecision !== 'rejected')

/** Ideas are visible only after the dedicated Review resolution completes. */
export const resolvedIdeas = (objects: ThoughtObject[]) =>
  activeObjects(objects).filter(item => item.kind === 'idea' && item.status === 'confirmed')

/** Confirmed and eligible: an unresolved `depends_on` link keeps a confirmed Action out of the queue without hiding it in a score. */
export const confirmedActions = (objects: ThoughtObject[], relationships: SemanticRelationship[] = []) =>
  activeObjects(objects)
    .filter(item => item.kind === 'action' && item.status === 'confirmed' && hasConfirmation(item) &&
      unresolvedDependencies(item, relationships, objects).length === 0)
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

/** A created Reminder instruction is append-only, including after handling or dismissal. */
export const hasCreatedReminderInstruction = (object: ThoughtObject): boolean =>
  object.history.some(entry => entry.reminderInstruction?.action === 'created')

function requireCompatibleReminderKind(object: ThoughtObject, kind: ObjectKind) {
  if (kind !== object.kind && hasCreatedReminderInstruction(object)) {
    throw new Error('This Reminder has an instruction history. Its type cannot be changed; edit its details instead.')
  }
}

export function updateObject(original: ThoughtObject, draft: ThoughtObject): ThoughtObject {
  requireCompatibleReminderKind(original, draft.kind)
  const status = draft.kind !== original.kind ? 'review' : compatibleStatus(original, draft.status)
  const changes = describeChanges(original, { ...draft, status })
  // A generic save accepts editable fields only. It cannot import a draft's gesture/history or source evidence.
  return withHistory({ ...original, kind: draft.kind, context: draft.context,
    interpretation: { ...original.interpretation, suggestedDate: draft.interpretation.suggestedDate },
    metadata: draft.metadata, status }, changes.length ? `Edited ${changes.join(', ')}` : 'Edited')
}

export function setObjectStatus(object: ThoughtObject, status: ObjectStatus): ThoughtObject {
  const safeStatus = compatibleStatus(object, status)
  return withHistory({ ...object, status: safeStatus }, safeStatus === status ? `Marked ${status}` :
    hasCreatedReminderInstruction(object) ? 'Kept resolved Reminder status; a created instruction cannot return to Review' :
    hasStagedActionResolution(object) ? 'Kept staged Action status; use Withdraw staged Action to return to Organize' :
      `Kept in review; ${status} requires confirmation`)
}

function compatibleStatus(object: ThoughtObject, status: ObjectStatus): ObjectStatus {
  if (hasCreatedReminderInstruction(object)) {
    if (object.status === 'review' || object.status === 'inbox') {
      throw new Error('This created Reminder has an invalid Review status. Its history was left unchanged; recovery needs an explicit decision.')
    }
    // A created instruction is already resolved. The generic complete/archive →
    // confirmed rule would incorrectly send it back to Review.
    return status === 'review' || status === 'inbox' ? object.status : status
  }
  if (hasStagedActionResolution(object) && (status === 'review' || status === 'inbox' ||
    (['complete', 'archived'].includes(object.status) && status === 'confirmed'))) return object.status
  return (['complete', 'archived'].includes(object.status) && status === 'confirmed') || object.status === 'review' || object.status === 'inbox' ||
    ((object.kind === 'action' || object.kind === 'commitment') && !hasConfirmation(object) && !hasStagedActionResolution(object)) ? 'review' : status
}

export function setObjectKind(object: ThoughtObject, kind: ObjectKind): ThoughtObject {
  requireCompatibleReminderKind(object, kind)
  if (hasCreatedReminderInstruction(object) && kind === object.kind) return object
  return { ...object, kind, status: 'review', history: [...object.history, {
    at: new Date().toISOString(), event: `Changed type to ${kind}`, reviewDecision: 'superseded'
  }] }
}

/** Withdraw only this item's current interpretation. Never claim to undo external effects. */
export function reverseObject(object: ThoughtObject, decision: 'rejected' | 'reversed' = 'reversed'): ThoughtObject {
  if (hasCreatedReminderInstruction(object)) {
    throw new Error('A created Reminder instruction cannot return to Review. Its history was left unchanged.')
  }
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
      rationale: 'Captured from canvas; review before turning spatial thought into structure.',
      method: 'built-in' as const,
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
  if ((original.interpretation.suggestedDate ?? '') !== (draft.interpretation.suggestedDate ?? '')) changes.push('time')
  if ((original.metadata.effort ?? '') !== (draft.metadata.effort ?? '')) changes.push('effort')
  if ((original.metadata.attentionLoad ?? '') !== (draft.metadata.attentionLoad ?? '')) changes.push('attention load')
  if ((original.metadata.strategicImportance ?? '') !== (draft.metadata.strategicImportance ?? '')) changes.push('importance')
  if ((original.metadata.urgency ?? '') !== (draft.metadata.urgency ?? '')) changes.push('urgency')
  if ((original.metadata.resourceCost ?? '') !== (draft.metadata.resourceCost ?? '')) changes.push('resource cost')
  if ((original.metadata.roi ?? '') !== (draft.metadata.roi ?? '')) changes.push('ROI')
  return changes
}

/** Context-only views, not inferred semantic membership or a persisted folder schema. */
export const bankFolders = ['Personal', 'Business', 'Unfiled'] as const
export function bankObjects(objects: ThoughtObject[]): Record<typeof bankFolders[number], ThoughtObject[]> {
  const folders: Record<typeof bankFolders[number], ThoughtObject[]> = { Personal: [], Business: [], Unfiled: [] }
  for (const item of objects) {
    if (!['confirmed', 'complete'].includes(item.status) ||
      ((item.kind === 'action' || item.kind === 'commitment') && !hasConfirmation(item))) continue
    const context = item.context?.trim().toLowerCase()
    const folder = context === 'personal' || context === 'home' ? 'Personal'
      : context === 'business' || context === 'work' ? 'Business' : 'Unfiled'
    folders[folder].push(item)
  }
  return folders
}
