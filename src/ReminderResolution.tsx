import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { AppState, SemanticObject, ThoughtObject } from './domain'
import type { ReminderChoice } from './reminderWorkflow'
import { dailyLogReminderProjection, specificReminderProjection } from './reminderProjection'

/** Converts a synchronous stale-state rejection into text that the mounted surface can show. */
export function reminderDeliveryFailureMessage(action: () => void): string | undefined {
  try { action(); return undefined } catch (error) {
    return error instanceof Error ? error.message : 'Unable to update this reminder. Refresh and try again.'
  }
}

export function ReminderResolution({ object, targets, onResolve, onCancel }: { object: ThoughtObject; targets: readonly SemanticObject[]; onResolve: (choice: ReminderChoice) => void; onCancel?: () => void }) {
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
  return <form className="reminder-resolution" onSubmit={submit} aria-label="Set reminder details"><p>Attach this reminder to an existing item. It will not change that item into a task or commitment.</p><label>Reminder for <select value={targetId} onChange={event => setTargetId(event.target.value)} required><option value="">Choose an item</option>{targets.map(target => <option key={target.id} value={target.id}>{target.summary}</option>)}</select></label><fieldset><legend>Mode</legend><label><input type="radio" name={`reminder-mode-${object.id}`} checked={mode === 'specific'} onChange={() => setMode('specific')} /> Specific</label><label><input type="radio" name={`reminder-mode-${object.id}`} checked={mode === 'daily-log'} onChange={() => setMode('daily-log')} /> Daily log</label></fieldset>{mode === 'specific' && <label>Date and time <input type="datetime-local" value={dueAt} onChange={event => setDueAt(event.target.value)} required /></label>}<p>Notification delivery is not available here; active reminders remain visible in the app.</p><button className="primary" type="submit">Save reminder</button>{onCancel && <button className="secondary" type="button" onClick={onCancel}>Cancel</button>}{message && <p role="alert">{message}</p>}</form>
}

/** Visible in-app fallback; an already-resolved stale click becomes a recoverable message. */
export function ReminderProjections({ state, onDeliveryState, focusInstructionId = null, onFocusHandled }: { state: AppState; onDeliveryState: (instructionId: string, state: 'handled' | 'dismissed') => void; focusInstructionId?: string | null; onFocusHandled?: () => void }) {
  const now = useMemo(() => new Date(), [state])
  const inFlight = useRef(new Set<string>())
  const rowRefs = useRef(new Map<string, HTMLLIElement>())
  const [pending, setPending] = useState<readonly string[]>([])
  const [message, setMessage] = useState('')
  useEffect(() => { const row = focusInstructionId ? rowRefs.current.get(focusInstructionId) : undefined; if (row) { row.focus(); onFocusHandled?.() } }, [focusInstructionId])
  if (!state.model) return null
  const specific = specificReminderProjection(state.model, now)
  const daily = dailyLogReminderProjection(state.model, now)
  const deliver = (instructionId: string, deliveryState: 'handled' | 'dismissed') => {
    if (inFlight.current.has(instructionId)) return
    inFlight.current.add(instructionId)
    setPending(current => [...current, instructionId])
    setMessage('')
    const failure = reminderDeliveryFailureMessage(() => onDeliveryState(instructionId, deliveryState))
    if (failure) {
      inFlight.current.delete(instructionId)
      setPending(current => current.filter(id => id !== instructionId))
      setMessage(failure)
    }
  }
  const rows = (items: typeof specific) => items.map(({ instruction, target, due }) => {
    const busy = pending.includes(instruction.id)
    return <li key={instruction.id} ref={node => { if (node) rowRefs.current.set(instruction.id, node); else rowRefs.current.delete(instruction.id) }} tabIndex={instruction.id === focusInstructionId ? -1 : undefined}><strong>{target.summary}</strong>{instruction.mode === 'specific' && <span>{due ? ' Due now' : ` Due ${new Date(instruction.dueAt!).toLocaleString()}`}</span>}<small> In-app only — notification delivery is unavailable.</small><button className="secondary" type="button" disabled={busy} onClick={() => deliver(instruction.id, 'handled')}>Handled</button><button className="secondary" type="button" disabled={busy} onClick={() => deliver(instruction.id, 'dismissed')}>Dismiss</button></li>
  })
  return <section className="reminder-projections" aria-label="Active reminders"><h2>Reminders</h2><p>Notification delivery is unavailable. Active reminders remain visible here.</p>{message && <p role="alert">{message}</p>}<h3>Specific</h3>{specific.length ? <ul>{rows(specific)}</ul> : <p>No active Specific reminders.</p>}<h3>Daily log</h3>{daily.length ? <ul>{rows(daily)}</ul> : <p>No active Daily log reminders.</p>}</section>
}
