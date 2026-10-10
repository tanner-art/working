import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { AppState, StagedAction } from './domain'
import { reconcileLegacyUi } from './migration'
import { scheduleStagedAction, setStagedActionPriority } from './actionStaging'

const localDateTimeValue = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
function StagedActionRow({ action, state, update, focus }: { action: StagedAction; state: AppState; update: (next: (state: AppState) => AppState) => void; focus: boolean }) {
  const [when, setWhen] = useState(() => localDateTimeValue(new Date(Date.now() + 60 * 60_000)))
  const [message, setMessage] = useState('')
  const row = useRef<HTMLLIElement>(null)
  useEffect(() => { if (focus) row.current?.focus() }, [focus])
  const object = state.objects.find(item => item.id === action.objectId)
  if (!object) return null
  const submit = (event: FormEvent) => { event.preventDefault(); try { update(current => scheduleStagedAction(current, action.objectId, new Date(when).toISOString(), Intl.DateTimeFormat().resolvedOptions().timeZone || 'local time')); setMessage('CalendarEvent confirmed.') } catch (error) { setMessage((error as Error).message) } }
  return <li ref={row} tabIndex={focus ? -1 : undefined}><article><h2>{object.interpretation.summary}</h2><label>Priority <select aria-label={`Priority for ${object.interpretation.summary}`} value={action.priority} disabled={action.status !== 'staged'} onChange={event => { try { update(current => setStagedActionPriority(current, action.objectId, Number(event.target.value) as StagedAction['priority'])); setMessage('Priority saved.') } catch (error) { setMessage((error as Error).message) } }}>{[1, 2, 3, 4, 5].map(priority => <option key={priority} value={priority}>{priority} of 5</option>)}</select></label><p>{action.status === 'scheduled' ? 'CalendarEvent confirmed' : 'Unscheduled staged Action'}</p>{action.status === 'staged' && <form onSubmit={submit}><label>Schedule as CalendarEvent <input aria-label={`Schedule ${object.interpretation.summary}`} type="datetime-local" required value={when} onChange={event => setWhen(event.target.value)} /></label><button className="primary" type="submit">Confirm CalendarEvent</button></form>}{message && <p role="status">{message}</p>}</article></li>
}
export function ScheduleView({ state, update, focusActionId = null }: { state: AppState; update: (next: (state: AppState) => AppState) => void; focusActionId?: string | null }) {
  const model = useMemo(() => reconcileLegacyUi(state), [state])
  const actions = (model.stagedActions ?? []).filter(action => action.status !== 'reversed').sort((left, right) => right.priority - left.priority || left.stagedAt.localeCompare(right.stagedAt))
  return <main className="page schedule-page"><header className="page-header"><div><p className="eyebrow">Confirmed for staging, not execution</p><h1>Schedule</h1></div></header><p className="lede">Staged Actions remain out of Today, notifications, and the Adaptive Plan. Scheduling creates a separate CalendarEvent only after confirmation.</p>{actions.length ? <ul className="detail-list">{actions.map(action => <StagedActionRow key={action.id} action={action} state={state} update={update} focus={action.objectId === focusActionId} />)}</ul> : <p className="empty">No staged Actions yet.</p>}</main>
}
