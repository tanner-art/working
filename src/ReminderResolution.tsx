import { useState, type FormEvent } from 'react'
import type { SemanticObject, ThoughtObject } from './domain'
import type { ReminderChoice } from './reminderWorkflow'

/** Minimal explicit choice form. Its owner supplies the target list and persistence callback. */
export function ReminderResolution({ object, targets, onResolve, onCancel }: {
  object: ThoughtObject
  targets: readonly SemanticObject[]
  onResolve: (choice: ReminderChoice) => void
  onCancel?: () => void
}) {
  const [targetId, setTargetId] = useState('')
  const [mode, setMode] = useState<ReminderChoice['mode']>('daily-log')
  const [dueAt, setDueAt] = useState('')
  const [message, setMessage] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!targetId) return setMessage('Choose what this reminder is about.')
    if (mode === 'specific' && !dueAt) return setMessage('Choose a date and time for this Specific reminder.')
    setMessage('')
    onResolve({ targetId, mode, ...(mode === 'specific' ? { dueAt: new Date(dueAt).toISOString() } : {}) })
  }
  return <form className="reminder-resolution" onSubmit={submit} aria-label="Set reminder details">
    <p>Attach this reminder to an existing item. It will not change that item into a task or commitment.</p>
    <label>Reminder for <select value={targetId} onChange={event => setTargetId(event.target.value)} required>
      <option value="">Choose an item</option>{targets.map(target => <option key={target.id} value={target.id}>{target.summary}</option>)}</select></label>
    <fieldset><legend>Mode</legend><label><input type="radio" name={`reminder-mode-${object.id}`} checked={mode === 'specific'} onChange={() => setMode('specific')} /> Specific</label><label><input type="radio" name={`reminder-mode-${object.id}`} checked={mode === 'daily-log'} onChange={() => setMode('daily-log')} /> Daily log</label></fieldset>
    {mode === 'specific' && <label>Date and time <input type="datetime-local" value={dueAt} onChange={event => setDueAt(event.target.value)} required /></label>}
    <p>Notification delivery is not available here; active reminders remain visible in the app.</p>
    <button className="primary" type="submit">Save reminder</button>{onCancel && <button className="secondary" type="button" onClick={onCancel}>Cancel</button>}{message && <p role="alert">{message}</p>}
  </form>
}
