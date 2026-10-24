import { useEffect, useMemo, useRef, useState } from 'react'
import type { WorkspaceSurfaceProps } from './appSurfaceRegistry'
import { brainKindLabels, buildBrain, filterBrain, layoutBrain } from './brain'
import './brainChat.css'

export function BrainView({ state, snapshotToken, readModel, navigate }: WorkspaceSurfaceProps) {
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState('')
  const [mode, setMode] = useState<'map' | 'groups'>('map')
  const [selected, setSelected] = useState('')
  const [message, setMessage] = useState('')
  const [zoom, setZoom] = useState(1)
  const [limit, setLimit] = useState(40)
  const [mapWidth, setMapWidth] = useState(960)
  const mapContainer = useRef<HTMLDivElement>(null)
  const detail = useRef<HTMLElement>(null)
  useEffect(() => { if (selected) detail.current?.scrollIntoView({ block: 'nearest' }) }, [selected])
  const model = useMemo(() => buildBrain(state, readModel), [state, readModel])
  const filtered = useMemo(() => filterBrain(model, query, group), [model, query, group])
  const visible = filtered.nodes.slice(0, 160)
  const layout = useMemo(() => layoutBrain(visible, mapWidth), [filtered, mapWidth])
  useEffect(() => {
    if (!mapContainer.current) return
    const observer = new ResizeObserver(entries => { if (entries[0]?.contentRect.width) setMapWidth(entries[0].contentRect.width) })
    observer.observe(mapContainer.current)
    return () => observer.disconnect()
  }, [mode, !!filtered.nodes.length])
  const chosen = filtered.nodes.find(n => n.id === selected)
  const groupLabels = new Map(model.nodes.map(n => [n.group, n.groupLabel]))
  const neighbors = chosen ? model.links.filter(l => l.source === chosen.id || l.target === chosen.id) : []
  const open = (id: string) => {
    const node = model.nodes.find(n => n.id === id)
    if (!node) return
    const result = navigate({ type: 'open-search-result', document: node.document, snapshotToken })
    if (!result.ok) setMessage(result.message)
  }
  return <main className="page brain-page" data-swipe-ignore aria-labelledby="brain-title">
    <header className="page-header"><div><p className="eyebrow">Your thoughts, connected</p><h1 id="brain-title">Brain</h1></div><button className="secondary" onClick={() => { const r = navigate({ type: 'close-surface' }); if (!r.ok) setMessage(r.message) }}>Close</button></header>
    <div className="brain-controls"><label className="brain-search">Search everything<input type="search" placeholder="Find a thought, idea or canvas…" value={query} onChange={e => { setQuery(e.target.value); setLimit(40) }} /></label><label>Group<select value={group} onChange={e => { setGroup(e.target.value); setLimit(40) }}><option value="">All groups</option>{[...groupLabels].sort((a, b) => a[1].localeCompare(b[1])).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
    <div className="brain-view-controls"><div role="group" aria-label="Brain view"><button aria-pressed={mode === 'map'} onClick={() => setMode('map')}>Connections</button><button aria-pressed={mode === 'groups'} onClick={() => setMode('groups')}>Groups</button></div><p role="status">{filtered.nodes.length} items</p></div>
    {(message || model.incomplete) && <p role="alert">{message || 'Some workspace items could not be read. This is a partial view.'}</p>}
    {!filtered.nodes.length ? <p className="empty">{query || group ? 'No matching items. Try another search or group.' : 'Your captures, ideas and canvases will appear here.'}</p> : <>
      {mode === 'map' ? <section className="brain-map-shell" aria-label="Connection map">
        <div className="brain-zoom"><button className="secondary" aria-label="Zoom out" onClick={() => setZoom(z => Math.max(.5, z - .25))}>−</button><button className="secondary" onClick={() => setZoom(1)}>Reset</button><button className="secondary" aria-label="Zoom in" onClick={() => setZoom(z => Math.min(3, z + .25))}>+</button></div>
        <div ref={mapContainer} className="brain-map-scroll" tabIndex={0} aria-label="Scrollable connection map">
          <svg className="brain-map" width={layout.width * zoom} height={layout.height * zoom} viewBox={`0 0 ${layout.width} ${layout.height}`} aria-label="Thought connections">
            {filtered.links.map((link, i) => { const a = layout.positions.get(link.source), b = layout.positions.get(link.target); return a && b ? <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={selected === link.source || selected === link.target ? 'highlight' : ''}><title>{link.label}</title></line> : null })}
            {visible.map(node => { const p = layout.positions.get(node.id)!; return <g key={node.id} transform={`translate(${p.x} ${p.y})`} role="button" tabIndex={0} aria-label={`${brainKindLabels[node.document.kind]}: ${node.title}`} aria-pressed={selected === node.id} onClick={() => setSelected(node.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(node.id) } }} className={`brain-node kind-${node.document.kind}${selected === node.id ? ' selected' : ''}`}><circle r="22" className="brain-hit" /><circle r={selected === node.id ? 10 : 7} /><text y="29" textAnchor="middle">{node.title.length > 23 ? `${node.title.slice(0, 23)}…` : node.title}</text><title>{node.title}</title></g> })}
          </svg>
        </div>
        <p className="brain-caption">Lines show source links and confirmed connections. Nearby items share a group—not an inferred relationship. Scroll to explore; select a dot to inspect.</p>
        {filtered.nodes.length > visible.length && <p role="status">Showing the first {visible.length} items on the map. Search to narrow it, or use Groups to browse every item.</p>}
      </section> : <div className="brain-groups">{[...new Set(filtered.nodes.slice(0, limit).map(n => n.group))].sort().map(g => <section key={g} className="brain-group"><h2>{groupLabels.get(g)}</h2>{filtered.nodes.slice(0, limit).filter(n => n.group === g).map(node => <button key={node.id} onClick={() => setSelected(node.id)}><small>{brainKindLabels[node.document.kind]}</small><span>{node.title}</span></button>)}</section>)}{limit < filtered.nodes.length && <button className="secondary" onClick={() => setLimit(n => n + 40)}>Show more items</button>}</div>}
      {chosen && <section ref={detail} className="brain-detail" aria-label="Selected thought"><div className="brain-detail-heading"><small>{brainKindLabels[chosen.document.kind]} · {chosen.groupLabel}</small><button className="secondary" aria-label="Deselect thought" onClick={() => setSelected('')}>×</button></div><h2>{chosen.title}</h2><button className="primary" onClick={() => open(chosen.id)}>Open item</button>{neighbors.length > 0 && <><h3>Connected to</h3><ul>{neighbors.map((link, i) => { const node = model.nodes.find(n => n.id === (link.source === chosen.id ? link.target : link.source)); return node && <li key={i}><button className="secondary" onClick={() => { setGroup(''); setQuery(''); setSelected(node.id) }}>{node.title}</button><small>{link.label}</small></li> })}</ul></>}</section>}
    </>}
  </main>
}
