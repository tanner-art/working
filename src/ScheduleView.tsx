import { useMemo, useState, type FormEvent } from 'react'
import type { AppState, StagedAction } from './domain'
import { reconcileLegacyUi } from './migration'
import { scheduleStagedAction } from './actionStaging'

function localDateTimeValue(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function StagedActionRow({ action, state, update }: { action: StagedAction; state: AppState; update: (next: (state: AppState) => AppState) => void }) {
  const [when, setWhen] = useState(() => localDateTimeValue(new Date(Date.now() + 60 * 60_000)))
  const [message, setMessage] = useState('')
  const object = state.objects.find(item => item.id === action.objectId)
  if (!object) return null
  const submit = (event: FormEvent) => {
    event.preventDefault()
    try {
      const startsAt = new Date(when).toISOString()
      const temporalContext = Intl.DateTimeFormat().resolvedOptions().timeZone || 'local time'
      update(current => scheduleStagedAction(current, action.objectId, startsAt, temporalContext))
      setMessage('CalendarEvent confirmed. The Action remains excluded from Today and the Adaptive Plan.')
    } catch (error) { setMessage((error as Error).message) }
  }
  return <li><article>
    <h2>{object.interpretation.summary}</h2>
    <p>Priority {action.priority} of 5 · {action.status === 'scheduled' ? 'CalendarEvent confirmed' : 'Unscheduled staged Action'}</p>
    {action.status === 'staged' && <form onSubmit={submit}>
      <label>Schedule as CalendarEvent <input aria-label={`Schedule ${object.interpretation.summary}`} type="datetime-local" required value={when} onChange={event => setWhen(event.target.value)} /></label>
      <button className="primary" type="submit">Confirm CalendarEvent</button>
    </form>}
    {action.status === 'reversed' && <p>This Action was reversed. Its capture and history are retained.</p>}
    {message && <p role="status">{message}</p>}
  </article></li>
}

/** A dedicated projection: staged Actions are intentionally absent from Today and planning. */
export function ScheduleView({ state, update }: { state: AppState; update: (next: (state: AppState) => AppState) => void }) {
  const model = useMemo(() => reconcileLegacyUi(state), [state])
  const actions = (model.stagedActions ?? []).filter(action => action.status !== 'reversed').sort((left, right) => right.priority - left.priority || left.stagedAt.localeCompare(right.stagedAt))
  return <main className="page schedule-page">
    <header className="page-header"><div><p className="eyebrow">Confirmed for staging, not execution</p><h1>Schedule</h1></div></header>
    <p className="lede">Staged Actions are saved with priority but remain out of Today, notifications, and the Adaptive Plan. Scheduling creates a separate CalendarEvent only after this confirmation.</p>
    {actions.length ? <ul className="detail-list">{actions.map(action => <StagedActionRow key={action.id} action={action} state={state} update={update} />)}</ul> : <p className="empty">No staged Actions yet. Resolve a capture as Action in Organize to add one here.</p>}
  </main>
}
