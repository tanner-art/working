import { useEffect, useRef, useState } from 'react'
import type { CanvasCurveHandle, CanvasElement, CanvasViewport } from './domain'
import { newCanvasElement, toggleCanvasNodeVariant } from './canvasDocument'
import { branchCanvasChild } from './canvasBranch'
import { CANVAS_SIZE, canvasShapeLabels, canvasNodeShape, canvasSize, canvasConnectorPath, connectionAppearance, connectionEndpoints, didMoveCanvasConnectionHandle, normalizeCurveHandle, perimeterAnchorAtPoint, resizeCanvasNode, convertCanvasNode, updateCanvasConnection, updateCanvasConnectionAnchors, type CanvasShape, type ConnectionPath, type ConnectionPattern, type ConnectionWeight } from './canvasGeometry'
import { attachBlocksInside, canvasGroups, moveCanvasNode, removeCanvasNode, setCanvasGroup } from './canvasGroups'
import { fitCanvasViewport, zoomCanvasViewport, type CanvasPoint } from './canvasViewport'
import { idleGestureState, reduceCanvasGesture, type GestureEffect, type GestureState, type PointerSample } from './canvasGestures'
import { applyCanvasStrokeSmoothing, canvasStrokeIntersectsLasso, normalizeCanvasLassoPoints, normalizeCanvasStrokePoints, projectCanvasStroke } from './canvasStrokes'

