import { useState } from 'react'
import type { SemanticObject, ThoughtObject } from './domain'
import { reviewResolutionKinds, resolveReviewCapture, type ReviewContinuations, type ReviewResolutionKind } from './reviewResolution'
import { ReminderResolution } from './ReminderResolution'
import type { ReminderChoice } from './reminderWorkflow'
import { CommitmentResolution } from './CommitmentResolution'
import { useSearchHandoffGuard } from './useSearchHandoffGuard'
import type { RegisterSearchHandoffGuard } from './searchHandoffGuards'

const labels: Record<ReviewResolutionKind, string> = {
  action: 'Action', commitment: 'Commitment', reminder: 'Reminder', idea: 'Idea',
}

/** The four-choice Review control; it owns no non-Idea persistence. */
export function ReviewResolution({ registerSearchHandoffGuard, object, onComplete, continuations, onEdit, reminderTargets = [], onResolveReminder }: {
  registerSearchHandoffGuard?: RegisterSearchHandoffGuard
  object: ThoughtObject
  onComplete: (object: ThoughtObject) => void
  continuations?: ReviewContinuations
  onEdit?: () => void
  reminderTargets?: readonly SemanticObject[]
  onResolveReminder?: (objectId: string, choice: ReminderChoice) => void
}) {
  const [message, setMessage] = useState('')
  const [resolving, setResolving] = useState<ReviewResolutionKind>()
  const [reminderSetup, setReminderSetup] = useState(false)
  const [commitmentSetup, setCommitmentSetup] = useState(false)
  useSearchHandoffGuard(registerSearchHandoffGuard, `review:${object.id}`, () => !resolving && !reminderSetup && !commitmentSetup)
  const resolve = async (kind: ReviewResolutionKind) => {
    setMessage('')
    setResolving(kind)
    const result = await resolveReviewCapture(object, kind, continuations)
    setResolving(undefined)
    if (result.status === 'completed') onComplete(result.object)
    else if (result.status === 'needs-input' && kind === 'commitment') { setCommitmentSetup(true); setMessage('') }
    else if (result.status === 'needs-input' && kind === 'reminder' && onResolveReminder) { setReminderSetup(true); setMessage('') }
    else setMessage(result.message)
  }
  return <div className="review-resolution" role="group" aria-label="Resolve capture">
    <p>Resolve this capture as:</p>
    {!reminderSetup && !commitmentSetup && <div className="review-actions">{reviewResolutionKinds.map(kind => <button key={kind} type="button" className={kind === 'idea' ? 'primary' : 'secondary'} disabled={!!resolving} onClick={() => void resolve(kind)}>{resolving === kind ? 'Resolving…' : labels[kind]}</button>)}{onEdit && <button type="button" className="secondary edit-thought-button" disabled={!!resolving} onClick={onEdit}>Edit thought</button>}</div>}
    {reminderSetup && onResolveReminder && <ReminderResolution object={object} targets={reminderTargets} onResolve={choice => { try { onResolveReminder(object.id, choice) } catch (error) { setMessage((error as Error).message) } }} onCancel={() => setReminderSetup(false)} />}
    {commitmentSetup && <CommitmentResolution object={object} dependencies={reminderTargets} onResolve={onComplete} onCancel={() => setCommitmentSetup(false)} />}
    {message && <p role="alert">{message}</p>}
  </div>
}
