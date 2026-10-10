import { describe, expect, it } from 'vitest'
import { CANVAS_RESIZE_TARGET_SIZE, beginPinchInteraction, clearPinchInteraction, commitPinchInteraction, createPinchInteraction, previewPinchInteraction, reduceResizePointerDown, viewportAtPinchStart } from './canvasInteraction'
import { idleGestureState, reduceCanvasGesture } from './canvasGestures'
import { moveCanvasNode } from './canvasGroups'
import { commitCanvas, emptyCanvasHistory } from './canvasHistory'
import { panCanvasViewport, zoomCanvasViewport } from './canvasViewport'

const first = { pointerId: 1, x: 20, y: 30 }
const second = { pointerId: 2, x: 100, y: 30 }

describe('canvas interaction bridge', () => {
  it('continues an uncommitted one-finger pan into pinch without a jump or double-applied delta', () => {
    const committed = { x: 10, y: -5, scale: 1.25 }
    const origin = { x: 80, y: 120 }
    const movedFirst = { ...first, x: first.x + 35, y: first.y - 20 }
    let gesture = reduceCanvasGesture(idleGestureState(), { type: 'pointer-down', sample: first, target: { kind: 'canvas' } }).state
    gesture = reduceCanvasGesture(gesture, { type: 'pointer-move', sample: { ...first, x: first.x + 20 } }).state
    const pan = reduceCanvasGesture(gesture, { type: 'pointer-move', sample: movedFirst })
    expect(pan.effects).toEqual([{ type: 'preview-pan', delta: { x: 35, y: -20 } }])

    const secondDown = reduceCanvasGesture(pan.state, { type: 'pointer-down', sample: second, target: { kind: 'canvas' } })
    expect(secondDown.effects.map(effect => effect.type)).toEqual(['cancel', 'begin-pinch'])
    const visiblePan = { x: committed.x + 35, y: committed.y - 20 }
    const start = viewportAtPinchStart(committed, visiblePan, null)
    const interaction = createPinchInteraction()
    beginPinchInteraction(interaction, start, movedFirst, second, origin, true)
    expect(interaction.preview).toEqual({ x: 45, y: -25, scale: 1.25 })
    // First pinch sample has not moved: the visible transform must remain exact.
    expect(previewPinchInteraction(interaction, movedFirst, second, origin)).toEqual(start)
    expect(commitPinchInteraction(interaction)).toEqual(start)
  })

  it('discards the carried pan if pinch is canceled instead of released', () => {
    const interaction = createPinchInteraction()
    const committed = { x: 10, y: -5, scale: 1 }
    const start = viewportAtPinchStart(committed, { x: 45, y: -25 }, null)
    beginPinchInteraction(interaction, start, first, second, { x: 0, y: 0 }, true)
    clearPinchInteraction(interaction)
    expect(commitPinchInteraction(interaction)).toBeNull()
    expect(committed).toEqual({ x: 10, y: -5, scale: 1 })
  })

  it('does not carry a node resize or stale pan into a fresh pinch', () => {
    const committed = { x: 10, y: -5, scale: 1 }
    const resize = reduceResizePointerDown(idleGestureState(), first, 'thought', true)
    const secondDown = reduceCanvasGesture(resize.state, { type: 'pointer-down', sample: second, target: { kind: 'canvas' } })
    expect(secondDown.effects.map(effect => effect.type)).toEqual(['cancel', 'begin-pinch'])
    expect(viewportAtPinchStart(committed, null, null)).toBe(committed)
  })

  it('commits the latest pinch preview synchronously without waiting for a render', () => {
    const interaction = createPinchInteraction()
    beginPinchInteraction(interaction, { x: 10, y: -5, scale: 1 }, first, second, { x: 0, y: 0 })

    const renderedPreview = previewPinchInteraction(interaction, first, { ...second, x: 180, y: 50 }, { x: 0, y: 0 })
    const latestPreview = previewPinchInteraction(interaction, first, { ...second, x: 220, y: 70 }, { x: 0, y: 0 })

    expect(latestPreview).not.toEqual(renderedPreview)
    expect(commitPinchInteraction(interaction)).toEqual(latestPreview)
    expect(interaction).toEqual({ start: null, preview: null })
  })

  it('keeps the world point under fingers stable when the canvas is offset by its toolbar', () => {
    const interaction = createPinchInteraction()
    const viewport = { x: 12, y: -8, scale: 1 }
    const origin = { x: 100, y: 200 }
    const firstFinger = { pointerId: 1, x: 220, y: 330 }
    const secondFinger = { pointerId: 2, x: 320, y: 330 }
    beginPinchInteraction(interaction, viewport, firstFinger, secondFinger, origin)

    const preview = previewPinchInteraction(interaction,
      { ...firstFinger, x: 195, y: 340 }, { ...secondFinger, x: 365, y: 340 }, origin)!
    const originalLocalMidpoint = { x: 170, y: 130 }
    const world = { x: (originalLocalMidpoint.x - viewport.x) / viewport.scale, y: (originalLocalMidpoint.y - viewport.y) / viewport.scale }

    expect(preview.scale).toBeCloseTo(1.6)
    expect(preview.x + world.x * preview.scale).toBeCloseTo(180)
    expect(preview.y + world.y * preview.scale).toBeCloseTo(140)
    expect(commitPinchInteraction(interaction)).toEqual(preview)
  })

  it('starts resize from visible edit mode even when it was not opened by hold', () => {
    const result = reduceResizePointerDown(idleGestureState(), first, 'thought', true)

    expect(result.state).toMatchObject({ mode: 'resizing', target: { kind: 'resize', id: 'thought' }, menuOpened: true })
    expect(result.effects).toEqual([{ type: 'begin-resize', id: 'thought', start: first }])
  })

  it('defines a 44 by 44 CSS-pixel resize target', () => {
    expect(CANVAS_RESIZE_TARGET_SIZE).toBe(44)
  })

  it('records one completed drag as one session undo step', () => {
    const original = [{ id: 'thought', type: 'text' as const, x: 10, y: 20, text: 'Move me' }]
    let gesture = reduceCanvasGesture(idleGestureState(), { type: 'pointer-down', sample: first, target: { kind: 'node', id: 'thought' } }).state
    gesture = reduceCanvasGesture(gesture, { type: 'pointer-move', sample: { ...first, x: 32 } }).state
    const completed = reduceCanvasGesture(gesture, { type: 'pointer-up', pointerId: first.pointerId })
    const move = completed.effects.find(effect => effect.type === 'commit-move')

    expect(move).toEqual({ type: 'commit-move', id: 'thought', delta: { x: 12, y: 0 } })
    const next = move && move.type === 'commit-move' ? moveCanvasNode(original, move.id, original[0].x + move.delta.x, original[0].y + move.delta.y) : original
    const history = commitCanvas(emptyCanvasHistory(original), next)
    expect(history.past).toEqual([original])
    expect(history.present).toEqual([{ ...original[0], x: 22 }])
  })

  it('keeps content coordinates intact while pan and pinch update only the viewport', () => {
    const elements = [{ id: 'thought', type: 'text' as const, x: 120, y: 240, text: 'Stable' }]
    const viewport = { x: 10, y: -5, scale: 1 }
    const panned = panCanvasViewport(viewport, { x: 35, y: -20 })
    const zoomed = zoomCanvasViewport(panned, { x: 100, y: 80 }, 1.4)

    expect(panned).toEqual({ x: 45, y: -25, scale: 1 })
    expect(zoomed).toEqual({ x: 23, y: -67, scale: 1.4 })
    expect(elements).toEqual([{ id: 'thought', type: 'text', x: 120, y: 240, text: 'Stable' }])
  })

  it('cancels a pinch without exposing a stale commit effect', () => {
    let gesture = reduceCanvasGesture(idleGestureState(), { type: 'pointer-down', sample: first, target: { kind: 'canvas' } }).state
    gesture = reduceCanvasGesture(gesture, { type: 'pointer-down', sample: second, target: { kind: 'canvas' } }).state
    const cancelled = reduceCanvasGesture(gesture, { type: 'pointer-cancel', pointerId: second.pointerId })

    expect(cancelled.state).toEqual(idleGestureState())
    expect(cancelled.effects).toEqual([{ type: 'cancel' }])
  })
})
