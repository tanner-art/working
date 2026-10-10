import { useMemo, useState, type FormEvent } from 'react'
import type { AppState, StagedAction } from './domain'
import { reconcileLegacyUi } from './migration'
import { scheduleStagedAction, setStagedActionPriority } from './actionStaging'
import { calculateAdaptivePlan, isPlanEligible, setActionPlanEligibility } from './adaptivePlan'

const localDateTimeValue = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)

function StagedActionRow({ action, state, update }: { action: StagedAction; state: AppState; update: (next: (state: AppState) => AppState) => void }) {
  const [when, setWhen] = useState(() => localDateTimeValue(new Date(Date.now() + 60 * 60_000)))
  const [message, setMessage] = useState('')
  const object = state.objects.find(item => item.id === action.objectId)
  if (!object) return null
  const submit = (event: FormEvent) => {
    event.preventDefault()
    try {
      update(current => scheduleStagedAction(current, action.objectId, new Date(when).toISOString(), Intl.DateTimeFormat().resolvedOptions().timeZone || 'local time'))
      setMessage('CalendarEvent confirmed.')
    } catch (error) { setMessage((error as Error).message) }
  }
  const eligible = isPlanEligible(object)
  return <li><article><h2>{object.interpretation.summary}</h2>
    <label>Priority <select aria-label={`Priority for ${object.interpretation.summary}`} value={action.priority} disabled={action.status !== 'staged'} onChange={event => {
      try {
        update(current => setStagedActionPriority(current, action.objectId, Number(event.target.value) as StagedAction['priority']))
        setMessage('Priority saved.')
      } catch (error) { setMessage((error as Error).message) }
    }}>{[1, 2, 3, 4, 5].map(priority => <option key={priority} value={priority}>{priority} of 5</option>)}</select></label>
    <p>{action.status === 'scheduled' ? 'CalendarEvent confirmed' : eligible ? 'Eligible for the Adaptive Plan; still unscheduled' : 'Unscheduled staged Action'}</p>
    {action.status === 'staged' && <><button className="secondary" type="button" onClick={() => {
      try {
        update(current => setActionPlanEligibility(current, action.objectId, !eligible))
        setMessage(eligible ? 'Removed from Adaptive Plan.' : 'Added to Adaptive Plan.')
      } catch (error) { setMessage((error as Error).message) }
    }}>{eligible ? 'Remove from plan' : 'Add to plan'}</button>
      <form onSubmit={submit}><label>Schedule as CalendarEvent <input aria-label={`Schedule ${object.interpretation.summary}`} type="datetime-local" required value={when} onChange={event => setWhen(event.target.value)} /></label><button className="primary" type="submit">Confirm CalendarEvent</button></form></>}
    {message && <p role="status">{message}</p>}
  </article></li>
}

export function ScheduleView({ state, update }: { state: AppState; update: (next: (state: AppState) => AppState) => void }) {
  const model = useMemo(() => reconcileLegacyUi(state), [state])
  const plan = useMemo(() => calculateAdaptivePlan(state), [state])
  const actions = (model.stagedActions ?? []).filter(action => action.status !== 'reversed').sort((left, right) => right.priority - left.priority || left.stagedAt.localeCompare(right.stagedAt))
  return <main className="page schedule-page"><header className="page-header"><div><p className="eyebrow">Confirmed for staging, not execution</p><h1>Schedule</h1></div></header>
    <p className="lede">Staged Actions stay out of Today and notifications. Adding one to the Adaptive Plan does not book calendar time. Scheduling creates a separate CalendarEvent only after confirmation.</p>
    {plan.recommendations[0] && <p role="status">Adaptive Plan recommends next: {plan.recommendations[0].title}. No time has been booked.</p>}
    <details><summary>Adaptive Plan ({plan.recommendations.length})</summary>
      {plan.recommendations.length ? <ol className="detail-list">{plan.recommendations.map((item, index) => <li key={item.objectId}><article><h3>{index === 0 ? 'Recommended next: ' : 'Also ready: '}{item.title}</h3><p>{item.explanation}</p></article></li>)}</ol>
        : <p>No Actions are eligible yet. Add a staged Action when you are ready.</p>}
      {plan.blockedCount > 0 && <p role="status">{plan.blockedCount} eligible {plan.blockedCount === 1 ? 'Action is' : 'Actions are'} waiting on dependencies.</p>}
    </details>
    {actions.length ? <ul className="detail-list">{actions.map(action => <StagedActionRow key={action.id} action={action} state={state} update={update} />)}</ul> : <p className="empty">No staged Actions yet.</p>}
  </main>
}
