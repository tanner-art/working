import { useEffect, useRef, useState } from 'react'
import type { AppState, CanvasElement, ObjectKind, ThoughtObject } from './domain'
import { objectLabels } from './domain'
import { interpret } from './interpreter'
import { canvasObjectDraft, confirmObject, hasConfirmation, reverseObject, fixedCommitments, recentObjects, confirmedActions, setObjectKind, setObjectStatus, updateObject } from './objectWorkflow'
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

type View = 'today' | 'capture' | 'review' | 'commitments' | 'canvas'
const nav: { id: View; label: string; icon: string }[] = [
  { id: 'today', label: 'Today', icon: '◉' }, { id: 'capture', label: 'Capture', icon: '＋' }, { id: 'review', label: 'Review', icon: '◇' }, { id: 'commitments', label: 'Commitments', icon: '□' }, { id: 'canvas', label: 'Canvas', icon: '⌁' }
]

export function App() {
  const [initial] = useState(loadStateResult)
  const [state, setState] = useState<AppState>(initial.state)
  const [saveError, setSaveError] = useState<string | undefined>()
  const [view, setView] = useState<View>('today')
  const [draft, setDraft] = useState('')
  const [context, setContext] = useState('')
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  // Session-only canvas undo/redo stack, kept at the App level (not inside Canvas) so
  // switching views does not discard it. See docs/DECISIONS.md D-010 (resolves OD-002).
  // `canvasHistory.present` and `state.canvas` are written together, from the same
  // returned CanvasHistory, in every handler below, so they never drift apart — see
  // the adaptation note in src/canvasHistory.ts.
  const [canvasHistory, setCanvasHistory] = useState<CanvasHistory>(() => emptyCanvasHistory(initial.state.canvas))
  const update = (fn: (current: AppState) => AppState) => setState(current => fn(current))
  useEffect(() => { if (!initial.error) setSaveError(saveState(state)) }, [state, initial.error])
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
  const reviewCount = state.objects.filter(item => item.status === 'review').length
  const capture = () => {
    const content = draft.trim()
    if (!content) return
    const result = interpret(content)
    const item = makeObject({ kind: result.kind, originalContent: content, source: 'text', confidence: result.confidence, interpretation: result.interpretation })
    item.context = context.trim() || undefined
    update(current => ({ ...current, objects: [item, ...current.objects] }))
    setDraft(''); setContext(''); setView(item.status === 'review' ? 'review' : 'today')
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
  if (initial.error) return <main className="page"><h1>Unable to load your thoughts</h1><p role="alert">{initial.error}</p><p>Editing is paused to protect your saved work. Retry after browser storage is available, or recover the saved data before continuing.</p><button className="primary" onClick={() => window.location.reload()}>Retry loading</button></main>
  return <main className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">⊹</span><span>threadline</span></div><nav>{nav.map(item => <button className={view === item.id ? 'nav-item active' : 'nav-item'} key={item.id} onClick={() => setView(item.id)}><span>{item.icon}</span>{item.label}{item.id === 'review' && reviewCount > 0 && <b>{reviewCount}</b>}</button>)}</nav><div className="sidebar-bottom"><span className="avatar">D</span><span>Personal space</span></div></aside>
    <section className="content">
      {saveError && <div className="storage-alert" role="alert"><p>{saveError}</p><button className="secondary" onClick={() => setSaveError(saveState(state))}>Retry saving</button><button className="secondary" onClick={downloadBackup}>Download backup</button></div>}
      {view === 'today' && <Today objects={state.objects} onCapture={() => setView('capture')} onOpen={setSelectedObjectId} />}
      {view === 'capture' && <Capture draft={draft} context={context} onDraft={setDraft} onContext={setContext} onCapture={capture} />}
      {view === 'review' && <Review objects={state.objects.filter(item => item.status === 'review')} onChangeKind={changeKind} onConfirm={revise} onReject={id => withdraw(id, 'rejected')} onOpen={setSelectedObjectId} />}
      {view === 'commitments' && <Commitments objects={state.objects} onAdd={() => { setDraft(''); setView('capture') }} onOpen={setSelectedObjectId} />}
      {view === 'canvas' && <Canvas elements={state.canvas} onCommit={commitCanvas} canUndo={canUndoCanvas(canvasHistory)} canRedo={canRedoCanvas(canvasHistory)} onUndo={undoCanvas} onRedo={redoCanvas} onCaptureObject={captureCanvasObject} />}
    </section>
    {selectedObject && <ObjectPanel object={selectedObject} onClose={() => setSelectedObjectId(null)} onSave={saveObject} onReverse={() => withdraw(selectedObject.id, 'reversed')} />}
  </main>
}

function Header({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) { return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>{action}</header> }
function Today({ objects, onCapture, onOpen }: { objects: ThoughtObject[]; onCapture: () => void; onOpen: (id: string) => void }) {
  const commitments = fixedCommitments(objects)
  const actions = confirmedActions(objects)
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
function Capture({ draft, context, onDraft, onContext, onCapture }: { draft: string; context: string; onDraft: (v: string) => void; onContext: (v: string) => void; onCapture: () => void }) { return <div className="page capture-page"><Header eyebrow="Raw capture" title="What’s on your mind?" /><p className="lede">Don’t decide what it is yet. Write it how you would say it.</p><div className="capture-box"><textarea autoFocus value={draft} onChange={event => onDraft(event.target.value)} placeholder="A thought, a loose end, an idea…" onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') onCapture() }} /><div className="capture-footer"><label>Context <input value={context} onChange={event => onContext(event.target.value)} placeholder="Optional — where this belongs" /></label><button className="primary" onClick={onCapture}>Interpret thought <span>⌘↵</span></button></div></div><div className="voice-placeholder"><span>⌁</span><div><strong>Voice capture</strong><p>Coming in the next pass. The source will remain attached to the same original thought.</p></div></div></div> }
function Review({ objects, onChangeKind, onConfirm, onReject, onOpen }: { objects: ThoughtObject[]; onChangeKind: (id: string, kind: ObjectKind) => void; onConfirm: (id: string, kind: ObjectKind) => void; onReject: (id: string) => void; onOpen: (id: string) => void }) {
  return <div className="page"><Header eyebrow="Decision interface" title="A few things need your judgment." />{objects.length === 0 ? <Empty text="Nothing is waiting for review. Ambiguous captures will appear here, with a proposed interpretation." /> : <div className="review-list">{objects.map(item => <article className="review-card" key={item.id}><div className="source-line"><span>Raw capture</span><time>{new Date(item.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div><blockquote>{item.originalContent}</blockquote><div className="proposal"><span className="spark">✦</span><div><p>{item.kind === 'action' ? 'Proposed Action — not yet executable.' : `Proposed ${objectLabels[item.kind]}.`}</p><p>{item.interpretation.summary}</p>{item.history.slice().reverse().find(entry => entry.reviewDecision || entry.confirmation)?.reviewDecision === 'rejected' && <p>Rejected interpretation. Preserved here so you can revise or reconsider it.</p>}<small>{item.kind === 'action' ? 'Confirm this Action to make this work eligible for execution.' : item.kind === 'commitment' ? 'Confirm this obligation only. This does not fix a deadline or schedule an event.' : 'Confirm this interpretation to accept its meaning.'}</small><small>{item.interpretation.rationale}</small></div><em>{Math.round(item.confidence * 100)}% confident</em></div><div className="review-actions"><select aria-label="Review object type" value={item.kind} onChange={event => onChangeKind(item.id, event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select><button className="secondary" onClick={() => onOpen(item.id)}>Adjust details</button><button className="secondary" onClick={() => onReject(item.id)}>Reject interpretation</button><button className="primary" disabled={item.kind === 'reminder'} onClick={() => onConfirm(item.id, item.kind)}>Confirm interpretation</button></div></article>)}</div>}</div>
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
  const loadSelect = (key: 'attentionLoad' | 'resourceCost') => <select value={draft.metadata[key] ?? ''} onChange={event => metadata(key, event.target.value)}>
    <option value="">Unspecified</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
  </select>
  return <div className="panel-backdrop" onMouseDown={onClose}>
    <aside className="object-panel" onMouseDown={event => event.stopPropagation()}>
      <header><div><p className="eyebrow">Object workbench</p><h2>Shape this thought</h2></div><button className="close-button" onClick={onClose} aria-label="Close object details">×</button></header>
      <div className="panel-scroll">
        <section className="raw-thought"><p className="section-label">Original capture</p><p>{object.originalContent}</p><small>{object.source} · {new Date(object.createdAt).toLocaleString()}</small></section>
        <section className="interpretation"><p className="section-label">AI proposal</p><strong>{object.interpretation.summary}</strong><small>{Math.round(object.confidence * 100)}% confident · {object.interpretation.rationale}</small></section>
        {awaitingConfirmation && <p>Type and detail edits do not confirm work. Save changes, then use Confirm interpretation in Review.</p>}
        <div className="form-grid">
          <label>Type<select value={draft.kind} onChange={event => field('kind', event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select></label>
          <label>Status<select disabled={awaitingConfirmation} value={awaitingConfirmation ? 'review' : draft.status} onChange={event => field('status', event.target.value as ThoughtObject['status'])}>{['inbox', 'review', 'confirmed', 'complete', 'archived'].map(status => <option key={status} value={status}>{status}</option>)}</select></label>
          <label className="wide">Context or project<input value={draft.context ?? ''} onChange={event => field('context', event.target.value)} placeholder="Optional — e.g. a project or person" /></label>
          <label>Proposed date (not fixed)<input type="date" value={draft.metadata.deadline ?? ''} onChange={event => metadata('deadline', event.target.value)} /></label>
          <label>Urgency{scoreSelect('urgency')}</label>
          <label>Effort<select value={draft.metadata.effort ?? ''} onChange={event => metadata('effort', event.target.value)}><option value="">Unspecified</option><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label>
          <label>Attention load{loadSelect('attentionLoad')}</label>
          <label>Strategic importance{scoreSelect('strategicImportance')}</label>
          <label>Resource cost{loadSelect('resourceCost')}</label>
          <label>Optional ROI{scoreSelect('roi')}</label>
        </div>
        <details><summary>Interpretation history ({object.history.length})</summary><ol>{object.history.slice().reverse().map((entry, index) => <li key={`${entry.at}-${index}`}><p>{entry.event}</p><time>{entry.at}</time>{entry.confirmation && <small>{entry.confirmation.transition}: {entry.confirmation.summary}</small>}</li>)}</ol></details>
        {hasConfirmation(object) && <><p>Reversal returns this meaning to Review. External effects are unchanged.</p><button className="secondary" onClick={() => { onReverse(); onClose() }}>Reverse confirmation</button></>}
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
  const [dragOffset, setDragOffset] = useState<{ id: string; dx: number; dy: number } | null>(null)
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const drag = useRef<{ id?: string; startX: number; startY: number; originalX?: number; originalY?: number; pan?: boolean; originalPan?: { x: number; y: number }; dx: number; dy: number; moved: boolean } | null>(null)
  const positioned = (id?: string) => {
    const item = elements.find(value => value.id === id)
    if (!item) return undefined
    return dragOffset && dragOffset.id === id ? { ...item, x: item.x + dragOffset.dx, y: item.y + dragOffset.dy } : item
  }
  const add = (type: 'text' | 'container') => {
    // Placement must account for both pan and zoom: a screen-space offset has to be
    // converted into world space by dividing by scale, or nodes land in the wrong spot
    // whenever the canvas is zoomed.
    const worldX = (260 - pan.x) / scale
    const worldY = (160 - pan.y) / scale
    const next = newCanvasElement(type, worldX, worldY)
    onCommit([...elements, next])
    setSelected(next.id)
  }
  const down = (event: React.PointerEvent, item?: CanvasElement) => { const point = { startX: event.clientX, startY: event.clientY, dx: 0, dy: 0, moved: false }; drag.current = item ? { ...point, id: item.id, originalX: item.x, originalY: item.y } : { ...point, pan: true, originalPan: pan }; (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId) }
  const move = (event: React.PointerEvent) => {
    if (!drag.current) return
    const dx = (event.clientX - drag.current.startX) / scale
    const dy = (event.clientY - drag.current.startY) / scale
    drag.current.dx = dx; drag.current.dy = dy
    if (dx !== 0 || dy !== 0) drag.current.moved = true
    if (drag.current.pan) setPan({ x: drag.current.originalPan!.x + dx * scale, y: drag.current.originalPan!.y + dy * scale })
    else if (drag.current.id) setDragOffset({ id: drag.current.id, dx, dy })
  }
  const end = () => {
    const current = drag.current
    drag.current = null
    if (current && !current.pan && current.id && current.moved) {
      const next = elements.map(item => item.id === current.id ? { ...item, x: current.originalX! + current.dx, y: current.originalY! + current.dy } : item)
      onCommit(next)
    }
    setDragOffset(null)
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
  const selectedElement = selected ? positioned(selected) : undefined
  const canCaptureSelected = Boolean(selectedElement?.text?.trim() && selectedElement.type !== 'arrow')
  const removeSelected = () => { if (!selected) return; onCommit(elements.filter(item => item.id !== selected && item.fromId !== selected && item.toId !== selected)); setSelected(null); setConnectFrom(null) }
  const commitText = (item: CanvasElement) => {
    if (editing && editing.id === item.id && editing.text !== item.text) onCommit(elements.map(value => value.id === item.id ? { ...value, text: editing.text } : value))
    setEditing(null)
  }
  return <div className="canvas-page"><div className="canvas-head"><div><p className="eyebrow">Spatial formulation</p><h1>Untitled canvas</h1></div><div className="canvas-tools"><button onClick={() => add('text')}>+ Text</button><button onClick={() => add('container')}>+ Group</button><button disabled={!selectedElement} className={connectFrom ? 'selected-tool' : ''} onClick={() => setConnectFrom(connectFrom ? null : selected)}>↗ Connect</button><button disabled={!canCaptureSelected} onClick={() => selectedElement && onCaptureObject(selectedElement)}>Capture node</button><button disabled={!selected} onClick={removeSelected}>Delete</button><span/><button disabled={!canUndo} title="Undo (Ctrl/Cmd+Z)" onClick={onUndo}>↶ Undo</button><button disabled={!canRedo} title="Redo (Ctrl/Cmd+Shift+Z)" onClick={onRedo}>↷ Redo</button><span/><button onClick={() => setScale(value => Math.max(.55, value - .15))}>−</button><span>{Math.round(scale * 100)}%</span><button onClick={() => setScale(value => Math.min(1.6, value + .15))}>＋</button></div></div><div className="canvas-note">{connectFrom ? 'Select another thought to draw the connection.' : 'Use the grip to move thoughts · drag empty space to pan · edit text directly'}</div><div className="canvas" onPointerDown={event => down(event)} onPointerMove={move} onPointerUp={end} onPointerLeave={end} onClick={() => setSelected(null)}><div className="canvas-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }}><svg className="arrows" aria-hidden="true">{arrows.map(arrow => { const from = positioned(arrow.fromId); const to = positioned(arrow.toId); if (!from || !to) return null; return <line key={arrow.id} x1={from.x + (from.width ?? 160) / 2} y1={from.y + 42} x2={to.x + (to.width ?? 160) / 2} y2={to.y + 22} markerEnd="url(#head)" /> })}<defs><marker id="head" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" /></marker></defs></svg>{elements.filter(item => item.type !== 'arrow').map(item => { const shown = positioned(item.id)!; return <div key={item.id} className={`canvas-node ${item.type} ${selected === item.id ? 'selected' : ''}`} style={{ left: shown.x, top: shown.y, width: item.width, height: item.height }} onClick={event => clickNode(event, item.id)}><div className="canvas-drag-handle" title="Move thought" onPointerDown={event => { event.stopPropagation(); down(event, item) }}><span></span><span></span><span></span></div>{item.type === 'container' && <small>GROUP</small>}<textarea value={editing && editing.id === item.id ? editing.text : (item.text ?? '')} onFocus={() => setEditing({ id: item.id, text: item.text ?? '' })} onChange={event => setEditing({ id: item.id, text: event.target.value })} onBlur={() => commitText(item)} onPointerDown={event => event.stopPropagation()} /></div> })}</div></div></div>
}
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
