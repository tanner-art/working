import { auth, accountLabel, dataOwnershipLabel, type AuthState } from './auth'
import { clearLocalData, defaultSettings, readSettings, resetSettings, writeSettings, SETTINGS_KEY, type LocalSettings } from './settings'
import { DIGEST_DELIVERY_KEY } from './digestDelivery'
import { CANVAS_SIZE, canvasShapeLabels, canvasNodeShape, canvasSize, canvasConnectorPath, connectionAppearance, resizeCanvasNode, convertCanvasNode, updateCanvasConnection, type CanvasShape, type ConnectionPath, type ConnectionPattern, type ConnectionWeight } from './canvasGeometry'
import { attachBlocksInside, canvasGroups, moveCanvasNode, removeCanvasNode, setCanvasGroup } from './canvasGroups'
import { TemporalReview } from './TemporalReview'
import { MorningDigest } from './DigestPanel'
import { CalendarView } from './CalendarView'
import { useEffect, useRef, useState } from 'react'
import type { AppState, CanvasElement, ObjectKind, SemanticRelationship, ThoughtObject } from './domain'
import { objectLabels } from './domain'
import { createInterpretedObject } from './captureInterpretation'
import { reviewObjects, canvasObjectDraft, confirmObject, hasConfirmation, reverseObject, fixedCommitments, recentObjects, confirmedActions, setObjectKind, setObjectStatus, updateObject } from './objectWorkflow'
import { loadStateResult, makeObject, newCanvasElement, saveState } from './store'
import type { CanvasHistory } from './canvasHistory'
import {
  canRedoCanvas,
  canUndoCanvas,
  commitCanvas as commitCanvasHistory,
  emptyCanvasHistory,
  redoCanvas as redoCanvasHistory,
  undoCanvas as undoCanvasHistory,
} from './canvasHistory'

type View = 'today' | 'capture' | 'review' | 'commitments' | 'calendar' | 'canvas' | 'settings' | 'digest'
const nav: { id: View; label: string; icon: string }[] = [
  { id: 'today', label: 'Today', icon: '◉' }, { id: 'capture', label: 'Capture', icon: '＋' }, { id: 'review', label: 'Organize', icon: '◇' }, { id: 'calendar', label: 'Calendar', icon: '▦' }, { id: 'canvas', label: 'Canvas', icon: '⌁' }, { id: 'settings', label: 'Settings', icon: '⚙' }
]

/** Single shared account subscription; several Settings cards read the same state. */
function useAuthState() {
  const [state, setState] = useState<AuthState>(auth.getState)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const unsubscribe = auth.subscribe(() => setState(auth.getState()))
    const disconnect = auth.connect()
    setState(auth.getState())
    return () => { unsubscribe(); disconnect() }
  }, [attempt])
  return { state, retry: () => setAttempt(value => value + 1) }
}

