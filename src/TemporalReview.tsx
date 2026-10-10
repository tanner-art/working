import { useState } from 'react'
import type { AppState, PersistedState, TemporalDecision, TemporalTarget } from './domain'
import { reconcileCurrentSession } from './store'
import { activeTemporalDecisions, deadlineProposal, eventProposal, temporalFactIsCurrent } from './temporalConfirmation'
import { decideTemporalReview } from './temporalReviewWorkflow'

export function TemporalReview({ state, onUpdate, readAccountModel, readDecisionModel, decisionBlocked }: { state: AppState; onUpdate: (fn: (current: AppState) => AppState) => void; readAccountModel?: (current: AppState) => PersistedState; readDecisionModel?: (current: AppState) => PersistedState; decisionBlocked?: string }) {
  const [message, setMessage] = useState('')
  let model: PersistedState
  let projectionError = ''
  try { model = readAccountModel?.(state) ?? reconcileCurrentSession(state) }
  catch { model = state.model!; projectionError = 'Showing the last loaded Timing review while account changes are unsaved. Retry saving or download a backup.' }
  if (!model) return <section className="page" aria-label="Timing review"><h2>Confirm timing separately</h2><p role="status">Timing review is temporarily unavailable. Your edits remain in this tab.</p></section>
  const decisionIssue = [decisionBlocked, projectionError].filter(Boolean).join(' ')
  const decide = (target: TemporalTarget, prior?: TemporalDecision) => {
    setMessage('')
    try { onUpdate(current => decideTemporalReview(current, target, prior, readDecisionModel?.(current))) }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Timing could not be confirmed. Retry saving or download a backup.') }
  }
  const active = activeTemporalDecisions(model)
  const proposals = [
    ...model.semanticObjects.map(o => deadlineProposal(model, o.id)),
    ...model.calendarEvents.map(e => eventProposal(model, e.id))
  ].filter((p): p is Exclude<TemporalTarget, { kind: 'direct-calendar-event' }> => !!p)
  return <section className="page" aria-label="Timing review">
    <h2>Confirm timing separately</h2>
    <p>Each confirmation fixes only the date or event shown. It does not confirm work or an obligation. Dates without a time remain date-only deadlines.</p>
    {decisionIssue && <p role="status">{decisionIssue} Your edits remain in this tab.</p>}
    {message && <p role="alert">{message}</p>}
    {!proposals.length && <p>No supported timing proposals. Confirm an object’s meaning to review its proposed deadline. Events need an explicit start time, temporal context and captured interpretation; event creation is not available here.</p>}
    <div className="review-list">{proposals.map(target => {
      const prior = active.find(e => e.target.kind === target.kind && (e.target.kind === 'fixed-deadline' && target.kind === 'fixed-deadline'
        ? e.target.objectId === target.objectId : e.target.kind === 'event-scheduling' && target.kind === 'event-scheduling' && e.target.eventId === target.eventId))
      const reading = model.interpretations.find(i => i.id === target.interpretationId)!
      const label = target.kind === 'fixed-deadline' ? model.semanticObjects.find(o => o.id === target.objectId)!.summary : target.title
      return <article className="review-card" key={target.kind === 'fixed-deadline' ? `deadline:${target.objectId}` : `event:${target.eventId}`}>
        <h3>{label}</h3>
        <p>{target.kind === 'fixed-deadline' ? `Fixed deadline: ${target.date} (date only)` : `Schedule event: ${target.startsAt} · ${target.temporalContext}`}</p>
        <small>Interpretation: {reading.summary}</small>
        <blockquote>{model.captures.find(c => c.id === reading.captureIds[0])?.originalContent}</blockquote>
        {target.kind === 'event-scheduling' && <p>Linked objects: {target.objectIds.map(id => model.semanticObjects.find(o => o.id === id)?.summary).join(', ') || 'None'}. Scheduling does not confirm these obligations.</p>}
        {prior && <p>{temporalFactIsCurrent(model, prior) ? 'Timing confirmed' : 'Proposal changed — reverse the earlier confirmation before confirming this date'} · {prior.target.kind === 'fixed-deadline' ? prior.target.date : prior.target.startsAt} · <time>{prior.at}</time></p>}
        <button className="secondary" disabled={!!decisionIssue} onClick={() => decide(prior?.target ?? target, prior)}>
          {prior ? target.kind === 'fixed-deadline' ? 'Reverse fixed deadline' : 'Reverse event scheduling' : target.kind === 'fixed-deadline' ? 'Confirm fixed deadline' : 'Confirm event scheduling'}
        </button>
      </article>
    })}</div>
    {active.filter(e => !proposals.some(p => p.kind === e.target.kind && (p.kind === 'fixed-deadline' && e.target.kind === 'fixed-deadline' ? p.objectId === e.target.objectId : p.kind === 'event-scheduling' && e.target.kind === 'event-scheduling' && p.eventId === e.target.eventId))).map(entry => <article className="review-card" key={entry.id}>
      <p>Earlier timing confirmation: {entry.target.kind === 'fixed-deadline' ? `${entry.target.objectId} · ${entry.target.date}` : `${entry.target.title} · ${entry.target.startsAt}`} · {entry.at}</p>
      <button className="secondary" disabled={!!decisionIssue} onClick={() => decide(entry.target, entry)}>Reverse earlier timing confirmation</button>
    </article>)}
  </section>
}
