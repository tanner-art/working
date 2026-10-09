import { useState, type FormEvent } from 'react'
import type { SemanticObject, ThoughtObject } from './domain'
import { resolveCommitment, type CommitmentDetails } from './commitmentWorkflow'

/** The four-field Review form; saving establishes an obligation, never an event. */
export function CommitmentResolution({ object, dependencies, onResolve, onCancel }: { object: ThoughtObject; dependencies: readonly SemanticObject[]; onResolve: (object: ThoughtObject) => void; onCancel?: () => void }) {
  const [title, setTitle] = useState(object.interpretation.summary), [date, setDate] = useState(''), [time, setTime] = useState('')
  const [dependencyIds, setDependencyIds] = useState<readonly string[]>([]), [message, setMessage] = useState('')
  const submit = (event: FormEvent) => { event.preventDefault(); try { const details: CommitmentDetails = { title, ...(date ? { date } : {}), ...(time ? { time } : {}), dependencyIds }; onResolve(resolveCommitment(object, details)) } catch (error) { setMessage(error instanceof Error ? error.message : 'Unable to save this commitment. Refresh Review and try again.') } }
  const toggle = (id: string) => setDependencyIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id])
  const choices = dependencies.filter(item => item.id !== object.id)
  return <form className="commitment-resolution" onSubmit={submit} aria-label="Set commitment details">
    <label>Title<input value={title} onChange={event => setTitle(event.target.value)} required /></label><label>Date<input type="date" value={date} onChange={event => setDate(event.target.value)} /></label><label>Time<input type="time" value={time} onChange={event => setTime(event.target.value)} /></label>
    <fieldset><legend>Dependencies</legend>{choices.length ? choices.map(item => <label key={item.id}><input type="checkbox" checked={dependencyIds.includes(item.id)} onChange={() => toggle(item.id)} /> {item.summary}</label>) : <p>No available dependencies.</p>}</fieldset>
    <p>Saving creates an obligation only. A date is a proposed deadline; a CalendarEvent requires a separate confirmation.</p><button className="primary" type="submit">Save commitment</button>{onCancel && <button className="secondary" type="button" onClick={onCancel}>Cancel</button>}{message && <p role="alert">{message}</p>}
  </form>
}