export function Canvas({ title, autoFocusTitle, elements, viewport, onTitle, onViewport, onCommit, onText, onFinishText, canUndo, canRedo, onUndo, onRedo, onCaptureObject, onExit, saveStatus }: {
  title: string; autoFocusTitle: boolean; onTitle: (title: string) => void
  elements: CanvasElement[]; viewport: CanvasViewport; onViewport: (viewport: CanvasViewport) => void
  onCommit: (elements: CanvasElement[]) => void; onText: (id: string, text: string) => void; onFinishText: () => void
  canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void
  onCaptureObject: (element: CanvasElement) => void; onExit: () => void; saveStatus: string
}) {
  const [titleDraft, setTitleDraft] = useState(title)
  const titleInput = useRef<HTMLInputElement>(null)
  const cancelTitle = useRef(false)
  const saveTitle = useRef(onTitle)
  saveTitle.current = onTitle
  useEffect(() => setTitleDraft(title), [title])
  useEffect(() => { if (autoFocusTitle) { titleInput.current?.focus(); titleInput.current?.select() } }, [autoFocusTitle])
  useEffect(() => {
    const clean = titleDraft.trim()
    if (!clean || clean === title) return
    const timer = window.setTimeout(() => saveTitle.current(clean), 700)
    return () => window.clearTimeout(timer)
  }, [titleDraft, title])
  const commitTitle = () => {
    if (cancelTitle.current) { cancelTitle.current = false; setTitleDraft(title); return }
    const clean = titleDraft.trim()
    if (!clean) { setTitleDraft(title); return }
    if (clean !== title) onTitle(clean)
  }
  const [panPreview, setPanPreview] = useState<{ x: number; y: number } | null>(null)
  const [pinchPreview, setPinchPreview] = useState<CanvasViewport | null>(null)
  const pan = pinchPreview ?? (panPreview ? { ...viewport, ...panPreview } : viewport), scale = pan.scale
  const canvasRef = useRef<HTMLDivElement>(null)
  const [editMode, setEditMode] = useState(false)
  const [tool, setTool] = useState<'select' | 'pen' | 'lasso'>('select')
  const gesture = useRef<GestureState>(idleGestureState())
  const holdTimer = useRef<number | null>(null)
  const pinchStart = useRef<{ viewport: CanvasViewport; midpoint: CanvasPoint; distance: number } | null>(null)
  const [selected, setSelected] = useState<string | null>(null); const [connectFrom, setConnectFrom] = useState<string | null>(null)
  // Undo/redo (and delete) can remove the currently selected or connect-from node out
  // from under this component without it ever unmounting. Clear any reference to an id
  // that no longer exists so a stale connect-from can never produce a dangling arrow.
  useEffect(() => {
    const ids = new Set(elements.map(item => item.id))
    setSelected(current => (current && !ids.has(current)) ? null : current)
    setConnectFrom(current => (current && !ids.has(current)) ? null : current)
    setSelectedStrokeIds(current => {
      const next = new Set([...current].filter(id => elements.some(item => item.id === id && item.type === 'freehand')))
      return next.size === current.size ? current : next
    })
    setRefinementCandidateId(current => current && elements.some(item => item.id === current && item.type === 'freehand' && item.projection === undefined) ? current : null)
  }, [elements])
  // Pointer previews are transient; only completed gestures become edits.
  const [resizePreview, setResizePreview] = useState<CanvasElement | null>(null)
  const [dragOffset, setDragOffset] = useState<{ id: string; dx: number; dy: number } | null>(null)
  const [connectionPreview, setConnectionPreview] = useState<{ id: string; patch: Pick<CanvasElement, 'sourceAnchor' | 'targetAnchor' | 'curveHandle'> } | null>(null)
  const connectionDrag = useRef<{ pointerId: number; id: string; kind: 'source' | 'target' | 'curve'; start: { x: number; y: number } } | null>(null)
  const penStroke = useRef<{ pointerId: number; sample: PointerSample; points: NonNullable<CanvasElement['rawPoints']> } | null>(null)
  const [penPreview, setPenPreview] = useState<NonNullable<CanvasElement['rawPoints']> | null>(null)
  const lassoPath = useRef<{ pointerId: number; sample: PointerSample; points: NonNullable<CanvasElement['rawPoints']> } | null>(null)
  const [lassoPreview, setLassoPreview] = useState<NonNullable<CanvasElement['rawPoints']> | null>(null)
  const [selectedStrokeIds, setSelectedStrokeIds] = useState<Set<string>>(() => new Set())
  const [refinementCandidateId, setRefinementCandidateId] = useState<string | null>(null)
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
  const midpoint = (a: PointerSample, b: PointerSample) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
  const distance = (a: PointerSample, b: PointerSample) => Math.max(1, Math.hypot(a.x - b.x, a.y - b.y))
  const clearHold = () => { if (holdTimer.current !== null) { window.clearTimeout(holdTimer.current); holdTimer.current = null } }
  const dismissRefinementPreview = () => setRefinementCandidateId(null)
  const clearInteraction = () => { clearHold(); dismissRefinementPreview(); drag.current = null; connectionDrag.current = null; penStroke.current = null; lassoPath.current = null; pinchStart.current = null; setPanPreview(null); setPinchPreview(null); setDragOffset(null); setResizePreview(null); setConnectionPreview(null); setPenPreview(null); setLassoPreview(null); gesture.current = idleGestureState() }
  useEffect(() => () => clearInteraction(), [])
  const applyGestureEffect = (effect: GestureEffect) => {
    if (effect.type === 'select') { setSelected(effect.id); setEditMode(false); return }
    if (effect.type === 'open-edit-menu') { setSelected(effect.id); setEditMode(true); return }
    if (effect.type === 'begin-move') {
      const item = elements.find(value => value.id === effect.id)
      if (item) drag.current = { pointerId: effect.start.pointerId, id: effect.id, startX: effect.start.x, startY: effect.start.y, originalX: item.x, originalY: item.y, dx: 0, dy: 0, moved: true }
      return
    }
    if (effect.type === 'preview-move') { if (drag.current) { const dx = effect.delta.x / scale, dy = effect.delta.y / scale; drag.current.dx = dx; drag.current.dy = dy; setDragOffset({ id: effect.id, dx, dy }) }; return }
    if (effect.type === 'commit-move') { const item = elements.find(value => value.id === effect.id); if (item) onCommit(moveCanvasNode(elements, effect.id, item.x + effect.delta.x / scale, item.y + effect.delta.y / scale)); drag.current = null; setDragOffset(null); return }
    if (effect.type === 'begin-pan') { drag.current = { pointerId: effect.start.pointerId, startX: effect.start.x, startY: effect.start.y, originalPan: pan, dx: 0, dy: 0, moved: true }; return }
    if (effect.type === 'preview-pan') { if (drag.current) { drag.current.dx = effect.delta.x; drag.current.dy = effect.delta.y; setPanPreview({ x: drag.current.originalPan!.x + effect.delta.x, y: drag.current.originalPan!.y + effect.delta.y }) }; return }
    if (effect.type === 'commit-pan') { if (drag.current?.originalPan) onViewport({ x: drag.current.originalPan.x + effect.delta.x, y: drag.current.originalPan.y + effect.delta.y, scale }); drag.current = null; setPanPreview(null); return }
    if (effect.type === 'begin-resize') { const item = elements.find(value => value.id === effect.id); if (item) drag.current = { pointerId: effect.start.pointerId, resize: item, id: effect.id, startX: effect.start.x, startY: effect.start.y, dx: 0, dy: 0, moved: true }; return }
    if (effect.type === 'preview-resize') { const item = elements.find(value => value.id === effect.id); if (item) setResizePreview(resizeCanvasNode([item], item.id, canvasSize(item).width + effect.delta.x / scale, canvasSize(item).height + effect.delta.y / scale)[0]); return }
    if (effect.type === 'commit-resize') { const item = elements.find(value => value.id === effect.id); if (item) { const size = canvasSize(item); onCommit(resizeCanvasNode(elements, item.id, size.width + effect.delta.x / scale, size.height + effect.delta.y / scale)) }; drag.current = null; setResizePreview(null); return }
    if (effect.type === 'begin-pinch') { pinchStart.current = { viewport, midpoint: midpoint(effect.first, effect.second), distance: distance(effect.first, effect.second) }; return }
    if (effect.type === 'preview-pinch') { const start = pinchStart.current; if (!start) return; const currentMidpoint = midpoint(effect.first, effect.second), nextScale = start.viewport.scale * distance(effect.first, effect.second) / start.distance; const anchored = zoomCanvasViewport(start.viewport, start.midpoint, nextScale); setPinchPreview({ ...anchored, x: anchored.x + currentMidpoint.x - start.midpoint.x, y: anchored.y + currentMidpoint.y - start.midpoint.y }); return }
    if (effect.type === 'commit-pinch') { if (pinchPreview) onViewport(pinchPreview); setPinchPreview(null); pinchStart.current = null; return }
    if (effect.type === 'cancel') { clearInteraction() }
  }
  const dispatchGesture = (action: Parameters<typeof reduceCanvasGesture>[1]) => { const result = reduceCanvasGesture(gesture.current, action); gesture.current = result.state; result.effects.forEach(applyGestureEffect) }
  const worldPoint = (event: React.PointerEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    return { x: (event.clientX - (rect?.left ?? 0) - pan.x) / scale, y: (event.clientY - (rect?.top ?? 0) - pan.y) / scale }
  }
  const down = (event: React.PointerEvent, item?: CanvasElement, resize = false) => {
    if (event.button !== 0) return
    dismissRefinementPreview()
    if (tool === 'pen' || tool === 'lasso') {
      const active = penStroke.current ?? lassoPath.current
      if (active) {
        ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
        if (lassoPath.current) setSelectedStrokeIds(new Set())
        penStroke.current = null; lassoPath.current = null; setPenPreview(null); setLassoPreview(null)
        dispatchGesture({ type: 'pointer-down', sample: active.sample, target: { kind: 'canvas' } })
        dispatchGesture({ type: 'pointer-down', sample: { pointerId: event.pointerId, x: event.clientX, y: event.clientY }, target: { kind: 'canvas' } })
        return
      }
      const point = worldPoint(event)
      event.preventDefault()
      ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
      const start = { pointerId: event.pointerId, sample: { pointerId: event.pointerId, x: event.clientX, y: event.clientY }, points: [point] }
      if (tool === 'pen') { penStroke.current = start; setPenPreview([point]) } else { lassoPath.current = start; setLassoPreview([point]) }
      return
    }
    const target = resize ? { kind: 'resize' as const, id: item!.id } : item ? { kind: 'node' as const, id: item.id } : { kind: 'canvas' as const }
    if (item) setSelected(item.id)
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    dispatchGesture({ type: 'pointer-down', sample: { pointerId: event.pointerId, x: event.clientX, y: event.clientY }, target })
    clearHold()
    if (target.kind === 'node') holdTimer.current = window.setTimeout(() => dispatchGesture({ type: 'hold', pointerId: event.pointerId }), 1500)
  }
  const move = (event: React.PointerEvent) => {
    dismissRefinementPreview()
    const active = penStroke.current
    if (active?.pointerId === event.pointerId) {
      const points = [...active.points, worldPoint(event)]
      penStroke.current = { ...active, points }
      setPenPreview(points)
      return
    }
    const lasso = lassoPath.current
    if (lasso?.pointerId === event.pointerId) {
      const points = [...lasso.points, worldPoint(event)]
      lassoPath.current = { ...lasso, points }
      setLassoPreview(points)
      return
    }
    dispatchGesture({ type: 'pointer-move', sample: { pointerId: event.pointerId, x: event.clientX, y: event.clientY } })
  }
  const cancel = () => { const hadLasso = lassoPath.current !== null; dispatchGesture({ type: 'reset' }); clearInteraction(); if (hadLasso) setSelectedStrokeIds(new Set()) }
  const end = (event: React.PointerEvent) => {
    const active = penStroke.current
    if (active?.pointerId === event.pointerId) {
      const points = normalizeCanvasStrokePoints([...active.points, worldPoint(event)])
      penStroke.current = null; setPenPreview(null)
      if (points) onCommit([...elements, { id: crypto.randomUUID(), type: 'freehand', x: points[0].x, y: points[0].y, rawPoints: points }])
      return
    }
    const lasso = lassoPath.current
    if (lasso?.pointerId === event.pointerId) {
      const points = normalizeCanvasLassoPoints([...lasso.points, worldPoint(event)])
      lassoPath.current = null; setLassoPreview(null)
      setSelected(null); setEditMode(false); setConnectFrom(null)
      setSelectedStrokeIds(points ? new Set(elements.filter(item => item.type === 'freehand' && canvasStrokeIntersectsLasso(item.rawPoints, points)).map(item => item.id)) : new Set())
      return
    }
    clearHold(); dispatchGesture({ type: 'pointer-up', pointerId: event.pointerId }); if (gesture.current.mode === 'idle') { drag.current = null; setDragOffset(null); setPanPreview(null); setResizePreview(null) }
  }
  const connectionPatchAtPoint = (arrow: CanvasElement, kind: 'source' | 'target' | 'curve', point: { x: number; y: number }) => {
    const from = positioned(arrow.fromId), to = positioned(arrow.toId)
    if (!from || !to) return undefined
    if (kind === 'source') {
      const sourceAnchor = perimeterAnchorAtPoint(from, point)
      return sourceAnchor ? { sourceAnchor } : undefined
    }
    if (kind === 'target') {
      const targetAnchor = perimeterAnchorAtPoint(to, point)
      return targetAnchor ? { targetAnchor } : undefined
    }
    const endpoints = connectionEndpoints(from, to, arrow)
    const spanX = Math.max(Math.abs(endpoints.x2 - endpoints.x1), 1), spanY = Math.max(Math.abs(endpoints.y2 - endpoints.y1), 1)
    return { curveHandle: normalizeCurveHandle({ x: (point.x - (endpoints.x1 + endpoints.x2) / 2) / spanX, y: (point.y - (endpoints.y1 + endpoints.y2) / 2) / spanY }) }
  }
  const previewConnection = (arrow: CanvasElement, kind: 'source' | 'target' | 'curve', point: { x: number; y: number }) => {
    const patch = connectionPatchAtPoint(arrow, kind, point)
    if (!patch) return
    const next = updateCanvasConnectionAnchors(elements, arrow.id, patch)
    if (next !== elements) setConnectionPreview({ id: arrow.id, patch })
  }
  const beginConnectionDrag = (event: React.PointerEvent<HTMLButtonElement>, arrow: CanvasElement, kind: 'source' | 'target' | 'curve') => {
    if (event.button !== 0) return
    event.preventDefault(); event.stopPropagation()
    connectionDrag.current = { pointerId: event.pointerId, id: arrow.id, kind, start: worldPoint(event) }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const moveConnectionDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const active = connectionDrag.current
    if (!active || active.pointerId !== event.pointerId) return
    event.preventDefault(); event.stopPropagation()
    const point = worldPoint(event)
    if (!didMoveCanvasConnectionHandle(active.start, point)) return
    const arrow = elements.find(item => item.id === active.id && item.type === 'arrow')
    if (arrow) previewConnection(arrow, active.kind, point)
  }
  const finishConnectionDrag = (event: React.PointerEvent<HTMLButtonElement>, commit: boolean) => {
    const active = connectionDrag.current
    if (!active || active.pointerId !== event.pointerId) return
    event.preventDefault(); event.stopPropagation()
    const arrow = elements.find(item => item.id === active.id && item.type === 'arrow')
    const point = worldPoint(event)
    if (commit && arrow && didMoveCanvasConnectionHandle(active.start, point)) {
      const patch = connectionPatchAtPoint(arrow, active.kind, point)
      if (patch) {
        const next = updateCanvasConnectionAnchors(elements, arrow.id, patch)
        if (next !== elements) onCommit(next)
      }
    }
    connectionDrag.current = null
    setConnectionPreview(null)
  }
  const nudgeConnectionHandle = (arrow: CanvasElement, kind: 'source' | 'target' | 'curve', event: React.KeyboardEvent<HTMLButtonElement>) => {
    const delta = event.shiftKey ? .1 : .02
    const dx = event.key === 'ArrowRight' ? delta : event.key === 'ArrowLeft' ? -delta : 0
    const dy = event.key === 'ArrowDown' ? delta : event.key === 'ArrowUp' ? -delta : 0
    if (!dx && !dy) return
    event.preventDefault(); event.stopPropagation()
    const from = positioned(arrow.fromId), to = positioned(arrow.toId)
    if (!from || !to) return
    let patch: Pick<CanvasElement, 'sourceAnchor' | 'targetAnchor' | 'curveHandle'>
    if (kind === 'source') {
      const endpoints = connectionEndpoints(from, to, arrow), base = arrow.sourceAnchor ?? perimeterAnchorAtPoint(from, { x: endpoints.x1, y: endpoints.y1 })
      if (!base) return
      patch = { sourceAnchor: { x: base.x + dx, y: base.y + dy } }
    } else if (kind === 'target') {
      const endpoints = connectionEndpoints(from, to, arrow), base = arrow.targetAnchor ?? perimeterAnchorAtPoint(to, { x: endpoints.x2, y: endpoints.y2 })
      if (!base) return
      patch = { targetAnchor: { x: base.x + dx, y: base.y + dy } }
    } else {
      const base: CanvasCurveHandle = arrow.curveHandle ?? { x: 0, y: 0 }
      patch = { curveHandle: { x: base.x + dx, y: base.y + dy } }
    }
    onCommit(updateCanvasConnectionAnchors(elements, arrow.id, patch))
  }
  const clickNode = (event: React.MouseEvent, id: string) => {
    event.stopPropagation()
    if (tool !== 'select') return
    // Validate the connect-from endpoint still exists (not just non-null) so a stale
    // reference left over from an undo/redo/delete can never produce a dangling arrow.
    const connectFromValid = connectFrom !== null && elements.some(item => item.id === connectFrom)
    if (connectFromValid && connectFrom !== id) {
      onCommit([...elements, { id: crypto.randomUUID(), type: 'arrow', x: 0, y: 0, fromId: connectFrom, toId: id }])
      setConnectFrom(null)
    } else {
      if (selected !== id) setEditMode(false)
      setSelected(id)
    }
  }
  const arrows = elements.filter(item => item.type === 'arrow')
  const strokes = elements.filter(item => item.type === 'freehand')
  const strokePath = (points: NonNullable<CanvasElement['rawPoints']>) => points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ')
  const renderedStrokePoints = (stroke: CanvasElement) => projectCanvasStroke(stroke.rawPoints, stroke.projection ?? { kind: 'raw' }) ?? stroke.rawPoints!
  const smoothingPreviewPoints = (stroke: CanvasElement) => projectCanvasStroke(stroke.rawPoints, { kind: 'smoothed', algorithm: 'moving-average-v1' })
  const selectedStroke = selectedStrokeIds.size === 1 ? strokes.find(stroke => selectedStrokeIds.has(stroke.id)) : undefined
  const canPreviewSmoothing = Boolean(selectedStroke && selectedStroke.projection === undefined && smoothingPreviewPoints(selectedStroke))
  const openSmoothingPreview = () => { if (canPreviewSmoothing && selectedStroke) setRefinementCandidateId(selectedStroke.id) }
  const acceptSmoothing = () => {
    const stroke = refinementCandidateId ? elements.find(item => item.id === refinementCandidateId && item.type === 'freehand') : undefined
    if (!stroke || stroke.projection !== undefined) { dismissRefinementPreview(); return }
    const smoothed = applyCanvasStrokeSmoothing(stroke, new Date().toISOString())
    if (!smoothed) { dismissRefinementPreview(); return }
    onCommit(elements.map(item => item.id === stroke.id ? smoothed : item))
    dismissRefinementPreview()
  }
  const renderedArrow = (arrow: CanvasElement) => connectionPreview?.id === arrow.id ? { ...arrow, ...connectionPreview.patch } : arrow
  const connectionHandlePositions = (arrow: CanvasElement) => {
    const shown = renderedArrow(arrow), from = positioned(shown.fromId), to = positioned(shown.toId)
    if (!from || !to) return undefined
    const endpoints = connectionEndpoints(from, to, shown)
    const spanX = Math.max(Math.abs(endpoints.x2 - endpoints.x1), 1), spanY = Math.max(Math.abs(endpoints.y2 - endpoints.y1), 1)
    const curve = shown.curveHandle
      ? { x: (endpoints.x1 + endpoints.x2) / 2 + shown.curveHandle.x * spanX, y: (endpoints.y1 + endpoints.y2) / 2 + shown.curveHandle.y * spanY }
      : { x: (endpoints.x1 + endpoints.x2) / 2, y: (endpoints.y1 + endpoints.y2) / 2 }
    return { source: { x: endpoints.x1, y: endpoints.y1 }, target: { x: endpoints.x2, y: endpoints.y2 }, curve }
  }
  const groups = canvasGroups(elements)
  const selectedElement = selected ? positioned(selected) : undefined
  const canCaptureSelected = Boolean(selectedElement?.text?.trim() && selectedElement.type !== 'arrow')
  const showBulletedText = (item: CanvasElement) => item.nodeVariant === 'bulleted-list'
    ? (item.text ?? '').split('\n').map(line => line ? `• ${line}` : '').join('\n')
    : item.text ?? ''
  const readBulletedText = (item: CanvasElement, text: string) => item.nodeVariant === 'bulleted-list'
    ? text.split('\n').map(line => line.startsWith('• ') ? line.slice(2) : line).join('\n')
    : text
  const branchSelected = () => {
    if (!selectedElement || selectedElement.type === 'arrow') return
    const branch = branchCanvasChild(elements, selectedElement.id)
    if (!branch) return
    onCommit(branch.elements)
    setConnectFrom(null)
    setSelected(branch.childId)
    setEditMode(true)
  }
  const removeSelected = () => { if (!selected) return; onCommit(removeCanvasNode(elements, selected)); setSelected(null); setConnectFrom(null) }
  const fit = (selection = false) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const ids = selection && selectedElement && selectedElement.type !== 'arrow' ? new Set([selectedElement.id]) : undefined
    onViewport(fitCanvasViewport(elements, { width: rect.width, height: rect.height }, 32, ids))
  }
  return <div className="canvas-page">
    <div className="canvas-head">
    <div>
    <button className="canvas-exit" onClick={onExit}>← Back to Bank</button>
    <label className="sr-only" htmlFor="canvas-title">Canvas title</label>
    <input ref={titleInput} id="canvas-title" className="canvas-title-input" maxLength={120} value={titleDraft} onChange={event => { cancelTitle.current = false; setTitleDraft(event.target.value) }} onBlur={commitTitle} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { cancelTitle.current = true; setTitleDraft(title); event.currentTarget.blur() } }} />
    <p className="canvas-save-status" role="status">{saveStatus}</p>
    </div>
    <div className="canvas-tools">
    <button onClick={() => add('text')}>+ Text</button>
    <button className={tool === 'pen' ? 'selected-tool' : ''} aria-pressed={tool === 'pen'} onClick={() => { cancel(); setTool(current => current === 'pen' ? 'select' : 'pen'); setConnectFrom(null); setSelected(null); setSelectedStrokeIds(new Set()); setEditMode(false) }}>Pen</button>
    <button className={tool === 'lasso' ? 'selected-tool' : ''} aria-pressed={tool === 'lasso'} onClick={() => { cancel(); setTool(current => current === 'lasso' ? 'select' : 'lasso'); setConnectFrom(null); setSelected(null); setSelectedStrokeIds(new Set()); setEditMode(false) }}>Lasso</button>
    <button disabled={!canPreviewSmoothing} onClick={openSmoothingPreview}>Preview smoothing</button>
    <button onClick={() => add('container')}>+ Group</button>
    <label className="canvas-palette">Add shape <select aria-label="Add canvas shape" value="" onChange={event => { if (event.target.value) add(event.target.value as CanvasShape) }}>
    <option value="" disabled>Choose shape…</option>{Object.entries(canvasShapeLabels).filter(([shape]) => shape !== 'text' && shape !== 'container').map(([shape, label]) => <option key={shape} value={shape}>{label}</option>)}
    </select></label>
    <button disabled={!selectedElement || selectedElement.type === 'arrow'} onClick={branchSelected}>Branch child</button>
    <button disabled={selectedElement?.type !== 'text'} aria-pressed={selectedElement?.nodeVariant === 'bulleted-list'} onClick={() => selectedElement && onCommit(toggleCanvasNodeVariant(elements, selectedElement.id))}>{selectedElement?.nodeVariant === 'bulleted-list' ? 'Plain text' : 'Bulleted list'}</button>
    <button disabled={!selectedElement} className={connectFrom ? 'selected-tool' : ''} onClick={() => setConnectFrom(connectFrom ? null : selected)}>↗ Connect</button>
    <button disabled={!canCaptureSelected} onClick={() => selectedElement && onCaptureObject(selectedElement)}>Capture node</button>
    <button disabled={!selected} onClick={removeSelected}>Delete</button>
    <span/>
    <button disabled={!canUndo} title="Undo (Ctrl/Cmd+Z)" onClick={onUndo}>↶ Undo</button>
    <button disabled={!canRedo} title="Redo (Ctrl/Cmd+Shift+Z)" onClick={onRedo}>↷ Redo</button>
    <span/>
    <button aria-label="Fit canvas" onClick={() => fit()}>Fit</button>
    <button aria-label="Fit selection" disabled={!selectedElement || selectedElement.type === 'arrow'} onClick={() => fit(true)}>Fit selection</button>
    <button aria-label="Zoom out" onClick={() => onViewport(zoomCanvasViewport(viewport, { x: (canvasRef.current?.clientWidth ?? 0) / 2, y: (canvasRef.current?.clientHeight ?? 0) / 2 }, scale - .15))}>−</button>
    <span>{Math.round(scale * 100)}%</span>
    <button aria-label="Zoom in" onClick={() => onViewport(zoomCanvasViewport(viewport, { x: (canvasRef.current?.clientWidth ?? 0) / 2, y: (canvasRef.current?.clientHeight ?? 0) / 2 }, scale + .15))}>＋</button>
    </div>
    </div>
    <div className={`canvas-properties${selectedElement && (editMode || selectedElement.type === 'arrow') ? ' has-selection' : ''}${editMode ? ' edit-mode' : ''}`}>{selectedElement && (editMode || selectedElement.type === 'arrow') && selectedElement.type !== 'arrow' && <>
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
    <div className="canvas-note">{tool === 'pen' ? 'Pen active · draw a stroke · use two fingers to zoom' : tool === 'lasso' ? selectedStrokeIds.size === 1 ? 'One stroke selected · preview smoothing or circle another selection' : 'Lasso active · circle one stroke to preview smoothing · use two fingers to zoom' : connectFrom ? 'Select another thought to draw the connection.' : 'Use the grip to move thoughts · drag empty space to pan · edit text directly'}</div>
    <div ref={canvasRef} className="canvas" onPointerDown={event => down(event)} onPointerMove={move} onPointerUp={end} onPointerCancel={cancel} onLostPointerCapture={cancel} onKeyDown={event => { if (event.key === 'Escape') cancel() }} onClick={() => { if (tool === 'select') { setSelected(null); setSelectedStrokeIds(new Set()); setEditMode(false) } }}>
    <div className="canvas-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }}>
    <svg className="canvas-strokes" aria-hidden="true">{strokes.map(stroke => <g key={stroke.id}><path className={`canvas-stroke${selectedStrokeIds.has(stroke.id) ? ' selected' : ''}`} d={strokePath(renderedStrokePoints(stroke))} />{refinementCandidateId === stroke.id && smoothingPreviewPoints(stroke) && <path className="canvas-stroke canvas-smoothing-preview" d={strokePath(smoothingPreviewPoints(stroke)!)} />}</g>)}{penPreview && <path className="canvas-stroke canvas-stroke-preview" d={strokePath(penPreview)} />}{lassoPreview && <path className="canvas-lasso-preview" d={`${strokePath(lassoPreview)} Z`} />}</svg>
    <svg className="arrows">{arrows.map(arrow => { const shown = renderedArrow(arrow), from = positioned(shown.fromId); const to = positioned(shown.toId); if (!from || !to) return null; const d = canvasConnectorPath(from, to, shown.connectionPath, shown); return <g key={arrow.id} className={selected === arrow.id ? 'selected' : ''}><path className="canvas-arrow-visible" d={d} style={connectionAppearance(shown)} markerEnd="url(#head)"/><path className="canvas-arrow-hit" d={d} role="button" tabIndex={0} aria-label={`Connection from ${from.text || 'block'} to ${to.text || 'block'}`} onClick={event => { event.stopPropagation(); if (tool === 'select') { setEditMode(false); setSelected(arrow.id) } }} onKeyDown={event => { if (tool === 'select' && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); setEditMode(false); setSelected(arrow.id) } }}/></g> })}<defs>
    <marker id="head" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
    <path d="M0,0 L0,6 L7,3 z" />
    </marker>
    </defs>
    </svg>{elements.filter(item => item.type === 'text' || item.type === 'container').map(item => { const shown = positioned(item.id)!; return <div key={item.id} className={`canvas-node ${item.type} shape-${canvasNodeShape(item)} ${selected === item.id ? 'selected' : ''}`} style={{ left: shown.x, top: shown.y, ...canvasSize(shown) }} onClick={event => clickNode(event, item.id)}>
    {(item.shape === 'ellipse' || item.shape === 'diamond') && <svg className="canvas-shape-outline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{item.shape === 'ellipse' ? <ellipse cx="50" cy="50" rx="50" ry="50" /> : <polygon points="50,0 100,50 50,100 0,50" />}</svg>}
    <div className="canvas-drag-handle" title="Move thought" onPointerDown={event => { event.stopPropagation(); down(event, item) }}>
    <span>
    </span>
    <span>
    </span>
    <span>
    </span>
    </div>{item.type === 'container' && <small>GROUP</small>}<textarea className={item.nodeVariant === 'bulleted-list' ? 'canvas-bulleted-text' : undefined} value={showBulletedText(item)} aria-label="Block text" onFocus={() => { if (tool === 'select' && selected !== item.id) setEditMode(false); if (tool === 'select') setSelected(item.id) }} onChange={event => onText(item.id, readBulletedText(item, event.target.value))} onBlur={onFinishText} onPointerDown={event => { event.stopPropagation(); if (tool !== 'select') down(event) }} />
    {editMode && selected === item.id && <button className="canvas-resize-handle" aria-label="Resize block" title="Resize block: drag or use arrow keys" onFocus={() => setSelected(item.id)} onClick={event => event.stopPropagation()} onPointerDown={event => { event.stopPropagation(); down(event, item, true) }} onKeyDown={event => { if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return; event.preventDefault(); const size = canvasSize(item), step = event.shiftKey ? 10 : 1; onCommit(resizeCanvasNode(elements, item.id, size.width + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0), size.height + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0))) }}>↘</button>}
    </div> })}{arrows.filter(arrow => selected === arrow.id).map(arrow => {
      const positions = connectionHandlePositions(arrow)
      if (!positions) return null
      const handle = (kind: 'source' | 'target' | 'curve', point: { x: number; y: number }, label: string) => <button key={kind} type="button" className={`canvas-connection-handle ${kind}`} style={{ left: point.x, top: point.y }} aria-label={label} title={`${label}: drag or use arrow keys`} onClick={event => event.stopPropagation()} onPointerDown={event => beginConnectionDrag(event, arrow, kind)} onPointerMove={moveConnectionDrag} onPointerUp={event => finishConnectionDrag(event, true)} onPointerCancel={event => finishConnectionDrag(event, false)} onLostPointerCapture={event => finishConnectionDrag(event, false)} onKeyDown={event => nudgeConnectionHandle(arrow, kind, event)} />
      return <div key={`${arrow.id}-handles`} className="canvas-connection-handles">{handle('source', positions.source, 'Move connection source anchor')}{handle('target', positions.target, 'Move connection target anchor')}{(renderedArrow(arrow).connectionPath === 'curved') && handle('curve', positions.curve, 'Move connection curve handle')}</div>
    })}</div>
    </div>
    {refinementCandidateId && <section className="canvas-refinement-sheet" role="dialog" aria-modal="false" aria-labelledby="smoothing-preview-title">
      <button className="canvas-refinement-dismiss" aria-label="Dismiss smoothing preview" onClick={dismissRefinementPreview}>×</button>
      <p className="section-label">Local refinement preview</p><h2 id="smoothing-preview-title">Smooth this stroke?</h2>
      <p>The highlighted line is a deterministic local smoothing preview. Its original raw points stay preserved.</p>
      <div><button className="secondary" onClick={dismissRefinementPreview}>Keep original</button><button className="primary" onClick={acceptSmoothing}>Use smoothed stroke</button></div>
    </section>}
    </div>
}
