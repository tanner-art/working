import { useEffect, useRef, useState } from 'react'
import type { CanvasElement, CanvasViewport } from './domain'
import { newCanvasElement } from './canvasDocument'
import { CANVAS_SIZE, canvasShapeLabels, canvasNodeShape, canvasSize, canvasConnectorPath, connectionAppearance, resizeCanvasNode, convertCanvasNode, updateCanvasConnection, type CanvasShape, type ConnectionPath, type ConnectionPattern, type ConnectionWeight } from './canvasGeometry'
import { attachBlocksInside, canvasGroups, moveCanvasNode, removeCanvasNode, setCanvasGroup } from './canvasGroups'

export function Canvas({ elements, viewport, onViewport, onCommit, onText, onFinishText, canUndo, canRedo, onUndo, onRedo, onCaptureObject, onExit, saveStatus }: {
  elements: CanvasElement[]; viewport: CanvasViewport; onViewport: (viewport: CanvasViewport) => void
  onCommit: (elements: CanvasElement[]) => void; onText: (id: string, text: string) => void; onFinishText: () => void
  canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void
  onCaptureObject: (element: CanvasElement) => void; onExit: () => void; saveStatus: string
}) {
  const [panPreview, setPanPreview] = useState<{ x: number; y: number } | null>(null)
  const pan = panPreview ?? viewport, scale = viewport.scale
  const [selected, setSelected] = useState<string | null>(null); const [connectFrom, setConnectFrom] = useState<string | null>(null)
  // Undo/redo (and delete) can remove the currently selected or connect-from node out
  // from under this component without it ever unmounting. Clear any reference to an id
  // that no longer exists so a stale connect-from can never produce a dangling arrow.
  useEffect(() => {
    const ids = new Set(elements.map(item => item.id))
    setSelected(current => (current && !ids.has(current)) ? null : current)
    setConnectFrom(current => (current && !ids.has(current)) ? null : current)
  }, [elements])
  // Pointer previews are transient; only completed gestures become edits.
  const [resizePreview, setResizePreview] = useState<CanvasElement | null>(null)
  const [dragOffset, setDragOffset] = useState<{ id: string; dx: number; dy: number } | null>(null)
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
    } else if (drag.current.pan) setPanPreview({ x: drag.current.originalPan!.x + dx * scale, y: drag.current.originalPan!.y + dy * scale })
    else if (drag.current.id) setDragOffset({ id: drag.current.id, dx, dy })
  }
  const cancel = () => { drag.current = null; setPanPreview(null); setDragOffset(null); setResizePreview(null) }
  const end = (event: React.PointerEvent) => {
    if (drag.current?.pointerId !== event.pointerId) return
    const current = drag.current
    drag.current = null
    if (current && !current.pan && current.id && current.moved) {
      const size = current.resize && canvasSize(current.resize)
      const next = size ? resizeCanvasNode(elements, current.id, size.width + current.dx, size.height + current.dy) : moveCanvasNode(elements, current.id, current.originalX! + current.dx, current.originalY! + current.dy)
      onCommit(next)
    }
    if (current.pan && current.moved) onViewport({ x: current.originalPan!.x + current.dx * scale, y: current.originalPan!.y + current.dy * scale, scale })
    setPanPreview(null)
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
  return <div className="canvas-page">
    <div className="canvas-head">
    <div>
    <button className="canvas-exit" onClick={onExit}>← Back to Today</button>
    <h1>Untitled canvas</h1>
    <p className="canvas-save-status" role="status">{saveStatus}</p>
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
    <button aria-label="Zoom out" onClick={() => onViewport({ ...viewport, scale: Math.max(.55, scale - .15) })}>−</button>
    <span>{Math.round(scale * 100)}%</span>
    <button aria-label="Zoom in" onClick={() => onViewport({ ...viewport, scale: Math.min(1.6, scale + .15) })}>＋</button>
    </div>
    </div>
    <div className={`canvas-properties${selectedElement ? ' has-selection' : ''}`}>{selectedElement && selectedElement.type !== 'arrow' && <>
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
    </>}
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
    </div>{item.type === 'container' && <small>GROUP</small>}<textarea value={item.text ?? ''} aria-label="Block text" onFocus={() => setSelected(item.id)} onChange={event => onText(item.id, event.target.value)} onBlur={onFinishText} onPointerDown={event => event.stopPropagation()} />
    <button className="canvas-resize-handle" aria-label="Resize block" title="Resize block: drag or use arrow keys" onFocus={() => setSelected(item.id)} onClick={event => event.stopPropagation()} onPointerDown={event => { event.stopPropagation(); down(event, item, true) }} onKeyDown={event => { if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return; event.preventDefault(); const size = canvasSize(item), step = event.shiftKey ? 10 : 1; onCommit(resizeCanvasNode(elements, item.id, size.width + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0), size.height + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0))) }}>↘</button>
    </div> })}</div>
    </div>
    </div>
}
