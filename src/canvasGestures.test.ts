import { describe, expect, it } from 'vitest'
import { idleGestureState, reduceCanvasGesture } from './canvasGestures'

const node = (pointerId = 1, x = 20, y = 30) => ({ pointerId, x, y })
const canvas = { kind: 'canvas' as const }
const thought = { kind: 'node' as const, id: 'thought' }
const step = (state: ReturnType<typeof idleGestureState>, action: Parameters<typeof reduceCanvasGesture>[1]) => reduceCanvasGesture(state, action)

describe('canvasGestures', () => {
  it('selects on a quick node tap without moving or opening a menu', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: thought })
    result = step(result.state, { type: 'pointer-up', pointerId: 1 })
    expect(result.effects).toEqual([{ type: 'select', id: 'thought' }])
    expect(result.state.mode).toBe('idle')
  })

  it('opens the edit menu after a stationary hold', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: thought })
    result = step(result.state, { type: 'hold', pointerId: 1 })
    expect(result.effects).toEqual([{ type: 'open-edit-menu', id: 'thought' }])
    expect(result.state.mode).toBe('edit-menu')
  })

  it('turns a held node into one move and one commit after screen slop', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: thought })
    result = step(result.state, { type: 'hold', pointerId: 1 })
    result = step(result.state, { type: 'pointer-move', sample: node(1, 29, 30) })
    expect(result.state.mode).toBe('moving-node')
    expect(result.effects.some(effect => effect.type === 'begin-move')).toBe(true)
    result = step(result.state, { type: 'pointer-up', pointerId: 1 })
    expect(result.effects).toContainEqual({ type: 'commit-move', id: 'thought', delta: { x: 9, y: 0 } })
  })

  it('pans empty canvas and commits only on release', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: canvas })
    result = step(result.state, { type: 'pointer-move', sample: node(1, 29, 42) })
    expect(result.effects).toContainEqual({ type: 'begin-pan', start: node() })
    result = step(result.state, { type: 'pointer-move', sample: node(1, 35, 50) })
    expect(result.effects).toEqual([{ type: 'preview-pan', delta: { x: 15, y: 20 } }])
    result = step(result.state, { type: 'pointer-up', pointerId: 1 })
    expect(result.effects).toContainEqual({ type: 'commit-pan', delta: { x: 15, y: 20 } })
  })

  it('does not open a menu or move from textarea taps', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: { kind: 'textarea', id: 'thought' } })
    result = step(result.state, { type: 'hold', pointerId: 1 })
    expect(result.effects).toEqual([])
    result = step(result.state, { type: 'pointer-move', sample: node(1, 40, 30) })
    expect(result.effects.some(effect => effect.type === 'begin-move')).toBe(false)
  })

  it('only permits resize after explicit edit mode', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: { kind: 'resize', id: 'thought' } })
    expect(result.effects).toEqual([])
    result = step(idleGestureState(), { type: 'enter-edit-mode' })
    result = step(result.state, { type: 'pointer-down', sample: node(), target: { kind: 'resize', id: 'thought' } })
    expect(result.effects).toEqual([{ type: 'begin-resize', id: 'thought', start: node() }])
    result = step(result.state, { type: 'pointer-move', sample: node(1, 40, 40) })
    result = step(result.state, { type: 'pointer-up', pointerId: 1 })
    expect(result.effects).toContainEqual({ type: 'commit-resize', id: 'thought', delta: { x: 20, y: 10 } })
  })

  it('switches to pinch when a second pointer arrives and cancels the node gesture', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: thought })
    result = step(result.state, { type: 'pointer-down', sample: node(2, 100, 30), target: canvas })
    expect(result.state.mode).toBe('pinch-zooming')
    expect(result.effects).toContainEqual({ type: 'begin-pinch', first: node(), second: node(2, 100, 30) })
    expect(result.effects).toContainEqual({ type: 'cancel' })
    result = step(result.state, { type: 'pointer-move', sample: node(2, 110, 30) })
    expect(result.effects[0].type).toBe('preview-pinch')
    result = step(result.state, { type: 'pointer-up', pointerId: 2 })
    expect(result.effects).toEqual([{ type: 'commit-pinch' }])
    expect(result.state.mode).toBe('idle')
  })

  it('resets on cancellation so stale pointers cannot commit', () => {
    let result = step(idleGestureState(), { type: 'pointer-down', sample: node(), target: thought })
    result = step(result.state, { type: 'pointer-cancel', pointerId: 1 })
    expect(result.state).toEqual(idleGestureState())
    result = step(result.state, { type: 'pointer-up', pointerId: 1 })
    expect(result.effects).toEqual([])
  })
})
