import { useEffect, useRef, useState } from 'react'
import { commitCanvas, redoCanvas, sameCanvas, undoCanvas } from './canvasHistory'
import type { AppState, CanvasElement, ObjectKind, ThoughtObject } from './domain'
import { objectLabels } from './domain'
import { interpret } from './interpreter'
import { buildMorningDigest } from './morningDigest'
import { dependencyCandidates, unresolvedDependencies } from './dependencies'
import { canvasObjectDraft, confirmObject, fixedCommitments, parentCandidates, parentObject, projectChildren, recentObjects, confirmedActions, setObjectKind, updateObject } from './objectWorkflow'
import { loadStateResult, makeObject, newCanvasElement, saveState } from './store'

type View = 'today' | 'capture' | 'review' | 'objects' | 'commitments' | 'canvas'
const nav: { id: View; label: string; icon: string }[] = [
  { id: 'today', label: 'Today', icon: '◉' }, { id: 'capture', label: 'Capture', icon: '＋' }, { id: 'review', label: 'Review', icon: '◇' }, { id: 'objects', label: 'Objects', icon: '▤' }, { id: 'commitments', label: 'Commitments', icon: '□' }, { id: 'canvas', label: 'Canvas', icon: '⌁' }
]

export function App() {
  const [initial] = useState(loadStateResult)
  const [state, setState] = useState<AppState>(initial.state)
  const [saveError, setSaveError] = useState<string | undefined>()
  const [view, setView] = useState<View>('today')
  const [draft, setDraft] = useState('')
  const [context, setContext] = useState('')
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const update = (fn: (current: AppState) => AppState) => setState(current => fn(current))
  useEffect(() => { if (!initial.error) setSaveError(saveState(state)) }, [state, initial.error])
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
      {view === 'review' && <Review objects={state.objects.filter(item => item.status === 'review')} onChangeKind={changeKind} onConfirm={revise} onOpen={setSelectedObjectId} />}
      {view === 'objects' && <ObjectWorkbench objects={state.objects} onOpen={setSelectedObjectId} />}
      {view === 'commitments' && <Commitments objects={state.objects} onAdd={() => { setDraft(''); setView('capture') }} onOpen={setSelectedObjectId} />}
      {view === 'canvas' && <Canvas elements={state.canvas} onChange={canvas => update(current => ({ ...current, canvas }))} onCaptureObject={captureCanvasObject} />}
    </section>
    {selectedObject && <ObjectPanel key={selectedObject.id} object={selectedObject} objects={state.objects} onOpen={setSelectedObjectId} onClose={() => setSelectedObjectId(null)} onSave={saveObject} />}
  </main>
}

