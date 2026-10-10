import { useEffect, useRef, useState } from 'react'
import { listCanvases } from './canvasBank'
import { filterCanvasesByTitle } from './canvasBankSearch'
import type { CanvasBank as CanvasBankModel, ThoughtObject } from './domain'
import type { ConnectionGraph } from './semanticLinks'

function GraphPreview({ graph }: { graph: ConnectionGraph }) {
  const columns = 4
  const rows = Math.ceil(graph.nodes.length / columns)
  const height = Math.max(170, rows * 120 + 30)
  const position = new Map(graph.nodes.map((node, index) => [node.id, {
    x: 120 + (index % columns) * 190, y: 85 + Math.floor(index / columns) * 120,
  }]))
  return <div className="connection-graph-scroll" aria-hidden="true"><svg viewBox={`0 0 800 ${height}`} role="presentation">
    {graph.links.map(link => {
      const source = position.get(link.sourceId)
      const target = position.get(link.targetId)
      return source && target ? <line key={link.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} /> : null
    })}
    {graph.nodes.map(node => {
      const point = position.get(node.id)!
      return <g key={node.id}><circle cx={point.x} cy={point.y} r="36" /><text x={point.x} y={point.y + 56} textAnchor="middle">{node.label.slice(0, 24)}</text></g>
    })}
  </svg></div>
}

export function CanvasBank({ bank, ideas, connections, focusTarget, onCreate, onOpen, onOpenIdea, onConnect }: {
  bank: CanvasBankModel
  ideas: ThoughtObject[]
  connections?: ConnectionGraph
  focusTarget: 'create' | string | null
  onCreate: () => void
  onOpen: (id: string) => void
  onOpenIdea: (id: string) => void
  onConnect?: (sourceId: string, targetId: string) => void
}) {
  const createRef = useRef<HTMLButtonElement>(null)
  const cardRefs = useRef(new Map<string, HTMLButtonElement>())
  const [search, setSearch] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [targetId, setTargetId] = useState('')
  const [connectionMessage, setConnectionMessage] = useState('')
  const canvases = listCanvases(bank)
  const matchingCanvases = filterCanvasesByTitle(canvases, search)
  const hasSearch = search.trim().length > 0
  useEffect(() => {
    if (!focusTarget) return
    ;(focusTarget === 'create' ? createRef.current : cardRefs.current.get(focusTarget))?.focus()
  }, [focusTarget])
  return <div className="page canvas-bank-page">
    <header className="canvas-bank-header">
      <div><p className="eyebrow">Visual thinking</p><h1>Canvas Bank</h1><p className="lede">Open a canvas or begin a new space for your ideas.</p></div>
      <button ref={createRef} className="primary canvas-create" onClick={onCreate}>Think visually <span aria-hidden="true">＋</span></button>
    </header>
    {canvases.length === 0 ? <section className="canvas-bank-empty"><h2>Your canvases will live here.</h2><p>Create one to start thinking visually. It saves automatically on this device or in your active account workspace.</p></section> :
      <>
        <div style={{ display: 'grid', gap: 8, marginBottom: 20 }}>
          <label htmlFor="canvas-bank-search">Search canvases</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <input id="canvas-bank-search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search by title" style={{ minWidth: 0, flex: '1 1 220px' }} />
            {hasSearch && <button type="button" onClick={() => setSearch('')}>Clear search</button>}
          </div>
          <p aria-live="polite" style={{ margin: 0 }}>{matchingCanvases.length} {matchingCanvases.length === 1 ? 'canvas' : 'canvases'} {hasSearch ? 'found' : 'saved'}</p>
        </div>
        {matchingCanvases.length === 0 ? <section className="canvas-bank-empty" aria-live="polite"><h2>No canvases match “{search.trim()}”.</h2><p>Try another title or clear your search to see every saved canvas.</p><button type="button" onClick={() => setSearch('')}>Clear search</button></section> :
          <section className="canvas-bank-grid" aria-label="Saved canvases">{matchingCanvases.map(canvas => <button
            ref={element => { if (element) cardRefs.current.set(canvas.id, element); else cardRefs.current.delete(canvas.id) }}
            className="canvas-bank-card" key={canvas.id} onClick={() => onOpen(canvas.id)} aria-label={`Open ${canvas.title}`}>
            <span className="canvas-card-visual" aria-hidden="true"><i/><i/><i/></span>
            <span className="canvas-card-copy"><strong>{canvas.title}</strong><small>{canvas.elements.length} {canvas.elements.length === 1 ? 'block' : 'blocks'}</small><small>{canvas.updatedAt.startsWith('1970-') ? 'Recovered from your original canvas' : `Edited ${new Date(canvas.updatedAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}`}</small></span>
            <span aria-hidden="true">→</span>
          </button>)}</section>}
      </>}
    <section className="canvas-bank-ideas" aria-labelledby="canvas-bank-ideas-heading">
      <h2 id="canvas-bank-ideas-heading">Ideas <span>{ideas.length}</span></h2>
      {ideas.length === 0 ? <p className="canvas-bank-ideas-empty">No resolved ideas yet.</p> :
        <div className="canvas-bank-idea-list">{ideas.map(item => <button key={item.id} className="canvas-bank-idea" onClick={() => onOpenIdea(item.id)} aria-label={`Open idea: ${item.currentContent ?? item.originalContent}`}>
          <strong>{item.currentContent ?? item.originalContent}</strong><small>{item.interpretation.summary}</small><span aria-hidden="true">→</span>
        </button>)}</div>}
    </section>
    {connections && onConnect && <section className="connection-section" aria-labelledby="connections-heading">
      <h2 id="connections-heading">Connections <span>{connections.links.length}</span></h2>
      <p>Only links you confirm appear here. Canvas arrows and older unverified links stay separate.</p>
      <details className="connection-add"><summary>＋ Connect thoughts</summary>
        <form onSubmit={event => { event.preventDefault(); try { onConnect(sourceId, targetId); setConnectionMessage('Connection added. Check save status above.'); setSourceId(''); setTargetId('') } catch (error) { setConnectionMessage(error instanceof Error ? error.message : 'Connection was not added.') } }}>
          <label>From<select required value={sourceId} onChange={event => setSourceId(event.target.value)}><option value="">Choose thought</option>{connections.candidates.map(node => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
          <label>To<select required value={targetId} onChange={event => setTargetId(event.target.value)}><option value="">Choose thought</option>{connections.candidates.filter(node => node.id !== sourceId).map(node => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
          <button type="submit" disabled={connections.candidates.length < 2}>Connect</button>
        </form>
        {connectionMessage && <p role={connectionMessage.startsWith('Connection added') ? 'status' : 'alert'}>{connectionMessage}</p>}
      </details>
      {connections.links.length === 0 ? <p className="connection-empty">No confirmed connections yet.</p> : <>
        <GraphPreview graph={connections} />
        <ul className="connection-list">{connections.links.map(link => {
          const source = connections.nodes.find(node => node.id === link.sourceId)
          const target = connections.nodes.find(node => node.id === link.targetId)
          return source && target ? <li key={link.id}><button onClick={() => onOpenIdea(source.id)} aria-label={`Open ${source.label}`}>{source.label}</button><span aria-hidden="true">↔</span><button onClick={() => onOpenIdea(target.id)} aria-label={`Open ${target.label}`}>{target.label}</button></li> : null
        })}</ul>
      </>}
    </section>}
  </div>
}
