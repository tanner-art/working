import { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import type { AppState, CanvasElement, ObjectKind, ThoughtObject } from './domain'
import { objectLabels } from './domain'
import { interpret } from './interpreter'
import { loadState, makeObject, newCanvasElement, saveState } from './store'
import './styles.css'

type View = 'today' | 'capture' | 'review' | 'commitments' | 'canvas'
const nav: { id: View; label: string; icon: string }[] = [
  { id: 'today', label: 'Today', icon: '◉' }, { id: 'capture', label: 'Capture', icon: '＋' }, { id: 'review', label: 'Review', icon: '◇' }, { id: 'commitments', label: 'Commitments', icon: '□' }, { id: 'canvas', label: 'Canvas', icon: '⌁' }
]

function App() {
  const [state, setState] = useState<AppState>(loadState)
  const [view, setView] = useState<View>('today')
  const [draft, setDraft] = useState('')
  const [context, setContext] = useState('')
  const update = (fn: (current: AppState) => AppState) => setState(current => fn(current))
  useEffect(() => saveState(state), [state])
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
  const revise = (id: string, kind: ObjectKind, status: ThoughtObject['status'] = 'confirmed') => update(current => ({ ...current, objects: current.objects.map(item => item.id === id ? { ...item, kind, status, confidence: 1, history: [...item.history, { at: new Date().toISOString(), event: `Confirmed as ${kind}` }] } : item) }))
  return <main className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">⊹</span><span>threadline</span></div><nav>{nav.map(item => <button className={view === item.id ? 'nav-item active' : 'nav-item'} key={item.id} onClick={() => setView(item.id)}><span>{item.icon}</span>{item.label}{item.id === 'review' && reviewCount > 0 && <b>{reviewCount}</b>}</button>)}</nav><div className="sidebar-bottom"><span className="avatar">D</span><span>Personal space</span></div></aside>
    <section className="content">
      {view === 'today' && <Today objects={state.objects} onCapture={() => setView('capture')} />}
      {view === 'capture' && <Capture draft={draft} context={context} onDraft={setDraft} onContext={setContext} onCapture={capture} />}
      {view === 'review' && <Review objects={state.objects.filter(item => item.status === 'review')} onConfirm={revise} />}
      {view === 'commitments' && <Commitments objects={state.objects} onAdd={() => { setDraft(''); setView('capture') }} />}
      {view === 'canvas' && <Canvas elements={state.canvas} onChange={canvas => update(current => ({ ...current, canvas }))} />}
    </section>
  </main>
}

function Header({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) { return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>{action}</header> }
function Today({ objects, onCapture }: { objects: ThoughtObject[]; onCapture: () => void }) {
  const commitments = objects.filter(item => item.kind === 'commitment' && item.status === 'confirmed')
  const actions = objects.filter(item => item.kind === 'action' && item.status === 'confirmed')
  return <div className="page"><Header eyebrow="Saturday, September 13" title="Make space for the work that matters." action={<button className="primary" onClick={onCapture}>Capture a thought <span>↵</span></button>} />
    <section className="today-grid"><div className="focus-card"><p className="section-label">Recommended focus</p><h2>{actions[0]?.originalContent ?? 'Start with a clean capture'}</h2><p>One meaningful action, selected from confirmed work—not an overflowing task list.</p><div className="focus-meta"><span>◒ {actions[0]?.metadata.effort ?? 'small'} effort</span><span>◌ {actions[0]?.metadata.attentionLoad ?? 'low'} attention</span></div><button className="quiet-button">Start focus →</button></div>
      <div className="day-summary"><p className="section-label">Attention budget</p><div className="orb"><b>{Math.max(2, 5 - actions.length)}</b><span>open hours</span></div><p>Keep the plan spacious. It can move as your day changes.</p></div></section>
    <section className="list-section"><div className="section-heading"><div><p className="section-label">Fixed commitments</p><h2>Today</h2></div><span>{commitments.length} scheduled</span></div>{commitments.length ? commitments.map(item => <div className="commitment-row" key={item.id}><span className="time-dot"/><div><strong>{item.originalContent}</strong><small>{item.interpretation.suggestedDate ?? 'Time to confirm'}</small></div><span className="kind-chip">Commitment</span></div>) : <Empty text="No fixed commitments today. Your execution plan is free to adapt." />}</section>
  </div>
}
function Capture({ draft, context, onDraft, onContext, onCapture }: { draft: string; context: string; onDraft: (v: string) => void; onContext: (v: string) => void; onCapture: () => void }) { return <div className="page capture-page"><Header eyebrow="Raw capture" title="What’s on your mind?" /><p className="lede">Don’t decide what it is yet. Write it how you would say it.</p><div className="capture-box"><textarea autoFocus value={draft} onChange={event => onDraft(event.target.value)} placeholder="A thought, a loose end, an idea…" onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') onCapture() }} /><div className="capture-footer"><label>Context <input value={context} onChange={event => onContext(event.target.value)} placeholder="Optional — where this belongs" /></label><button className="primary" onClick={onCapture}>Interpret thought <span>⌘↵</span></button></div></div><div className="voice-placeholder"><span>⌁</span><div><strong>Voice capture</strong><p>Coming in the next pass. The source will remain attached to the same original thought.</p></div></div></div> }
function Review({ objects, onConfirm }: { objects: ThoughtObject[]; onConfirm: (id: string, kind: ObjectKind) => void }) { return <div className="page"><Header eyebrow="Decision interface" title="A few things need your judgment." />{objects.length === 0 ? <Empty text="Nothing is waiting for review. Ambiguous captures will appear here, with a proposed interpretation." /> : <div className="review-list">{objects.map(item => <article className="review-card" key={item.id}><div className="source-line"><span>Raw capture</span><time>{new Date(item.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div><blockquote>{item.originalContent}</blockquote><div className="proposal"><span className="spark">✦</span><div><p>I’d store this as an <strong>{objectLabels[item.kind]}</strong>.</p><small>{item.interpretation.rationale}</small></div><em>{Math.round(item.confidence * 100)}% confident</em></div><div className="review-actions"><select value={item.kind} onChange={event => onConfirm(item.id, event.target.value as ObjectKind)}>{(Object.keys(objectLabels) as ObjectKind[]).slice(0, 4).map(kind => <option key={kind} value={kind}>{objectLabels[kind]}</option>)}</select><button className="primary" onClick={() => onConfirm(item.id, item.kind)}>Confirm interpretation</button></div></article>)}</div>}</div> }
function Commitments({ objects, onAdd }: { objects: ThoughtObject[]; onAdd: () => void }) { const items = objects.filter(item => item.kind === 'commitment' || item.kind === 'reminder'); return <div className="page"><Header eyebrow="External time" title="Commitments stay put." action={<button className="primary" onClick={onAdd}>Add commitment</button>} /><p className="lede">Meetings, appointments, deadlines, and events. This is separate from the flexible execution plan.</p><div className="calendar-grid"><div className="calendar-day"><p className="section-label">Today</p><b>13</b><span>Saturday</span></div><div className="calendar-list">{items.length ? items.map(item => <div className="commitment-row" key={item.id}><span className="time-dot"/><div><strong>{item.originalContent}</strong><small>{item.interpretation.suggestedDate ?? 'Needs a date'}</small></div><span className="kind-chip">{objectLabels[item.kind]}</span></div>) : <Empty text="No commitments captured yet." />}</div></div></div> }
function Canvas({ elements, onChange }: { elements: CanvasElement[]; onChange: (elements: CanvasElement[]) => void }) {
  const [pan, setPan] = useState({ x: 0, y: 0 }); const [scale, setScale] = useState(1); const [selected, setSelected] = useState<string | null>(null); const [connectFrom, setConnectFrom] = useState<string | null>(null); const drag = useRef<{ id?: string; startX: number; startY: number; originalX?: number; originalY?: number; pan?: boolean; originalPan?: { x: number; y: number } } | null>(null)
  const positioned = (id?: string) => elements.find(item => item.id === id)
  const add = (type: 'text' | 'container') => { const next = newCanvasElement(type, 260 - pan.x, 160 - pan.y); onChange([...elements, next]); setSelected(next.id) }
  const down = (event: React.PointerEvent, item?: CanvasElement) => { const point = { startX: event.clientX, startY: event.clientY }; drag.current = item ? { ...point, id: item.id, originalX: item.x, originalY: item.y } : { ...point, pan: true, originalPan: pan }; (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId) }
  const move = (event: React.PointerEvent) => { if (!drag.current) return; const dx = (event.clientX - drag.current.startX) / scale; const dy = (event.clientY - drag.current.startY) / scale; if (drag.current.pan) setPan({ x: drag.current.originalPan!.x + dx * scale, y: drag.current.originalPan!.y + dy * scale }); else if (drag.current.id) onChange(elements.map(item => item.id === drag.current!.id ? { ...item, x: drag.current!.originalX! + dx, y: drag.current!.originalY! + dy } : item)) }
  const end = () => { drag.current = null }
  const clickNode = (event: React.MouseEvent, id: string) => { event.stopPropagation(); if (connectFrom && connectFrom !== id) { onChange([...elements, { id: crypto.randomUUID(), type: 'arrow', x: 0, y: 0, fromId: connectFrom, toId: id }]); setConnectFrom(null) } else setSelected(id) }
  const arrows = elements.filter(item => item.type === 'arrow')
  return <div className="canvas-page"><div className="canvas-head"><div><p className="eyebrow">Spatial formulation</p><h1>Untitled canvas</h1></div><div className="canvas-tools"><button onClick={() => add('text')}>+ Text</button><button onClick={() => add('container')}>+ Group</button><button className={connectFrom ? 'selected-tool' : ''} onClick={() => setConnectFrom(connectFrom ? null : selected)}>↗ Connect</button><span/><button onClick={() => setScale(value => Math.max(.55, value - .15))}>−</button><span>{Math.round(scale * 100)}%</span><button onClick={() => setScale(value => Math.min(1.6, value + .15))}>＋</button></div></div><div className="canvas-note">{connectFrom ? 'Select another thought to draw the connection.' : 'Drag to move thoughts · drag empty space to pan · select a thought, then connect'}</div><div className="canvas" onPointerDown={event => down(event)} onPointerMove={move} onPointerUp={end} onPointerLeave={end} onClick={() => setSelected(null)}><div className="canvas-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }}><svg className="arrows" aria-hidden="true">{arrows.map(arrow => { const from = positioned(arrow.fromId); const to = positioned(arrow.toId); if (!from || !to) return null; return <line key={arrow.id} x1={from.x + (from.width ?? 160) / 2} y1={from.y + 42} x2={to.x + (to.width ?? 160) / 2} y2={to.y + 22} markerEnd="url(#head)" /> })}<defs><marker id="head" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" /></marker></defs></svg>{elements.filter(item => item.type !== 'arrow').map(item => <div key={item.id} className={`canvas-node ${item.type} ${selected === item.id ? 'selected' : ''}`} style={{ left: item.x, top: item.y, width: item.width, height: item.height }} onPointerDown={event => { event.stopPropagation(); down(event, item) }} onClick={event => clickNode(event, item.id)}>{item.type === 'container' && <small>GROUP</small>}<textarea value={item.text} onChange={event => onChange(elements.map(value => value.id === item.id ? { ...value, text: event.target.value } : value))} onPointerDown={event => event.stopPropagation()} /></div>)}</div></div></div>
}
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
createRoot(document.getElementById('root')!).render(<App />)
