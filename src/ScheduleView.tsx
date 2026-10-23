import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { AppState, PersistedState, StagedAction } from './domain'
import { reconcileCurrentSession } from './store'
import { scheduleStagedAction, setStagedActionPriority } from './actionStaging'
import { calculateAdaptivePlan, isPlanEligible, setActionPlanEligibility } from './adaptivePlan'
import { useSearchHandoffGuard } from './useSearchHandoffGuard'
import type { RegisterSearchHandoffGuard } from './searchHandoffGuards'

const localDateTimeValue = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)

function StagedActionRow({ registerSearchHandoffGuard, action, state, update, readDecisionModel, decisionBlocked, planBlocked, focus, onFocusHandled }: { registerSearchHandoffGuard?: RegisterSearchHandoffGuard; action: StagedAction; state: AppState; update: (next: (state: AppState) => AppState) => void; readDecisionModel?: (current: AppState) => PersistedState; decisionBlocked?: string; planBlocked?: boolean; focus: boolean; onFocusHandled?: () => void }) {
  const [when, setWhen] = useState(() => localDateTimeValue(new Date(Date.now() + 60 * 60_000)))
  const initialWhen = useRef(when)
  useSearchHandoffGuard(registerSearchHandoffGuard, `schedule:${action.id}`, () => action.status !== 'staged' || when === initialWhen.current)
  const [message, setMessage] = useState('')
  const row = useRef<HTMLLIElement>(null)
  useEffect(() => { if (focus && row.current) { row.current.focus(); onFocusHandled?.() } }, [focus])
  const object = state.objects.find(item => item.id === action.objectId)
  if (!object) return null
  const submit = (event: FormEvent) => {
    event.preventDefault()
    try {
      update(current => scheduleStagedAction(current, action.objectId, new Date(when).toISOString(), Intl.DateTimeFormat().resolvedOptions().timeZone || 'local time', readDecisionModel?.(current)))
      setMessage('CalendarEvent confirmed.')
    } catch (error) { setMessage((error as Error).message) }
  }
  const eligible = isPlanEligible(object)
  return <li ref={row} tabIndex={focus ? -1 : undefined}><article><h2>{object.interpretation.summary}</h2>
    <label>Priority <select aria-label={`Priority for ${object.interpretation.summary}`} value={action.priority} disabled={action.status !== 'staged'} onChange={event => {
      try {
        update(current => setStagedActionPriority(current, action.objectId, Number(event.target.value) as StagedAction['priority']))
        setMessage('Priority saved.')
      } catch (error) { setMessage((error as Error).message) }
    }}>{[1, 2, 3, 4, 5].map(priority => <option key={priority} value={priority}>{priority} of 5</option>)}</select></label>
    <p>{action.status === 'scheduled' ? 'CalendarEvent confirmed' : planBlocked ? 'Plan status unavailable until this workspace is verified' : eligible ? 'Eligible for the Adaptive Plan; still unscheduled' : 'Unscheduled staged Action'}</p>
    {action.status === 'staged' && <><button className="secondary" type="button" onClick={() => {
      try {
        update(current => setActionPlanEligibility(current, action.objectId, !eligible))
        setMessage(eligible ? 'Removed from Adaptive Plan.' : 'Added to Adaptive Plan.')
      } catch (error) { setMessage((error as Error).message) }
    }} disabled={planBlocked}>{eligible ? 'Remove from plan' : 'Add to plan'}</button>
      <form onSubmit={submit}><label>Schedule as CalendarEvent <input aria-label={`Schedule ${object.interpretation.summary}`} type="datetime-local" required value={when} onChange={event => setWhen(event.target.value)} /></label><button className="primary" type="submit" disabled={!!decisionBlocked}>Confirm CalendarEvent</button></form></>}
    {message && <p role="status">{message}</p>}
  </article></li>
}

export function ScheduleView({ registerSearchHandoffGuard, state, update, readAccountModel, readDecisionModel, decisionBlocked, focusActionId = null, onFocusHandled }: { registerSearchHandoffGuard?: RegisterSearchHandoffGuard; state: AppState; update: (next: (state: AppState) => AppState) => void; readAccountModel?: (current: AppState) => PersistedState; readDecisionModel?: (current: AppState) => PersistedState; decisionBlocked?: string; focusActionId?: string | null; onFocusHandled?: () => void }) {
  const projection = useMemo(() => {
    try { return { model: reconcileCurrentSession(state, readAccountModel?.(state)), error: '' } }
    catch { return { model: state.model, error: 'Showing the last loaded Schedule while account changes are unsaved. Retry saving or download a backup.' } }
  }, [state, readAccountModel])
  const decisionIssue = [decisionBlocked, projection.error].filter(Boolean).join(' ')
  const planProjection = useMemo(() => {
    if (projection.error || !projection.model) return { plan: null, error: 'Adaptive Plan unavailable while the current workspace cannot be verified.' }
    try { return { plan: calculateAdaptivePlan({ ...state, model: projection.model }), error: '' } }
    catch { return { plan: null, error: 'Adaptive Plan unavailable because Action evidence could not be verified.' } }
  }, [state, projection.model, projection.error])
  const plan = planProjection.plan
  const actions = (projection.model?.stagedActions ?? []).filter(action => action.status !== 'reversed' &&
    state.objects.some(object => object.id === action.objectId && object.status === 'confirmed')).sort((left, right) => right.priority - left.priority || left.stagedAt.localeCompare(right.stagedAt))
  if (!projection.model) return <main className="page schedule-page"><header className="page-header"><h1>Schedule</h1></header><p role="status">{projection.error}</p><p>Your edits remain in this tab. Wait for saving to finish, or use Retry saving or Download backup above.</p></main>
  return <main className="page schedule-page"><header className="page-header"><div><p className="eyebrow">Confirmed for staging, not execution</p><h1>Schedule</h1></div></header>
    <p className="lede">Staged Actions stay out of Today and notifications. Adding one to the Adaptive Plan does not book calendar time. Scheduling creates a separate CalendarEvent only after confirmation.</p>
    {decisionIssue && <p role="status">{decisionIssue} Your edits and scheduling input remain in this tab.</p>}
    {planProjection.error && <p role="alert">{planProjection.error} Plan changes are disabled until the workspace is verified.</p>}
    {plan?.recommendations[0] && <p role="status">Adaptive Plan recommends next: {plan.recommendations[0].title}. No time has been booked.</p>}
    {plan && <details><summary>Adaptive Plan ({plan.recommendations.length})</summary>
      {plan.recommendations.length ? <ol className="detail-list">{plan.recommendations.map((item, index) => <li key={item.objectId}><article><h3>{index === 0 ? 'Recommended next: ' : 'Also ready: '}{item.title}</h3><p>{item.explanation}</p></article></li>)}</ol>
        : <p>No Actions are eligible yet. Add a staged Action when you are ready.</p>}
      {plan.blockedCount > 0 && <p role="status">{plan.blockedCount} eligible {plan.blockedCount === 1 ? 'Action is' : 'Actions are'} waiting on dependencies.</p>}
    </details>}
    {actions.length ? <ul className="detail-list">{actions.map(action => <StagedActionRow registerSearchHandoffGuard={registerSearchHandoffGuard} key={action.id} action={action} state={state} update={update} readDecisionModel={readDecisionModel} decisionBlocked={decisionIssue} planBlocked={!!planProjection.error || !!decisionIssue} focus={action.objectId === focusActionId} onFocusHandled={onFocusHandled} />)}</ul> : <p className="empty">No staged Actions yet.</p>}
  </main>
}
