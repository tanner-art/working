import { useState } from 'react'
import type { ThoughtObject } from './domain'
import { reviewResolutionKinds, resolveReviewCapture, type ReviewContinuations, type ReviewResolutionKind } from './reviewResolution'

const labels: Record<ReviewResolutionKind, string> = {
  action: 'Action', commitment: 'Commitment', reminder: 'Reminder', idea: 'Idea',
}

/** The four-choice Review control; it owns no non-Idea persistence. */
export function ReviewResolution({ object, onComplete, continuations, onEdit }: {
  object: ThoughtObject
  onComplete: (object: ThoughtObject) => void
  continuations?: ReviewContinuations
  onEdit?: () => void
}) {
  const [message, setMessage] = useState('')
  const [resolving, setResolving] = useState<ReviewResolutionKind>()
  const resolve = async (kind: ReviewResolutionKind) => {
    setMessage('')
    setResolving(kind)
    const result = await resolveReviewCapture(object, kind, continuations)
    setResolving(undefined)
    if (result.status === 'completed') onComplete(result.object)
    else setMessage(result.message)
  }
  return <div className="review-resolution" role="group" aria-label="Resolve capture">
    <p>Resolve this capture as:</p>
    <div className="review-actions">{reviewResolutionKinds.map(kind => <button key={kind} type="button" className={kind === 'idea' ? 'primary' : 'secondary'} disabled={!!resolving} onClick={() => void resolve(kind)}>{resolving === kind ? 'Resolving…' : labels[kind]}</button>)}{onEdit && <button type="button" className="secondary edit-thought-button" disabled={!!resolving} onClick={onEdit}>Edit thought</button>}</div>
    {message && <p role="alert">{message}</p>}
  </div>
}