export function App() {
  const [initial] = useState(loadStateResult)
  const [state, setState] = useState<AppState>(initial.state)
  const [saveError, setSaveError] = useState<string | undefined>()
  const [preferences, setPreferences] = useState(() => {
    try { return { value: readSettings(localStorage), error: '' } }
    catch { return { value: { ...defaultSettings }, error: 'Local settings could not be read. Editing settings is paused; stored settings are untouched.' } }
  })
  const account = useAuthState()
  const [view, setView] = useState<View>(preferences.value.startPage)
  const [clearRequested, setClearRequested] = useState(false)
  const clearing = useRef(false)
  const capturePending = useRef(false)
  const [captureError, setCaptureError] = useState<string | undefined>()
  const [draft, setDraft] = useState('')
  const [captureBusy, setCaptureBusy] = useState(false)
  const [captureSuccess, setCaptureSuccess] = useState(0)
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  // Session-only canvas undo/redo stack, kept at the App level (not inside Canvas) so
  // switching views does not discard it. See docs/DECISIONS.md D-010 (resolves OD-002).
  // `canvasHistory.present` and `state.canvas` are written together, from the same
  // returned CanvasHistory, in every handler below, so they never drift apart — see
  // the adaptation note in src/canvasHistory.ts.
  const [canvasHistory, setCanvasHistory] = useState<CanvasHistory>(() => emptyCanvasHistory(initial.state.canvas))
  const update = (fn: (current: AppState) => AppState) => setState(current => fn(current))
  useEffect(() => { if (!initial.error && !clearing.current) setSaveError(saveState(state)) }, [state, initial.error])
  const commitCanvas = (next: CanvasElement[]) => {
    const nextHistory = commitCanvasHistory(canvasHistory, next)
    setCanvasHistory(nextHistory)
    update(current => ({ ...current, canvas: nextHistory.present }))
  }
  const undoCanvas = () => {
    const nextHistory = undoCanvasHistory(canvasHistory)
    if (nextHistory === canvasHistory) return
    setCanvasHistory(nextHistory)
    update(current => ({ ...current, canvas: nextHistory.present }))
  }
  const redoCanvas = () => {
    const nextHistory = redoCanvasHistory(canvasHistory)
    if (nextHistory === canvasHistory) return
    setCanvasHistory(nextHistory)
    update(current => ({ ...current, canvas: nextHistory.present }))
  }
  useEffect(() => {
    if (view !== 'canvas') return
    const isEditableTarget = (target: EventTarget | null) => {
      const element = target as HTMLElement | null
      return element?.tagName === 'INPUT' || element?.tagName === 'TEXTAREA' || Boolean(element?.isContentEditable)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return // never hijack native text-field undo
      const isModifier = event.metaKey || event.ctrlKey
      if (!isModifier) return
      const key = event.key.toLowerCase()
      if (key === 'z' && event.shiftKey) { event.preventDefault(); redoCanvas() }
      else if (key === 'z') { event.preventDefault(); undoCanvas() }
      else if (key === 'y') { event.preventDefault(); redoCanvas() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [view, canvasHistory])
  const downloadBackup = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = 'threadline-backup.json'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const downloadExport = () => {
    try {
      const backup = { ...state, localSettings: localStorage.getItem(SETTINGS_KEY), digestDelivery: localStorage.getItem(DIGEST_DELIVERY_KEY) }
      const url = URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url; link.download = 'threadline-export.json'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { throw new Error('Export could not read browser storage. Use Download thoughts backup to preserve the work in this tab.') }
  }
  const reviewCount = reviewObjects(state.objects).length
  const capture = async () => {
    const content = draft.trim()
    if (!content || capturePending.current) return
    capturePending.current = true
    setCaptureBusy(true)
    setCaptureSuccess(0)
    setCaptureError(undefined)
    try {
      const item = await createInterpretedObject(content)
      if (clearing.current) return
      update(current => ({ ...current, objects: [item, ...current.objects] }))
      // Preserve any new typing while an asynchronous interpreter is running.
      setDraft(current => current === draft ? '' : current)
      setCaptureSuccess(value => value + 1)
    } catch {
      setCaptureError('Unable to capture this thought. Your draft is preserved; retry capturing it.')
    } finally {
      capturePending.current = false
      setCaptureBusy(false)
    }
  }
  const revise = (id: string, kind: ObjectKind) => update(current => ({ ...current, objects: current.objects.map(item => item.id === id ? confirmObject(item, kind) : item) }))
  const withdraw = (id: string, decision: 'rejected' | 'reversed') => update(current => ({ ...current, objects: current.objects.map(item => item.id === id ? reverseObject(item, decision) : item) }))
  const changeKind = (id: string, kind: ObjectKind) => update(current => ({ ...current, objects: current.objects.map(item => item.id === id ? setObjectKind(item, kind) : item) }))
  const saveObject = (updated: ThoughtObject) => update(current => ({ ...current, objects: current.objects.map(item => item.id === updated.id ? updateObject(item, updated) : item) }))
  const captureCanvasObject = (element: CanvasElement) => {
    const draft = canvasObjectDraft(element)
    if (!draft) return
    const item = makeObject(draft)
    update(current => ({ ...current, objects: [item, ...current.objects] }))
    setSelectedObjectId(item.id)
  }
  const selectedObject = state.objects.find(item => item.id === selectedObjectId)
  if (clearRequested) return <ClearLocalData onBackup={downloadBackup} />
  if (initial.error) return <main className="page"><h1>Unable to load your thoughts</h1><p role="alert">{initial.error}</p><p>Editing is paused to protect your saved work. Retry after browser storage is available, or recover the saved data before continuing.</p><button className="primary" onClick={() => window.location.reload()}>Retry loading</button></main>
  return <main className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">⊹</span><span>threadline</span></div><nav>{nav.map(item => <button className={view === item.id ? 'nav-item active' : 'nav-item'} key={item.id} aria-label={item.label} aria-current={view === item.id ? 'page' : undefined} onClick={() => setView(item.id)}><span>{item.icon}</span>{item.label}{item.id === 'review' && reviewCount > 0 && <b>{reviewCount}</b>}</button>)}</nav><button className="sidebar-bottom" aria-label="Account settings" onClick={() => setView('settings')}><span className="avatar">{preferences.value.displayName.slice(0, 1).toUpperCase() || '○'}</span><span>{preferences.value.displayName || 'Personal space'}</span></button></aside>
    <section className="content">
      {captureError && <div className="storage-alert" role="alert">{captureError}</div>}
      {saveError && <div className="storage-alert" role="alert"><p>{saveError}</p><button className="secondary" onClick={() => setSaveError(saveState(state))}>Retry saving</button><button className="secondary" onClick={downloadBackup}>Download backup</button></div>}
      {view === 'today' && <div className="digest-entry"><button className="secondary" onClick={() => setView('digest')}>Morning digest →</button></div>}
      <MorningDigest state={state} visible={view === 'digest'} onShow={() => setView('digest')} />
      {view === 'settings' && <SettingsPage settings={preferences.value} error={preferences.error} authState={account.state} onRetryAccount={account.retry} onSave={value => {
        writeSettings(localStorage, value)
        setPreferences({ value, error: '' })
      }} onResetSettings={() => setPreferences({ value: resetSettings(localStorage), error: '' })} onExport={downloadExport} onBackup={downloadBackup} onClear={() => { clearing.current = true; setClearRequested(true) }} onOpenDigest={() => setView('digest')} />}
      {view === 'today' && <Today objects={state.objects} relationships={state.model?.relationships ?? []} onCapture={() => setView('capture')} onOpen={setSelectedObjectId} />}
      {view === 'capture' && <Capture draft={draft} busy={captureBusy} success={saveError ? 0 : captureSuccess} onDraft={value => { setDraft(value); setCaptureSuccess(0) }} onCapture={capture} />}
      {view === 'review' && <Review objects={reviewObjects(state.objects)} onChangeKind={changeKind} onConfirm={revise} onReject={id => withdraw(id, 'rejected')} onOpen={setSelectedObjectId} />}
      {view === 'review' && <details className="timing-details"><summary>Timing</summary><TemporalReview state={state} onUpdate={update} /></details>}
      {view === 'commitments' && <Commitments objects={state.objects} onAdd={() => { setDraft(''); setView('capture') }} onOpen={setSelectedObjectId} />}
      {view === 'calendar' && <CalendarView state={state} onOpen={setSelectedObjectId} />}
      {view === 'canvas' && <Canvas elements={state.canvas} onCommit={commitCanvas} canUndo={canUndoCanvas(canvasHistory)} canRedo={canRedoCanvas(canvasHistory)} onUndo={undoCanvas} onRedo={redoCanvas} onCaptureObject={captureCanvasObject} />}
    </section>
    {selectedObject && <ObjectPanel object={selectedObject} onClose={() => setSelectedObjectId(null)} onSave={saveObject} onReverse={() => withdraw(selectedObject.id, 'reversed')} />}
  </main>
}

function AccountSection({ state, onRetry }: { state: AuthState; onRetry: () => void }) {
  const [email, setEmail] = useState('')
  return <section className="settings-card"><h2>Account</h2>
    <p role="status" className={state.status === 'signed-in' ? 'status-pill positive' : 'status-pill'}>{accountLabel(state)}</p>
    <p>{dataOwnershipLabel(state)}</p>
    {'message' in state && state.message && <p role={state.status === 'error' ? 'alert' : 'status'}>{state.message}</p>}
    {state.status === 'unconfigured' && <button className="secondary" disabled>Log in with email — unavailable</button>}
    {state.status === 'signed-out' && <form onSubmit={event => { event.preventDefault(); void auth.act('login', email) }}>
      <label>Email address<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></label>
      <button className="primary">Email me a sign-in link</button>
    </form>}
    {state.status === 'loading' && <button className="secondary" disabled>Please wait…</button>}
    {state.status === 'signed-in' && <button className="secondary" onClick={() => { void auth.act('logout') }}>Log out</button>}
    {state.status === 'error' && <button className="secondary" onClick={onRetry}>Retry checking account</button>}
  </section>
}

function DataSection({ state }: { state: AuthState }) {
  return <section className="settings-card"><h2>Data</h2>
    <p className="status-pill">{state.status === 'signed-in' ? 'Signed in · still local-only' : 'Local-only'}</p>
    <p>{dataOwnershipLabel(state)}</p>
    <p>Next: use Recovery below to download a backup you control — there is no cloud sync to fall back on yet.</p>
  </section>
}

function AiInterpretationSection() {
  return <section className="settings-card"><h2>AI interpretation</h2>
    <p className="status-pill muted">Built-in rules only</p>
    <p>Captures are organized by deterministic rules built into the app, not a connected AI provider. Suggested type, confidence and rationale come from those rules, not a live model.</p>
    <button className="secondary" disabled>Connect an AI provider — not built yet</button>
  </section>
}

function MobileInstallSection() {
  const [installed] = useState(() => typeof window !== 'undefined' && Boolean(
    window.matchMedia?.('(display-mode: standalone)').matches ||
    (window.navigator as unknown as { standalone?: boolean }).standalone,
  ))
  return <section className="settings-card"><h2>Mobile install</h2>
    <p className={installed ? 'status-pill positive' : 'status-pill'}>{installed ? 'Installed' : 'Installable now'}</p>
    {installed ? <p>Threadline is running from your home screen right now.</p> : <>
      <p>Threadline can be added to your phone's home screen straight from your browser. There is no in-app setup wizard yet — these are the exact steps:</p>
      <ul>
        <li><strong>iPhone (Safari):</strong> tap Share, then Add to Home Screen.</li>
        <li><strong>Android (Chrome):</strong> open the ⋮ menu and choose Install app, or accept the prompt if Chrome offers it.</li>
      </ul>
    </>}
  </section>
}

function DigestSection({ onOpen }: { onOpen: () => void }) {
  return <section className="settings-card"><h2>Digest</h2>
    <p className="status-pill positive">Available</p>
    <p>The Morning Digest view already works and is reachable from Today. Scheduled delivery and notifications are not built yet — opening it here shows today's digest on demand.</p>
    <button className="secondary" onClick={onOpen}>Open Morning Digest</button>
  </section>
}

function SettingsPage({ settings, error, authState, onRetryAccount, onSave, onResetSettings, onExport, onBackup, onClear, onOpenDigest }: {
  settings: LocalSettings; error: string; authState: AuthState; onRetryAccount: () => void
  onSave: (value: LocalSettings) => void; onResetSettings: () => void
  onExport: () => void; onBackup: () => void; onClear: () => void; onOpenDigest: () => void
}) {
  const [draft, setDraft] = useState(settings)
  const [message, setMessage] = useState('')
  const [failure, setFailure] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  return <div className="page settings-page"><Header eyebrow="Your space" title="Settings / Account" />
    <AccountSection state={authState} onRetry={onRetryAccount} />
    <section className="settings-card"><h2>Local profile</h2><p>Your thoughts and preferences are stored in this browser on this device. There is no account backup or cross-device sync.</p>
      {error && <p role="alert">{error}</p>}
      {error && <div className="settings-recovery"><p>Resetting affects only your display name and start page — it does not touch your thoughts, canvas or digest settings.</p><button className="secondary" onClick={() => { setFailure(''); setMessage(''); try { onResetSettings(); setDraft(defaultSettings); setMessage('Settings reset to defaults on this device.') } catch { setFailure('Settings could not be reset. Check browser storage and retry.') } }}>Reset settings to defaults</button></div>}
      <form onSubmit={event => { event.preventDefault(); setFailure(''); setMessage(''); try { onSave({ ...draft, displayName: draft.displayName.trim() }); setDraft({ ...draft, displayName: draft.displayName.trim() }); setMessage('Settings saved on this device.') } catch { setFailure('Settings could not be saved. Your edits are still here; check browser storage and retry.') } }}>
        <fieldset disabled={!!error}><label>Display name / profile label<input maxLength={80} autoComplete="nickname" value={draft.displayName} onChange={event => setDraft({ ...draft, displayName: event.target.value })} placeholder="Personal space" /></label>
          <label>Open Threadline to<select value={draft.startPage} onChange={event => setDraft({ ...draft, startPage: event.target.value as LocalSettings['startPage'] })}><option value="today">Today</option><option value="capture">Capture</option><option value="canvas">Canvas</option></select></label>
          <button className="primary" type="submit">Save settings</button></fieldset>
      </form><p role="status">{message}</p>
    </section>
    <DataSection state={authState} />
    <AiInterpretationSection />
    <MobileInstallSection />
    <DigestSection onOpen={onOpenDigest} />
    <section className="settings-card"><h2>Recovery</h2><p>Export thoughts, canvas, local profile and digest preferences as JSON. Backup import is not available yet.</p><div className="settings-actions"><button className="secondary" onClick={() => { setFailure(''); try { onExport() } catch (error) { setFailure((error as Error).message) } }}>Download full export</button><button className="secondary" onClick={onBackup}>Download thoughts backup</button></div>
      <p>Clearing removes all Threadline thoughts, canvas and preferences from this browser, including drafts and session undo history. This cannot be undone. Download a backup first and close other Threadline tabs.</p>
      {!confirming ? <button className="secondary danger-button" onClick={() => setConfirming(true)}>Clear local data…</button> : <form className="clear-confirmation" onSubmit={event => { event.preventDefault(); if (confirmation === 'CLEAR') onClear() }}><label>Type CLEAR to permanently clear local data<input autoFocus autoComplete="off" value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label><div className="settings-actions"><button type="button" className="secondary" onClick={() => { setConfirming(false); setConfirmation('') }}>Cancel</button><button className="primary danger-button" disabled={confirmation !== 'CLEAR'}>Permanently clear local data</button></div></form>}
    </section>{failure && <p role="alert">{failure}</p>}
  </div>
}

function ClearLocalData({ onBackup }: { onBackup: () => void }) {
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const clear = () => {
    try { clearLocalData(localStorage, 'CLEAR'); setError(''); setDone(true) }
    catch { setError('Clearing could not finish. Some local data may already be cleared. Editing is paused; retry to finish.') }
  }
  // Mounted only after confirmation, with the digest and other writers unmounted.
  useEffect(clear, [])
  return <main className="page"><h1>{done ? 'Local data cleared' : 'Clearing local data'}</h1>{error && <p role="alert">{error}</p>}{done ? <button className="primary" onClick={() => window.location.reload()}>Start fresh</button> : <div className="settings-actions"><button className="secondary" onClick={clear}>Retry clearing</button><button className="secondary" onClick={onBackup}>Download thoughts backup</button></div>}</main>
}

function Header({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) { return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>{action}</header> }
function Today({ objects, relationships, onCapture, onOpen }: { objects: ThoughtObject[]; relationships: SemanticRelationship[]; onCapture: () => void; onOpen: (id: string) => void }) {
  const commitments = fixedCommitments(objects)
  const actions = confirmedActions(objects, relationships)
  const focus = actions[0]
  const recent = recentObjects(objects)
  const date = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date())
  return <div className="page"><Header eyebrow={date} title="Make space for the work that matters." action={<button className="primary" onClick={onCapture}>Capture a thought <span>↵</span></button>} />
    <section className="today-grid"><div className="focus-card"><p className="section-label">Recommended focus</p><h2>{focus?.originalContent ?? 'Start with a clean capture'}</h2><p>One meaningful action, selected from confirmed work—not an overflowing task list.</p><div className="focus-meta"><span>◒ {focus?.metadata.effort ?? 'small'} effort</span><span>◌ {focus?.metadata.attentionLoad ?? 'low'} attention</span></div><button className="quiet-button" disabled={!focus} onClick={() => focus && onOpen(focus.id)}>{focus ? `Open ${objectLabels[focus.kind].toLowerCase()}` : 'Capture first'} →</button></div>
      <div className="day-summary"><p className="section-label">Attention budget</p><div className="orb"><b>{Math.max(2, 5 - actions.length)}</b><span>open hours</span></div><p>Keep the plan spacious. It can move as your day changes.</p></div></section>
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Fixed commitments</p><h2>Today</h2></div><span>{commitments.length} scheduled</span></div>{commitments.length ? commitments.map(item => <ObjectRow item={item} key={item.id} onOpen={onOpen} accent="commitment" />) : <Empty text="No fixed commitments today. Your execution plan is free to adapt." />}</section>
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Object workbench</p><h2>Recent captures</h2></div><span>{recent.length} visible</span></div>{recent.length ? recent.map(item => <ObjectRow item={item} key={item.id} onOpen={onOpen} />) : <Empty text="Capture something and it will appear here for shaping." />}</section>
  </div>
}
function Capture({ draft, busy, success, onDraft, onCapture }: { draft: string; busy: boolean; success: number; onDraft: (v: string) => void; onCapture: () => void }) {
  const input = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { if (success) input.current?.focus() }, [success])
  return <div className="page capture-page"><Header eyebrow="Raw capture" title="What’s on your mind?" />
    <div className="capture-box"><textarea ref={input} autoFocus aria-label="Raw thought" value={draft} onChange={event => onDraft(event.target.value)} placeholder="A thought, a loose end, an idea…" onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); onCapture() } }} />
      <div className="capture-footer"><span role="status">{success > 0 && <span className="capture-success">✓ Captured</span>}</span><button className="primary" disabled={busy || !draft.trim()} onClick={onCapture}>{busy ? 'Capturing…' : 'Capture'}</button></div>
    </div>
  </div>
}
function Review({ objects, onChangeKind, onConfirm, onReject, onOpen }: { objects: ThoughtObject[]; onChangeKind: (id: string, kind: ObjectKind) => void; onConfirm: (id: string, kind: ObjectKind) => void; onReject: (id: string) => void; onOpen: (id: string) => void }) {
  const [rejecting, setRejecting] = useState<string | null>(null)
  return <div className="page"><Header eyebrow="Your thoughts" title="Organize" />{objects.length === 0 ? <Empty text="All caught up." /> : <div className="review-list">{objects.map(item => <article className="review-card" key={item.id}>
    <div className="source-line"><span>Raw capture</span><time>{new Date(item.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div><blockquote>{item.originalContent}</blockquote>
    <div className="proposal"><div><p>Proposed {objectLabels[item.kind]}</p><p>{item.interpretation.summary}</p>{item.kind === 'commitment' && <small>Confirms the obligation only.</small>}{item.kind === 'reminder' && <small>Choose an object type before confirming.</small>}</div></div>
    {rejecting === item.id ? <div className="reject-confirmation" role="group" aria-label="Confirm rejection"><p>Reject this proposal? Your original capture is kept.</p><button className="secondary" autoFocus onClick={() => setRejecting(null)}>Cancel</button><button className="secondary danger-button" onClick={() => { onReject(item.id); setRejecting(null) }}>Confirm rejection</button></div> : <div className="review-actions"><select aria-label="Object type" value={item.kind} onChange={event => onChangeKind(item.id, event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select><button className="secondary" onClick={() => onOpen(item.id)}>Edit</button><button className="secondary" onClick={() => setRejecting(item.id)}>Reject…</button><button className="primary" disabled={item.kind === 'reminder'} onClick={() => onConfirm(item.id, item.kind)}>Confirm</button></div>}
  </article>)}</div>}</div>
}
function ObjectRow({ item, onOpen, accent }: { item: ThoughtObject; onOpen: (id: string) => void; accent?: 'commitment' }) {
  const detail = item.interpretation.suggestedDate ?? item.context ?? item.interpretation.rationale
  return <button className={`commitment-row clickable-row ${accent === 'commitment' ? 'commitment-accent' : ''}`} onClick={() => onOpen(item.id)}><span className="time-dot"/><div><strong>{item.originalContent}</strong><small>{detail}</small></div><span className="status-chip">{item.status}</span><span className="kind-chip">{objectLabels[item.kind]}</span></button>
}
function Commitments({ objects, onAdd, onOpen }: { objects: ThoughtObject[]; onAdd: () => void; onOpen: (id: string) => void }) { const items = fixedCommitments(objects); const now = new Date(); return <div className="page"><Header eyebrow="External time" title="Commitments stay put." action={<button className="primary" onClick={onAdd}>Add commitment</button>} /><p className="lede">Meetings, appointments, deadlines, and events. This is separate from the flexible execution plan.</p><div className="calendar-grid"><div className="calendar-day"><p className="section-label">Today</p><b>{now.getDate()}</b><span>{new Intl.DateTimeFormat('en-US', { weekday: 'long' }).format(now)}</span></div><div className="calendar-list">{items.length ? items.map(item => <ObjectRow item={item} key={item.id} onOpen={onOpen} accent="commitment" />) : <Empty text="No commitments captured yet." />}</div></div></div> }
function ObjectPanel({ object, onClose, onSave, onReverse }: { object: ThoughtObject; onClose: () => void; onSave: (object: ThoughtObject) => void; onReverse: () => void }) {
  const [draft, setDraft] = useState(object)
  useEffect(() => setDraft(object), [object])
  const awaitingConfirmation = draft.kind !== object.kind || object.status === 'review' || object.status === 'inbox' || ((object.kind === 'action' || object.kind === 'commitment') && !hasConfirmation(object))
  const field = (key: keyof ThoughtObject, value: unknown) => setDraft(current => ({ ...current, [key]: value }))
  const metadata = (key: keyof ThoughtObject['metadata'], value: unknown) => setDraft(current => ({ ...current, metadata: { ...current.metadata, [key]: value || undefined } as ThoughtObject['metadata'] }))
  const scoreSelect = (key: 'urgency' | 'strategicImportance' | 'roi') => <select value={draft.metadata[key] ?? ''} onChange={event => metadata(key, event.target.value ? Number(event.target.value) as 1 | 2 | 3 | 4 | 5 : undefined)}>
    <option value="">Unspecified</option>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value}</option>)}
  </select>
  return <div className="panel-backdrop" onMouseDown={onClose}>
    <aside className="object-panel" onMouseDown={event => event.stopPropagation()}>
      <header><div><p className="eyebrow">Object workbench</p><h2>Shape this thought</h2></div><button className="close-button" onClick={onClose} aria-label="Close object details">×</button></header>
      <div className="panel-scroll">
        <section className="raw-thought"><p className="section-label">Original capture</p><p>{object.originalContent}</p><small>{object.source} · {new Date(object.createdAt).toLocaleString()}</small></section>
        <section className="interpretation"><p className="section-label">AI proposal</p><strong>{object.interpretation.summary}</strong><small>{Math.round(object.confidence * 100)}% confident · {object.interpretation.rationale}</small></section>
        {awaitingConfirmation && <p>Complete and Archive require confirmation in Organize.</p>}
        <div className="form-grid">
          <label>Type<select value={draft.kind} onChange={event => field('kind', event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select></label>
          <label>Status<select disabled={awaitingConfirmation} value={awaitingConfirmation ? 'review' : draft.status} onChange={event => field('status', event.target.value as ThoughtObject['status'])}>{['inbox', 'review', 'confirmed', 'complete', 'archived'].map(status => <option key={status} value={status}>{status}</option>)}</select></label>
          <label className="wide">Context or project<input value={draft.context ?? ''} onChange={event => field('context', event.target.value)} placeholder="Optional — e.g. a project or person" /></label>
          <label>Proposed date (not fixed)<input type="date" value={draft.metadata.deadline ?? ''} onChange={event => metadata('deadline', event.target.value)} /></label>
          <label>Urgency{scoreSelect('urgency')}</label>
          <label>Effort<select value={draft.metadata.effort ?? ''} onChange={event => metadata('effort', event.target.value)}><option value="">Unspecified</option><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label>
        </div>
        <details><summary>Interpretation history ({object.history.length})</summary><ol>{object.history.slice().reverse().map((entry, index) => <li key={`${entry.at}-${index}`}><p>{entry.event}</p><time>{entry.at}</time>{entry.confirmation && <small>{entry.confirmation.transition}: {entry.confirmation.summary}</small>}</li>)}</ol></details>
        {hasConfirmation(object) && <><p>Return this item to Organize.</p><button className="secondary" onClick={() => { onReverse(); onClose() }}>Reverse confirmation</button></>}
      </div>
      <footer><button disabled={awaitingConfirmation} className="secondary" onClick={() => { onSave(setObjectStatus(draft, 'archived')); onClose() }}>Archive</button><button disabled={awaitingConfirmation} className="secondary" onClick={() => { onSave(setObjectStatus(draft, 'complete')); onClose() }}>Complete</button><button className="primary" onClick={() => { onSave(draft); onClose() }}>Save changes</button></footer>
    </aside>
  </div>
}
function Canvas({ elements, onCommit, canUndo, canRedo, onUndo, onRedo, onCaptureObject }: { elements: CanvasElement[]; onCommit: (elements: CanvasElement[]) => void; canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void; onCaptureObject: (element: CanvasElement) => void }) {
  const [pan, setPan] = useState({ x: 0, y: 0 }); const [scale, setScale] = useState(1); const [selected, setSelected] = useState<string | null>(null); const [connectFrom, setConnectFrom] = useState<string | null>(null)
  // Undo/redo (and delete) can remove the currently selected or connect-from node out
  // from under this component without it ever unmounting. Clear any reference to an id
  // that no longer exists so a stale connect-from can never produce a dangling arrow.
  useEffect(() => {
    const ids = new Set(elements.map(item => item.id))
    setSelected(current => (current && !ids.has(current)) ? null : current)
    setConnectFrom(current => (current && !ids.has(current)) ? null : current)
  }, [elements])
  // Live drag/text-edit state stays local to Canvas so every pointer move or keystroke
  // does not push an undo step; only the final, committed result is sent to onCommit,
  // which groups a whole drag or text edit into exactly one undo step.
  const [resizePreview, setResizePreview] = useState<CanvasElement | null>(null)
  const [dragOffset, setDragOffset] = useState<{ id: string; dx: number; dy: number } | null>(null)
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const drag = useRef<{ pointerId: number; resize?: CanvasElement; id?: string; startX: number; startY: number; originalX?: number; originalY?: number; pan?: boolean; originalPan?: { x: number; y: number }; dx: number; dy: number; moved: boolean } | null>(null)
  const positioned = (id?: string) => {
    const item = elements.find(value => value.id === id)
    if (!item) return undefined
    if (resizePreview?.id === id) return resizePreview
    const dragged = dragOffset ? elements.find(value => value.id === dragOffset.id) : undefined
    return dragOffset && (dragOffset.id === id || (dragged?.type === 'container' && item.groupId === dragged.id))
      ? { ...item, x: item.x + dragOffset.dx, y: item.y + dragOffset.dy } : item
  }
  const add = (shape: CanvasShape) => {
    // Placement must account for both pan and zoom: a screen-space offset has to be
    // converted into world space by dividing by scale, or nodes land in the wrong spot
    // whenever the canvas is zoomed.
    const worldX = ((window.innerWidth < 720 ? 32 : 260) - pan.x) / scale
    const worldY = (160 - pan.y) / scale
    const base = newCanvasElement(shape === 'container' ? 'container' : 'text', worldX, worldY)
    const next = convertCanvasNode([base], base.id, shape)[0]
    onCommit([...elements, next])
    setSelected(next.id)
  }
  const down = (event: React.PointerEvent, item?: CanvasElement, resize = false) => { if (event.button !== 0 || drag.current) return; if (item) setSelected(item.id); const point = { pointerId: event.pointerId, resize: resize ? item : undefined, startX: event.clientX, startY: event.clientY, dx: 0, dy: 0, moved: false }; drag.current = item ? { ...point, id: item.id, originalX: item.x, originalY: item.y } : { ...point, pan: true, originalPan: pan }; (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId) }
  const move = (event: React.PointerEvent) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return
    const dx = (event.clientX - drag.current.startX) / scale
    const dy = (event.clientY - drag.current.startY) / scale
    drag.current.dx = dx; drag.current.dy = dy
    if (dx !== 0 || dy !== 0) drag.current.moved = true
    if (drag.current.resize) {
      const node = drag.current.resize, size = canvasSize(node)
      setResizePreview(resizeCanvasNode([node], node.id, size.width + dx, size.height + dy)[0])
    } else if (drag.current.pan) setPan({ x: drag.current.originalPan!.x + dx * scale, y: drag.current.originalPan!.y + dy * scale })
    else if (drag.current.id) setDragOffset({ id: drag.current.id, dx, dy })
  }
  const cancel = () => { drag.current = null; setDragOffset(null); setResizePreview(null) }
  const end = (event: React.PointerEvent) => {
    if (drag.current?.pointerId !== event.pointerId) return
    const current = drag.current
    drag.current = null
    if (current && !current.pan && current.id && current.moved) {
      const size = current.resize && canvasSize(current.resize)
      const next = size ? resizeCanvasNode(elements, current.id, size.width + current.dx, size.height + current.dy) : moveCanvasNode(elements, current.id, current.originalX! + current.dx, current.originalY! + current.dy)
      onCommit(next)
    }
    setDragOffset(null)
    setResizePreview(null)
  }
  const clickNode = (event: React.MouseEvent, id: string) => {
    event.stopPropagation()
    // Validate the connect-from endpoint still exists (not just non-null) so a stale
    // reference left over from an undo/redo/delete can never produce a dangling arrow.
    const connectFromValid = connectFrom !== null && elements.some(item => item.id === connectFrom)
    if (connectFromValid && connectFrom !== id) {
      onCommit([...elements, { id: crypto.randomUUID(), type: 'arrow', x: 0, y: 0, fromId: connectFrom, toId: id }])
      setConnectFrom(null)
    } else {
      setSelected(id)
    }
  }
  const arrows = elements.filter(item => item.type === 'arrow')
  const groups = canvasGroups(elements)
  const selectedElement = selected ? positioned(selected) : undefined
  const canCaptureSelected = Boolean(selectedElement?.text?.trim() && selectedElement.type !== 'arrow')
  const removeSelected = () => { if (!selected) return; onCommit(removeCanvasNode(elements, selected)); setSelected(null); setConnectFrom(null) }
  const commitText = (item: CanvasElement) => {
    if (editing && editing.id === item.id && editing.text !== item.text) onCommit(elements.map(value => value.id === item.id ? { ...value, text: editing.text } : value))
    setEditing(null)
  }
  return <div className="canvas-page">
    <div className="canvas-head">
    <div>
    <p className="eyebrow">Spatial formulation</p>
    <h1>Untitled canvas</h1>
    </div>
    <div className="canvas-tools">
    <button onClick={() => add('text')}>+ Text</button>
    <button onClick={() => add('container')}>+ Group</button>
    <label className="canvas-palette">Add shape <select aria-label="Add canvas shape" value="" onChange={event => { if (event.target.value) add(event.target.value as CanvasShape) }}>
    <option value="" disabled>Choose shape…</option>{Object.entries(canvasShapeLabels).filter(([shape]) => shape !== 'text' && shape !== 'container').map(([shape, label]) => <option key={shape} value={shape}>{label}</option>)}
    </select></label>
    <button disabled={!selectedElement} className={connectFrom ? 'selected-tool' : ''} onClick={() => setConnectFrom(connectFrom ? null : selected)}>↗ Connect</button>
    <button disabled={!canCaptureSelected} onClick={() => selectedElement && onCaptureObject(selectedElement)}>Capture node</button>
    <button disabled={!selected} onClick={removeSelected}>Delete</button>
    <span/>
    <button disabled={!canUndo} title="Undo (Ctrl/Cmd+Z)" onClick={onUndo}>↶ Undo</button>
    <button disabled={!canRedo} title="Redo (Ctrl/Cmd+Shift+Z)" onClick={onRedo}>↷ Redo</button>
    <span/>
    <button onClick={() => setScale(value => Math.max(.55, value - .15))}>−</button>
    <span>{Math.round(scale * 100)}%</span>
    <button onClick={() => setScale(value => Math.min(1.6, value + .15))}>＋</button>
    </div>
    </div>
    <div className="canvas-properties">{selectedElement && selectedElement.type !== 'arrow' && <>
    <label>Shape <select aria-label="Block shape" value={canvasNodeShape(selectedElement)} onChange={event => onCommit(convertCanvasNode(elements, selectedElement.id, event.target.value as CanvasShape))}>
    {Object.entries(canvasShapeLabels).map(([shape, label]) => <option key={shape} value={shape}>{label}</option>)}
    </select>
    </label>{selectedElement.type === 'text' && <label>Move with group <select aria-label="Move with group" value={selectedElement.groupId ?? ''} onChange={event => onCommit(setCanvasGroup(elements, selectedElement.id, event.target.value || undefined))}>
    <option value="">None</option>{groups.map(group => <option key={group.id} value={group.id}>{group.text?.trim() || 'Untitled group'}</option>)}
    </select></label>}{selectedElement.type === 'container' && <button className="secondary" onClick={() => onCommit(attachBlocksInside(elements, selectedElement.id))}>Attach blocks inside</button>}{(['width', 'height'] as const).map(axis => <label key={axis}>{axis === 'width' ? 'Width' : 'Height'}<input key={`${selectedElement.id}-${canvasSize(selectedElement)[axis]}`} aria-label={`Block ${axis}`} type="number" min={axis === 'width' ? CANVAS_SIZE.minWidth : CANVAS_SIZE.minHeight} max={axis === 'width' ? CANVAS_SIZE.maxWidth : CANVAS_SIZE.maxHeight} defaultValue={canvasSize(selectedElement)[axis]} onBlur={event => { const size = canvasSize(selectedElement); const value = event.target.value === '' ? size[axis] : event.target.valueAsNumber; onCommit(resizeCanvasNode(elements, selectedElement.id, axis === 'width' ? value : size.width, axis === 'height' ? value : size.height)); event.target.value = String(canvasSize({ ...selectedElement, [axis]: value })[axis]) }} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }} />
    </label>)}</>}{selectedElement?.type === 'arrow' && <>
    <label>Line <select aria-label="Connection path" value={selectedElement.connectionPath ?? 'straight'} onChange={event => onCommit(updateCanvasConnection(elements, selectedElement.id, { connectionPath: event.target.value as ConnectionPath }))}><option value="straight">Straight</option><option value="curved">Curved arc</option></select></label>
    <label>Pattern <select aria-label="Connection pattern" value={selectedElement.connectionPattern ?? 'solid'} onChange={event => onCommit(updateCanvasConnection(elements, selectedElement.id, { connectionPattern: event.target.value as ConnectionPattern }))}><option value="solid">Solid</option><option value="dashed">Dashed</option><option value="dotted">Dotted</option></select></label>
    <label>Weight <select aria-label="Connection weight" value={selectedElement.connectionWeight ?? 'regular'} onChange={event => onCommit(updateCanvasConnection(elements, selectedElement.id, { connectionWeight: event.target.value as ConnectionWeight }))}><option value="light">Light</option><option value="regular">Regular</option><option value="bold">Bold</option></select></label>
    </>}<span>{selectedElement?.type === 'arrow' ? 'Connection styling is saved with the canvas and can be undone.' : selectedElement ? 'Group membership stays attached when a group moves. Resizing does not remove members.' : 'Select a block or connection to change its appearance.'}</span>
    </div>
    <div className="canvas-note">{connectFrom ? 'Select another thought to draw the connection.' : 'Use the grip to move thoughts · drag empty space to pan · edit text directly'}</div>
    <div className="canvas" onPointerDown={event => down(event)} onPointerMove={move} onPointerUp={end} onPointerCancel={cancel} onLostPointerCapture={cancel} onKeyDown={event => { if (event.key === 'Escape') cancel() }} onClick={() => setSelected(null)}>
    <div className="canvas-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }}>
    <svg className="arrows">{arrows.map(arrow => { const from = positioned(arrow.fromId); const to = positioned(arrow.toId); if (!from || !to) return null; const d = canvasConnectorPath(from, to, arrow.connectionPath); return <g key={arrow.id} className={selected === arrow.id ? 'selected' : ''}><path className="canvas-arrow-visible" d={d} style={connectionAppearance(arrow)} markerEnd="url(#head)"/><path className="canvas-arrow-hit" d={d} role="button" tabIndex={0} aria-label={`Connection from ${from.text || 'block'} to ${to.text || 'block'}`} onClick={event => { event.stopPropagation(); setSelected(arrow.id) }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(arrow.id) } }}/></g> })}<defs>
    <marker id="head" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
    <path d="M0,0 L0,6 L7,3 z" />
    </marker>
    </defs>
    </svg>{elements.filter(item => item.type !== 'arrow').map(item => { const shown = positioned(item.id)!; return <div key={item.id} className={`canvas-node ${item.type} shape-${canvasNodeShape(item)} ${selected === item.id ? 'selected' : ''}`} style={{ left: shown.x, top: shown.y, ...canvasSize(shown) }} onClick={event => clickNode(event, item.id)}>
    {(item.shape === 'ellipse' || item.shape === 'diamond') && <svg className="canvas-shape-outline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{item.shape === 'ellipse' ? <ellipse cx="50" cy="50" rx="50" ry="50" /> : <polygon points="50,0 100,50 50,100 0,50" />}</svg>}
    <div className="canvas-drag-handle" title="Move thought" onPointerDown={event => { event.stopPropagation(); down(event, item) }}>
    <span>
    </span>
    <span>
    </span>
    <span>
    </span>
    </div>{item.type === 'container' && <small>GROUP</small>}<textarea value={editing && editing.id === item.id ? editing.text : (item.text ?? '')} aria-label="Block text" onFocus={() => { setSelected(item.id); setEditing({ id: item.id, text: item.text ?? '' }) }} onChange={event => setEditing({ id: item.id, text: event.target.value })} onBlur={() => commitText(item)} onPointerDown={event => event.stopPropagation()} />
    <button className="canvas-resize-handle" aria-label="Resize block" title="Resize block: drag or use arrow keys" onFocus={() => setSelected(item.id)} onClick={event => event.stopPropagation()} onPointerDown={event => { event.stopPropagation(); down(event, item, true) }} onKeyDown={event => { if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return; event.preventDefault(); const size = canvasSize(item), step = event.shiftKey ? 10 : 1; onCommit(resizeCanvasNode(elements, item.id, size.width + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0), size.height + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0))) }}>↘</button>
    </div> })}</div>
    </div>
    </div>
}
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