function Header({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) { return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>{action}</header> }
function Today({ objects, onCapture, onOpen }: { objects: ThoughtObject[]; onCapture: () => void; onOpen: (id: string) => void }) {
  const actions = confirmedActions(objects)
  const focus = actions[0]
  const blocked = objects.filter(item => item.kind === 'action' && item.status === 'confirmed' && unresolvedDependencies(item, objects).length > 0)
  const recent = recentObjects(objects)
  const digest = buildMorningDigest(objects)
  const commitments = digest.fixedToday
  const date = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date())
  return <div className="page"><Header eyebrow={date} title="Make space for the work that matters." action={<button className="primary" onClick={onCapture}>Capture a thought <span>↵</span></button>} />
    <section className="today-grid"><div className="focus-card"><p className="section-label">Recommended focus</p><h2>{focus?.originalContent ?? (blocked.length ? 'Your actions are waiting on prerequisites' : 'Start with a clean capture')}</h2><p>{focus ? 'One meaningful action selected from confirmed work with no unfinished prerequisites.' : blocked.length ? 'Open a waiting action to review what needs to happen first.' : 'Capture a thought to begin shaping your next action.'}</p>{focus && <div className="focus-meta"><span>◒ {focus.metadata.effort ?? 'unspecified'} effort</span><span>◌ {focus.metadata.attentionLoad ?? 'unspecified'} attention</span></div>}<button className="quiet-button" onClick={() => focus ? onOpen(focus.id) : blocked.length ? onOpen(blocked[0].id) : onCapture()}>{focus ? 'Open action' : blocked.length ? 'Review prerequisites' : 'Capture a thought'} →</button></div>
      <div className="day-summary"><p className="section-label">Available work</p><div className="orb"><b>{actions.length}</b><span>ready actions</span></div><p>{blocked.length > 0 && `${blocked.length} actions waiting on prerequisites. `}Your available hours haven’t been set. Choose work that fits your time and attention today.</p></div></section>
    <section className="digest-strip"><p className="section-label">Morning digest</p><div><span>{digest.fixedToday.length} fixed today</span><span>{digest.upcoming.length} upcoming</span><span>{digest.recommended.length} execution picks</span><span>{digest.needsReview.length} decisions</span><span>{digest.projectSignals.length} project signals</span></div></section>
    <section className="digest-details" aria-label="Digest details">{[
      { title: 'Upcoming commitments', items: digest.upcoming, limit: 3 },
      { title: 'Execution picks', items: digest.recommended, limit: 3 },
      { title: 'Needs your decision', items: digest.needsReview, limit: 5 },
      { title: 'Projects and objectives', items: digest.projectSignals, limit: 3 }
    ].map(group => <details key={group.title}><summary>{group.title} · {group.items.length} shown</summary><p>A focused selection of up to {group.limit}. Open a thought to review its details.</p>{group.items.length ? group.items.map(item => <ObjectRow item={item} objects={objects} key={item.id} onOpen={onOpen} />) : <Empty text="Nothing in this part of the digest right now." />}</details>)}</section>
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Fixed commitments</p><h2>Today</h2></div><span>{commitments.length} scheduled</span></div>{commitments.length ? commitments.map(item => <ObjectRow item={item} objects={objects} key={item.id} onOpen={onOpen} accent="commitment" />) : <Empty text="No fixed commitments today. Your execution plan is free to adapt." />}</section>
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Object workbench</p><h2>Recent captures</h2></div><span>{recent.length} visible</span></div>{recent.length ? recent.map(item => <ObjectRow item={item} objects={objects} key={item.id} onOpen={onOpen} />) : <Empty text="Capture something and it will appear here for shaping." />}</section>
  </div>
}
function Capture({ draft, context, onDraft, onContext, onCapture }: { draft: string; context: string; onDraft: (v: string) => void; onContext: (v: string) => void; onCapture: () => void }) { return <div className="page capture-page"><Header eyebrow="Raw capture" title="What’s on your mind?" /><p className="lede">Don’t decide what it is yet. Write it how you would say it.</p><div className="capture-box"><textarea autoFocus value={draft} onChange={event => onDraft(event.target.value)} placeholder="A thought, a loose end, an idea…" onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') onCapture() }} /><div className="capture-footer"><label>Context <input value={context} onChange={event => onContext(event.target.value)} placeholder="Optional — where this belongs" /></label><button className="primary" onClick={onCapture}>Interpret thought <span>⌘↵</span></button></div></div><div className="voice-placeholder"><span>⌁</span><div><strong>Voice capture</strong><p>Coming in the next pass. The source will remain attached to the same original thought.</p></div></div></div> }
function Review({ objects, onChangeKind, onConfirm, onOpen }: { objects: ThoughtObject[]; onChangeKind: (id: string, kind: ObjectKind) => void; onConfirm: (id: string, kind: ObjectKind) => void; onOpen: (id: string) => void }) {
  return <div className="page"><Header eyebrow="Decision interface" title="A few things need your judgment." />{objects.length === 0 ? <Empty text="Nothing is waiting for review. Ambiguous captures will appear here, with a proposed interpretation." /> : <div className="review-list">{objects.map(item => <article className="review-card" key={item.id}><div className="source-line"><span>Raw capture</span><time>{new Date(item.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div><blockquote>{item.originalContent}</blockquote><div className="proposal"><span className="spark">✦</span><div><p>I’d store this as an <strong>{objectLabels[item.kind]}</strong>.</p><small>{item.interpretation.rationale}</small></div><em>{Math.round(item.confidence * 100)}% confident</em></div><div className="review-actions"><select aria-label="Review object type" value={item.kind} onChange={event => onChangeKind(item.id, event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select><button className="secondary" onClick={() => onOpen(item.id)}>Adjust details</button><button className="primary" onClick={() => onConfirm(item.id, item.kind)}>Confirm interpretation</button></div></article>)}</div>}</div>
}
function ObjectRow({ item, objects, onOpen, accent }: { item: ThoughtObject; objects: ThoughtObject[]; onOpen: (id: string) => void; accent?: 'commitment' }) {
  const detail = item.metadata.deadline ?? item.interpretation.suggestedDate ?? item.context ?? item.interpretation.rationale
  const parent = parentObject(objects, item)
  return <button className={`commitment-row clickable-row ${accent === 'commitment' ? 'commitment-accent' : ''}`} onClick={() => onOpen(item.id)}><span className="time-dot"/><div><strong>{item.originalContent}</strong><small>{detail}</small></div>{parent && <span className="parent-chip">{parent.originalContent}</span>}<span className="status-chip">{item.status}</span><span className="kind-chip">{objectLabels[item.kind]}</span></button>
}
function ObjectWorkbench({ objects, onOpen }: { objects: ThoughtObject[]; onOpen: (id: string) => void }) {
  const [kind, setKind] = useState<ObjectKind | 'all'>('all')
  const [collection, setCollection] = useState('active')
  const [query, setQuery] = useState('')
  const normalized = query.trim().toLowerCase()
  const items = objects.filter(item =>
    (collection === 'all' || (collection === 'archived' ? item.status === 'archived' : item.status !== 'archived')) &&
    (kind === 'all' || item.kind === kind) &&
    (!normalized || `${item.originalContent} ${item.context ?? ''} ${item.interpretation.rationale}`.toLowerCase().includes(normalized))
  )
  return <div className="page"><Header eyebrow="Semantic system" title="Everything you can shape." /><div className="workbench-controls"><input aria-label="Search captured thoughts" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search captured thoughts" /><select aria-label="Filter by type" value={kind} onChange={event => setKind(event.target.value as ObjectKind | 'all')}><option value="all">All types</option>{(Object.keys(objectLabels) as ObjectKind[]).map(value => <option key={value} value={value}>{objectLabels[value]}</option>)}</select><select aria-label="Filter by archive status" value={collection} onChange={event => setCollection(event.target.value)}><option value="active">Active thoughts</option><option value="archived">Archived thoughts</option><option value="all">All thoughts</option></select></div>{collection === 'archived' && <p className="lede">Open a thought and change its status to bring it back into your work.</p>}<section className="list-section object-list">{items.length ? items.map(item => <ObjectRow item={item} objects={objects} key={item.id} onOpen={onOpen} />) : <Empty text="No matching thoughts." />}</section></div>
}
function Commitments({ objects, onAdd, onOpen }: { objects: ThoughtObject[]; onAdd: () => void; onOpen: (id: string) => void }) { const items = fixedCommitments(objects); const now = new Date(); return <div className="page"><Header eyebrow="External time" title="Commitments stay put." action={<button className="primary" onClick={onAdd}>Add commitment</button>} /><p className="lede">Meetings, appointments, deadlines, and events. This is separate from the flexible execution plan.</p><div className="calendar-grid"><div className="calendar-day"><p className="section-label">Today</p><b>{now.getDate()}</b><span>{new Intl.DateTimeFormat('en-US', { weekday: 'long' }).format(now)}</span></div><div className="calendar-list">{items.length ? items.map(item => <ObjectRow item={item} objects={objects} key={item.id} onOpen={onOpen} accent="commitment" />) : <Empty text="No commitments captured yet." />}</div></div></div> }
function ObjectPanel({ object, objects, onOpen, onClose, onSave }: { object: ThoughtObject; objects: ThoughtObject[]; onOpen: (id: string) => void; onClose: () => void; onSave: (object: ThoughtObject) => void }) {
  const [draft, setDraft] = useState(object)
  useEffect(() => setDraft(object), [object])
  const field = (key: keyof ThoughtObject, value: unknown) => setDraft(current => ({ ...current, [key]: value }))
  const metadata = (key: keyof ThoughtObject['metadata'], value: unknown) => setDraft(current => ({ ...current, metadata: { ...current.metadata, [key]: value || undefined } as ThoughtObject['metadata'] }))
  const parents = parentCandidates(objects, object.id)
  const children = projectChildren(objects, object.id)
  const parent = parentObject(objects, object)
  const hasUnsavedChanges = JSON.stringify(draft) !== JSON.stringify(object)
  const parentId = draft.relationships.find(item => item.type === 'belongs_to')?.targetId ?? ''
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
        <section className="interpretation"><p className="section-label">Recorded interpretation</p><strong>{object.interpretation.summary}</strong><small>Suggested type: {objectLabels[object.interpretation.suggestedKind]} · {Math.round(object.confidence * 100)}% recorded confidence</small><small>{object.interpretation.rationale}</small></section>
        {(parent || object.kind === 'project' || object.kind === 'objective') && <section className="project-contents"><h3>Project connections</h3>{hasUnsavedChanges && <p>Save or discard your edits before opening a connected thought.</p>}{parent && <button className="secondary" disabled={hasUnsavedChanges} onClick={() => onOpen(parent.id)}>Open parent: {parent.originalContent}</button>}{(object.kind === 'project' || object.kind === 'objective') && <><p>{children.length} linked thoughts · {children.filter(item => item.status === 'complete').length} complete</p>{children.length ? children.map(child => <button className="project-child" disabled={hasUnsavedChanges} key={child.id} onClick={() => onOpen(child.id)}><strong>{child.originalContent}</strong><small>{objectLabels[child.kind]} · {child.status}</small></button>) : <p>To add a thought here, open it and choose this project or objective as its parent.</p>}</>}</section>}
        <DependencyEditor object={draft} objects={objects} onChange={setDraft} />
        <div className="form-grid">
          <label>Type<select value={draft.kind} onChange={event => field('kind', event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select></label>
          <label>Status<select value={draft.status} onChange={event => field('status', event.target.value as ThoughtObject['status'])}>{['inbox', 'review', 'confirmed', 'complete', 'archived'].map(status => <option key={status} value={status}>{status}</option>)}</select></label>
          <label className="wide">Context or project<input value={draft.context ?? ''} onChange={event => field('context', event.target.value)} placeholder="Optional — e.g. a project or person" /></label>
          <label>Deadline<input type="date" value={draft.metadata.deadline ?? ''} onChange={event => metadata('deadline', event.target.value)} /></label>
          <label>Urgency{scoreSelect('urgency')}</label>
          <label>Effort<select value={draft.metadata.effort ?? ''} onChange={event => metadata('effort', event.target.value)}><option value="">Unspecified</option><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label>
          <label>Attention load{loadSelect('attentionLoad')}</label>
          <label>Strategic importance{scoreSelect('strategicImportance')}</label>
          <label>Resource cost{loadSelect('resourceCost')}</label>
          <label>Optional ROI{scoreSelect('roi')}</label>
          {(parents.length > 0 || parentId) && <label className="wide">Parent project or objective<select value={parentId} onChange={event => setDraft(current => ({ ...current, relationships: event.target.value ? [...current.relationships.filter(item => item.type !== 'belongs_to'), { targetId: event.target.value, type: 'belongs_to' }] : current.relationships.filter(item => item.type !== 'belongs_to') }))}><option value="">No parent</option>{parentId && !parents.some(item => item.id === parentId) && <option value={parentId} disabled>Unavailable parent — choose another or clear</option>}{parents.map(item => <option key={item.id} value={item.id}>{objectLabels[item.kind]} · {item.originalContent}</option>)}</select></label>}
        </div>
        <details className="object-history"><summary>History ({object.history.length})</summary>{object.history.length ? <ol>{object.history.slice().reverse().map((entry, index) => <li key={`${entry.at}-${index}`}><p>{entry.event}</p><time>{Number.isFinite(Date.parse(entry.at)) ? new Date(entry.at).toLocaleString() : 'Time unavailable'}</time></li>)}</ol> : <p>No history recorded for this thought.</p>}</details>
      </div>
      <footer><button className="secondary" onClick={() => { onSave({ ...draft, status: 'archived' }); onClose() }}>Archive</button><button className="secondary" onClick={() => { onSave({ ...draft, status: 'complete' }); onClose() }}>Complete</button><button className="primary" onClick={() => { onSave(draft); onClose() }}>Save changes</button></footer>
    </aside>
  </div>
}
function DependencyEditor({ object, objects, onChange }: { object: ThoughtObject; objects: ThoughtObject[]; onChange: (value: ThoughtObject) => void }) {
  const links = object.relationships.filter(link => link.type === 'depends_on')
  const candidates = dependencyCandidates(object, objects)
  const waiting = unresolvedDependencies(object, objects).length
  return <section className="dependency-editor"><h3>Dependencies</h3><p>{waiting ? `Waiting on ${waiting} prerequisite${waiting === 1 ? '' : 's'}. This thought will not be recommended as an action until they are complete or unlinked.` : 'No unfinished prerequisites.'}</p>
    {links.map(link => { const target = objects.find(item => item.id === link.targetId); return <div className="dependency-row" key={link.targetId}><span>{target?.originalContent ?? 'Unavailable thought'} · {target?.status ?? 'missing'}</span><button className="secondary" onClick={() => onChange({ ...object, relationships: object.relationships.filter(value => value.type !== 'depends_on' || value.targetId !== link.targetId) })} aria-label={`Unlink dependency ${target?.originalContent ?? 'Unavailable thought'}`}>Unlink</button></div> })}
    <label>Add prerequisite<select value="" onChange={event => { if (event.target.value) onChange({ ...object, relationships: [...object.relationships, { type: 'depends_on', targetId: event.target.value }] }) }}><option value="">Choose a thought</option>{candidates.map(item => <option key={item.id} value={item.id}>{item.originalContent}</option>)}</select></label>
  </section>
}
function Canvas({ elements, onChange, onCaptureObject }: { elements: CanvasElement[]; onChange: (elements: CanvasElement[]) => void; onCaptureObject: (element: CanvasElement) => void }) {
  const [pan, setPan] = useState({ x: 0, y: 0 }); const [scale, setScale] = useState(1); const [selected, setSelected] = useState<string | null>(null); const [connectFrom, setConnectFrom] = useState<string | null>(null); const [past, setPast] = useState<CanvasElement[][]>([]); const [future, setFuture] = useState<CanvasElement[][]>([]); const drag = useRef<{ id?: string; startX: number; startY: number; originalX?: number; originalY?: number; pan?: boolean; originalPan?: { x: number; y: number }; before?: CanvasElement[] } | null>(null)
  const positioned = (id?: string) => elements.find(item => item.id === id)
  const commit = (next: CanvasElement[]) => {
    const history = commitCanvas({ past, present: elements, future }, next)
    setPast(history.past); setFuture(history.future); onChange(history.present)
  }
  const textBefore = useRef<CanvasElement[] | null>(null)
  const startTextEdit = (event: React.FocusEvent) => { if (event.target instanceof HTMLTextAreaElement) textBefore.current = elements }
  const endTextEdit = () => {
    if (!textBefore.current) return
    const history = commitCanvas({ past, present: textBefore.current, future }, elements)
    setPast(history.past); setFuture(history.future); textBefore.current = null
  }
  const add = (type: 'text' | 'container') => { const next = newCanvasElement(type, (260 - pan.x) / scale, (160 - pan.y) / scale); commit([...elements, next]); setSelected(next.id) }
  const down = (event: React.PointerEvent, item?: CanvasElement) => { const point = { startX: event.clientX, startY: event.clientY }; drag.current = item ? { ...point, id: item.id, originalX: item.x, originalY: item.y, before: elements } : { ...point, pan: true, originalPan: pan }; (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId) }
  const move = (event: React.PointerEvent) => { if (!drag.current) return; const dx = (event.clientX - drag.current.startX) / scale; const dy = (event.clientY - drag.current.startY) / scale; if (drag.current.pan) setPan({ x: drag.current.originalPan!.x + dx * scale, y: drag.current.originalPan!.y + dy * scale }); else if (drag.current.id) onChange(elements.map(item => item.id === drag.current!.id ? { ...item, x: drag.current!.originalX! + dx, y: drag.current!.originalY! + dy } : item)) }
  const end = () => { if (drag.current?.id && drag.current.before && !sameCanvas(drag.current.before, elements)) { const history = commitCanvas({ past, present: drag.current.before, future }, elements); setPast(history.past); setFuture(history.future) } drag.current = null }
  const clickNode = (event: React.MouseEvent, id: string) => { event.stopPropagation(); if (connectFrom && connectFrom !== id) { commit([...elements, { id: crypto.randomUUID(), type: 'arrow', x: 0, y: 0, fromId: connectFrom, toId: id }]); setConnectFrom(null) } else setSelected(id) }
  const arrows = elements.filter(item => item.type === 'arrow')
  const selectedElement = selected ? positioned(selected) : undefined
  const canCaptureSelected = Boolean(selectedElement?.text?.trim() && selectedElement.type !== 'arrow')
  const removeSelected = () => { if (!selected) return; commit(elements.filter(item => item.id !== selected && item.fromId !== selected && item.toId !== selected)); setSelected(null); setConnectFrom(null) }
  const undo = () => { const history = undoCanvas({ past, present: elements, future }); setPast(history.past); setFuture(history.future); onChange(history.present); setSelected(null); setConnectFrom(null) }
  const redo = () => { const history = redoCanvas({ past, present: elements, future }); setPast(history.past); setFuture(history.future); onChange(history.present); setSelected(null); setConnectFrom(null) }
  const keyCanvas = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement
    if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') return
    if (!(event.metaKey || event.ctrlKey)) return
    if (event.key.toLowerCase() === 'z' && event.shiftKey && future.length) { event.preventDefault(); redo(); return }
    if (event.key.toLowerCase() === 'z' && past.length) { event.preventDefault(); undo(); return }
    if (event.key.toLowerCase() === 'y' && future.length) { event.preventDefault(); redo() }
  }
  return <div className="canvas-page" tabIndex={0} onKeyDown={keyCanvas} onFocusCapture={startTextEdit} onBlurCapture={endTextEdit}><div className="canvas-head"><div><p className="eyebrow">Spatial formulation</p><h1>Untitled canvas</h1></div><div className="canvas-tools"><button disabled={!past.length} onClick={undo}>↶ Undo</button><button disabled={!future.length} onClick={redo}>↷ Redo</button><button onClick={() => add('text')}>+ Text</button><button onClick={() => add('container')}>+ Group</button><button disabled={!selected} className={connectFrom ? 'selected-tool' : ''} onClick={() => setConnectFrom(connectFrom ? null : selected)}>↗ Connect</button><button disabled={!canCaptureSelected} onClick={() => selectedElement && onCaptureObject(selectedElement)}>Capture node</button><button disabled={!selected} onClick={removeSelected}>Delete</button><span/><button onClick={() => setScale(value => Math.max(.55, value - .15))}>−</button><span>{Math.round(scale * 100)}%</span><button onClick={() => setScale(value => Math.min(1.6, value + .15))}>＋</button></div></div><div className="canvas-note">{connectFrom ? 'Select another thought to draw the connection.' : 'Use the grip to move thoughts · drag empty space to pan · edit text directly'}</div><div className="canvas" onPointerDown={event => down(event)} onPointerMove={move} onPointerUp={end} onPointerLeave={end} onClick={() => setSelected(null)}><div className="canvas-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }}><svg className="arrows" aria-hidden="true">{arrows.map(arrow => { const from = positioned(arrow.fromId); const to = positioned(arrow.toId); if (!from || !to) return null; return <line key={arrow.id} x1={from.x + (from.width ?? 160) / 2} y1={from.y + 42} x2={to.x + (to.width ?? 160) / 2} y2={to.y + 22} markerEnd="url(#head)" /> })}<defs><marker id="head" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" /></marker></defs></svg>{elements.filter(item => item.type !== 'arrow').map(item => <div key={item.id} className={`canvas-node ${item.type} ${selected === item.id ? 'selected' : ''}`} style={{ left: item.x, top: item.y, width: item.width, height: item.height }} onClick={event => clickNode(event, item.id)}><div className="canvas-drag-handle" title="Move thought" onPointerDown={event => { event.stopPropagation(); down(event, item) }}><span></span><span></span><span></span></div>{item.type === 'container' && <small>GROUP</small>}<textarea value={item.text} onChange={event => onChange(elements.map(value => value.id === item.id ? { ...value, text: event.target.value } : value))} onPointerDown={event => event.stopPropagation()} /></div>)}</div></div></div>
}
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
