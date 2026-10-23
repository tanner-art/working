import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { isValidElement, type ReactElement, type PointerEvent } from 'react'
import { Canvas } from './Canvas'
import type { CanvasViewport } from './domain'
import { canvasSize } from './canvasGeometry'

const hooks = vi.hoisted(() => ({ stateIndex: 0, tool: 'select' }))
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>()
  return { ...actual,
    // Invoke the real component handlers without rendering between samples. This
    // deliberately exercises event batching / stale render closures, not a DOM.
    useEffect: () => undefined,
    useMemo: (calculate: () => unknown) => calculate(),
    useRef: (current: unknown) => ({ current }),
    useState: (initial: unknown) => {
      const index = hooks.stateIndex++
      let value = index === 4 ? hooks.tool : typeof initial === 'function' ? initial() : initial
      return [value, (next: unknown) => { value = typeof next === 'function' ? next(value) : next }]
    },
  }
})
type Element = ReactElement<Record<string, unknown>>
function find(tree: unknown, matches: (element: Element) => boolean): Element | undefined {
  if (Array.isArray(tree)) return tree.map(child => find(child, matches)).find(Boolean)
  if (!isValidElement<Record<string, unknown>>(tree)) return undefined
  return matches(tree) ? tree : find(tree.props.children, matches)
}
const event = (pointerId: number, x: number, y = 30) => ({
  pointerId, clientX: x, clientY: y, button: 0, pointerType: 'touch',
  preventDefault: vi.fn(), stopPropagation: vi.fn(), currentTarget: { setPointerCapture: vi.fn() },
}) as unknown as PointerEvent
function setup() {
  const viewport = vi.fn<(value: CanvasViewport) => void>(), commit = vi.fn(), text = vi.fn()
  const noop = () => undefined
  const tree = Canvas({ title: 'Synthetic', autoFocusTitle: false,
    elements: [{ id: 'block', type: 'text', x: 10, y: 20, text: 'Untouched' }],
    viewport: { x: 0, y: 0, scale: 1 }, onTitle: noop, onViewport: viewport,
    onCommit: commit, onText: text, onFinishText: noop, canUndo: false, canRedo: false,
    onUndo: noop, onRedo: noop, onCaptureObject: noop, onExit: noop, saveStatus: 'Saved' })
  const surface = find(tree, element => element.props.className === 'canvas')!
  const textarea = find(tree, element => element.type === 'textarea')!
  const send = (name: string, sample: PointerEvent, target = surface) => (target.props[name] as (event: PointerEvent) => void)(sample)
  return { viewport, commit, text, send, textarea, tree }
}
beforeEach(() => {
  hooks.stateIndex = 0; hooks.tool = 'select'
  vi.stubGlobal('window', { setTimeout: vi.fn(() => 1), clearTimeout: vi.fn(), requestAnimationFrame: vi.fn(() => 1), cancelAnimationFrame: vi.fn() })
})
afterEach(() => vi.unstubAllGlobals())

describe('Canvas pointer routing (synthetic component handlers)', () => {
  it('creates a content-sized node through the actual Text toolbar action', () => {
    const { tree, commit } = setup()
    const addText = find(tree, element => element.type === 'button' && element.props.children === '+ Text')!
    ;(addText.props.onClick as () => void)()
    const node = commit.mock.calls[0][0].at(-1)
    expect(node.autoSize).toBe(true)
    expect(canvasSize({ ...node, text: 'Dad' })).toEqual({ width: 58, height: 42 })
    expect(canvasSize({ ...node, text: 'Repair Foreman' }).width).toBeGreaterThan(56)
  })
  it('keeps ordinary text editing native but accepts a second finger over text', () => {
    const { send, textarea, viewport, commit, text } = setup()
    const ordinary = event(10, 20)
    send('onPointerDown', ordinary, textarea)
    expect(ordinary.preventDefault).not.toHaveBeenCalled()
    expect(ordinary.currentTarget.setPointerCapture).not.toHaveBeenCalled()
    send('onPointerUp', ordinary)
    send('onPointerDown', event(1, 20))
    const second = event(2, 100)
    send('onPointerDown', second, textarea)
    expect(second.preventDefault).toHaveBeenCalledOnce()
    send('onPointerMove', event(2, 140))
    send('onPointerUp', event(2, 140))
    const zoomed = viewport.mock.calls.at(-1)![0]
    expect(zoomed.scale).toBe(1.5)
    send('onLostPointerCapture', event(2, 140))
    send('onPointerMove', event(1, 50))
    send('onPointerUp', event(1, 50))
    expect(viewport.mock.calls.at(-1)![0]).toEqual({ ...zoomed, x: zoomed.x + 30 })
    expect(commit).not.toHaveBeenCalled()
    expect(text).not.toHaveBeenCalled()
  })

  it('pinches when both fingers start over text without editing or moving the block', () => {
    const { send, textarea, viewport, commit, text } = setup()
    const first = event(1, 20)
    send('onPointerDown', first, textarea)
    expect(first.preventDefault).not.toHaveBeenCalled()
    send('onPointerDown', event(2, 100), textarea)
    send('onPointerMove', event(2, 260))
    send('onPointerUp', event(2, 260)); send('onPointerUp', event(1, 20))
    expect(viewport.mock.calls.at(-1)![0].scale).toBe(3)
    expect(commit).not.toHaveBeenCalled()
    expect(text).not.toHaveBeenCalled()
  })

  it('carries the synchronous zoom and pan into a second pinch before any render', () => {
    const { send, viewport } = setup()
    send('onPointerDown', event(1, 20)); send('onPointerDown', event(2, 100))
    send('onPointerMove', event(2, 140)); send('onPointerUp', event(2, 140))
    const firstZoom = viewport.mock.calls.at(-1)![0]
    send('onPointerMove', event(1, 50))
    send('onPointerDown', event(3, 170))
    send('onPointerMove', event(3, 170))
    send('onPointerUp', event(3, 170))
    expect(viewport.mock.calls.at(-1)![0]).toEqual({ ...firstZoom, x: firstZoom.x + 30 })
  })

  it('cancels active capture loss without committing a partial pinch or stale release', () => {
    const { send, viewport } = setup()
    send('onPointerDown', event(1, 20)); send('onPointerDown', event(2, 100))
    send('onPointerMove', event(2, 140)); send('onLostPointerCapture', event(1, 20))
    send('onPointerUp', event(2, 140)); send('onPointerUp', event(1, 20))
    expect(viewport).not.toHaveBeenCalled()
  })

  it.each(['pen', 'lasso'])('keeps %s from starting a stroke when a carried finger rejoins pinch', tool => {
    hooks.tool = tool
    const { send, textarea, viewport, commit } = setup()
    send('onPointerDown', event(1, 20)); send('onPointerMove', event(1, 40))
    const second = event(2, 100)
    send('onPointerDown', second, textarea)
    expect(second.preventDefault).toHaveBeenCalledOnce()
    send('onPointerMove', event(2, 100)); send('onPointerUp', event(2, 100))
    expect(viewport.mock.calls.at(-1)![0].scale).toBe(1)
    send('onLostPointerCapture', event(2, 100))
    send('onPointerDown', event(3, 100)); send('onPointerMove', event(3, 130))
    send('onPointerUp', event(3, 130)); send('onPointerUp', event(1, 40))
    expect(viewport.mock.calls.at(-1)![0].scale).toBe(1.5)
    expect(commit).not.toHaveBeenCalled()
  })
})
