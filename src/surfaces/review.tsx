import { useState } from 'react'
import type { ThoughtObject } from '../domain'
import { resolvedIdeas, reviewObjects } from '../objectWorkflow'
import { reviewResolutionKinds, resolveReviewCapture, type ReviewResolutionKind } from '../reviewResolution'

const labels: Record<ReviewResolutionKind, string> = {
  action: 'Action', commitment: 'Commitment', reminder: 'Reminder', idea: 'Idea',
}

/**
 * Review's feature-local composition. The application-shell owner mounts this
 * through the WP-11 surface boundary; this package does not edit App.tsx.
 */
export function ReviewSurface({ objects, onUpdate }: {
  objects: ThoughtObject[]
  onUpdate: (object: ThoughtObject) => void
}) {
  const pending = reviewObjects(objects)
  const ideas = resolvedIdeas(objects)
  return <section className="page" aria-label="Review">
    <h1>Review</h1>
    {!pending.length && <p>All caught up.</p>}
    <div className="review-list">{pending.map(object => <article className="review-card" key={object.id}>
      <blockquote>{object.currentContent ?? object.originalContent}</blockquote>
      <p>{object.interpretation.summary}</p>
      <SurfaceReviewResolution object={object} onComplete={onUpdate} />
    </article>)}</div>
    <section aria-labelledby="ideas-heading">
      <h2 id="ideas-heading">Ideas</h2>
      {!ideas.length && <p>No resolved ideas yet.</p>}
      <ul>{ideas.map(idea => <li key={idea.id}>{idea.currentContent ?? idea.originalContent}</li>)}</ul>
    </section>
  </section>
}

/** Kept local to avoid case-insensitive resolver ambiguity with ReviewResolution.tsx. */
function SurfaceReviewResolution({ object, onComplete }: { object: ThoughtObject; onComplete: (object: ThoughtObject) => void }) {
  const [message, setMessage] = useState('')
  const [resolving, setResolving] = useState<ReviewResolutionKind>()
  const resolve = async (kind: ReviewResolutionKind) => {
    setMessage('')
    setResolving(kind)
    const result = await resolveReviewCapture(object, kind)
    setResolving(undefined)
    if (result.status === 'completed') onComplete(result.object)
    else setMessage(result.message)
  }
  return <div className="review-resolution" role="group" aria-label="Resolve capture">
    <p>Resolve this capture as:</p>
    <div className="review-actions">{reviewResolutionKinds.map(kind => <button key={kind} type="button" className={kind === 'idea' ? 'primary' : 'secondary'} disabled={!!resolving} onClick={() => void resolve(kind)}>{resolving === kind ? 'Resolving…' : labels[kind]}</button>)}</div>
    {message && <p role="alert">{message}</p>}
  </div>
}
