import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CanvasElement } from './domain'
import { canvasSize, canvasConnector, canvasConnectorPath, connectionAppearance, convertCanvasNode, resizeCanvasNode, updateCanvasConnection } from './canvasGeometry'
import { commitCanvas, emptyCanvasHistory, redoCanvas, undoCanvas } from './canvasHistory'
import { moveCanvasNode, setCanvasGroup } from './canvasGroups'
import { loadStateResult, saveState } from './store'

const nodes: CanvasElement[] = [
  { id: 'a', type: 'text', x: -30, y: 25, text: 'Original thought\nwith content', width: 190, height: 100 },
  { id: 'b', type: 'container', x: 500, y: 400, text: 'Group', width: 320, height: 210 },
  { id: 'link', type: 'arrow', x: 0, y: 0, fromId: 'a', toId: 'b' },
]
afterEach(() => vi.unstubAllGlobals())
describe('canvas size and conversion', () => {
  it('resizes only the target geometry without mutating original expression or connector IDs', () => {
    const before = structuredClone(nodes)
    const resized = resizeCanvasNode(nodes, 'a', 340, 230)
    expect(resized[0]).toEqual({ ...nodes[0], width: 340, height: 230 })
    expect(resized[1]).toBe(nodes[1])
    expect(resized[2]).toBe(nodes[2])
    expect(nodes).toEqual(before)
    expect(canvasConnector(resized[0], resized[1])).toEqual({ x1: 140, y1: 255, x2: 660, y2: 400 })
  })
  it('converts both supported forms while preserving text, position, dimensions and ports', () => {
    const converted = convertCanvasNode(nodes, 'a', 'container')
    expect(converted[0]).toEqual({ ...nodes[0], type: 'container' })
    expect(canvasConnector(converted[0], converted[1])).toEqual(canvasConnector(nodes[0], nodes[1]))
    expect(convertCanvasNode(converted, 'a', 'text')).toEqual(nodes)
    expect(convertCanvasNode(nodes, 'b', 'text')[1]).toEqual({ ...nodes[1], type: 'text' })
    expect(converted[2]).toBe(nodes[2])
  })
  it('keeps legacy implicit dimensions stable across conversion', () => {
    const legacy: CanvasElement = { id: 'legacy', type: 'text', x: 10, y: 30, text: 'Keep me' }
    const converted = convertCanvasNode([legacy], legacy.id, 'container')[0]
    expect(canvasSize(converted)).toEqual(canvasSize(legacy))
    expect(converted.text).toBe(legacy.text)
  })
  it('clamps both axes, rounds pixels, rejects non-finite requests and never resizes arrows', () => {
    expect(resizeCanvasNode(nodes, 'a', -5, 99999)[0]).toMatchObject({ width: 120, height: 900 })
    expect(resizeCanvasNode(nodes, 'a', 99999, -5)[0]).toMatchObject({ width: 1200, height: 100 })
    expect(resizeCanvasNode(nodes, 'a', 150.3, 160.8)[0]).toMatchObject({ width: 150, height: 161 })
    for (const value of [NaN, Infinity, -Infinity]) {
      expect(resizeCanvasNode(nodes, 'a', value, 200)).toBe(nodes)
      expect(resizeCanvasNode(nodes, 'a', 200, value)).toBe(nodes)
    }
    expect(resizeCanvasNode(nodes, 'link', 400, 400)).toEqual(nodes)
    expect(convertCanvasNode(nodes, 'link', 'text')).toEqual(nodes)
  })
  it('undoes and redoes atomic resize and conversion with exact connector restoration', () => {
    const resized = resizeCanvasNode(nodes, 'a', 400, 300)
    const converted = convertCanvasNode(resized, 'a', 'container')
    const first = commitCanvas(emptyCanvasHistory(nodes), resized)
    const second = commitCanvas(first, converted)
    expect(second.past).toHaveLength(2)
    expect(undoCanvas(second).present).toEqual(resized)
    expect(undoCanvas(undoCanvas(second)).present).toEqual(nodes)
    expect(redoCanvas(redoCanvas(undoCanvas(undoCanvas(second)))).present).toEqual(converted)
    expect(canvasConnector(undoCanvas(undoCanvas(second)).present[0], nodes[1])).toEqual(canvasConnector(nodes[0], nodes[1]))
    expect(commitCanvas(first, resizeCanvasNode(resized, 'a', 400, 300))).toBe(first)
    expect(commitCanvas(first, convertCanvasNode(resized, 'a', 'text'))).toBe(first)
    expect(commitCanvas(undoCanvas(second), resizeCanvasNode(resized, 'a', 500, 300)).future).toEqual([])
  })
  it('persists edits and undo/redo without changing capture or semantic evidence; reload starts fresh history', () => {
    let raw: string | null = null
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const initial = loadStateResult().state
    const evidence = structuredClone(initial.model!)
    let history = emptyCanvasHistory(initial.canvas)
    history = commitCanvas(history, resizeCanvasNode(initial.canvas, 'canvas-idea', 420, 240))
    history = commitCanvas(history, convertCanvasNode(history.present, 'canvas-idea', 'container'))
    for (const snapshot of [history, undoCanvas(history), redoCanvas(undoCanvas(history))]) {
      expect(saveState({ ...initial, canvas: snapshot.present })).toBeUndefined()
      const loaded = loadStateResult()
      expect(loaded.error).toBeUndefined()
      expect(loaded.state.canvas).toEqual(snapshot.present)
      expect(loaded.state.model).toEqual({ ...evidence, canvas: snapshot.present })
      expect(emptyCanvasHistory(loaded.state.canvas).past).toEqual([])
    }
  })

  it('renders straight and curved connectors from the same live endpoint geometry', () => {
    expect(canvasConnectorPath(nodes[0], nodes[1])).toBe('M 65 125 L 660 400')
    expect(canvasConnectorPath(nodes[0], nodes[1], 'curved')).toBe('M 65 125 C 65 248.75, 660 276.25, 660 400')
  })

  it('maps connection pattern and weight to visible SVG styling with legacy defaults', () => {
    expect(connectionAppearance(nodes[2])).toEqual({ strokeWidth: 2, strokeDasharray: undefined, strokeLinecap: 'butt' })
    expect(connectionAppearance({ ...nodes[2], connectionPattern: 'dotted', connectionWeight: 'bold' }))
      .toEqual({ strokeWidth: 5, strokeDasharray: '2 7', strokeLinecap: 'round' })
    expect(connectionAppearance({ ...nodes[2], connectionPattern: 'dashed', connectionWeight: 'light' }))
      .toEqual({ strokeWidth: 1, strokeDasharray: '12 8', strokeLinecap: 'butt' })
  })

  it('updates only the selected connection and participates in exact undo/redo', () => {
    const styled = updateCanvasConnection(nodes, 'link', { connectionPath: 'curved', connectionPattern: 'dashed', connectionWeight: 'bold' })
    expect(styled[0]).toBe(nodes[0])
    expect(styled[2]).toEqual({ ...nodes[2], connectionPath: 'curved', connectionPattern: 'dashed', connectionWeight: 'bold' })
    const history = commitCanvas(emptyCanvasHistory(nodes), styled)
    expect(undoCanvas(history).present).toEqual(nodes)
    expect(redoCanvas(undoCanvas(history)).present).toEqual(styled)
  })

  it('persists styled connections while preserving legacy connections unchanged', () => {
    let raw: string | null = null
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const initial = loadStateResult().state
    expect(initial.canvas.find(item => item.type === 'arrow')).not.toHaveProperty('connectionPath')
    const styled = updateCanvasConnection(initial.canvas, 'canvas-arrow', { connectionPath: 'curved', connectionPattern: 'dotted', connectionWeight: 'bold' })
    expect(saveState({ ...initial, canvas: styled })).toBeUndefined()
    const loaded = loadStateResult()
    expect(loaded.error).toBeUndefined()
    expect(loaded.state.canvas.find(item => item.id === 'canvas-arrow')).toMatchObject({ connectionPath: 'curved', connectionPattern: 'dotted', connectionWeight: 'bold' })
  })
})


describe('TASK-024 visual shape palette', () => {
  it.each(['rectangle', 'rounded-rectangle', 'ellipse', 'diamond'] as const)('preserves expression, sticky membership and history for %s', shape => {
    const grouped = setCanvasGroup(nodes, 'a', 'b')
    const converted = convertCanvasNode(grouped, 'a', shape)
    expect(converted[0]).toEqual({ ...grouped[0], shape })
    expect(converted[2]).toBe(grouped[2])
    const moved = moveCanvasNode(converted, 'b', 550, 470)
    expect(moved[0]).toMatchObject({ x: 20, y: 95, groupId: 'b', shape })
    const resized = resizeCanvasNode(moved, 'a', 400, 300)
    expect(resized[0]).toMatchObject({ shape, groupId: 'b', text: nodes[0].text })
    const history = commitCanvas(commitCanvas(emptyCanvasHistory(grouped), converted), resized)
    expect(undoCanvas(history).present).toEqual(converted)
    expect(undoCanvas(undoCanvas(history)).present).toEqual(grouped)
    expect(redoCanvas(undoCanvas(history)).present).toEqual(resized)
    expect(convertCanvasNode(converted, 'a', shape)).toBe(converted)
    expect(convertCanvasNode(converted, 'a', 'text')).toEqual(grouped)
    expect(convertCanvasNode(converted, 'a', 'container')[0]).toMatchObject({ type: 'container', shape: undefined, groupId: undefined })
    expect(convertCanvasNode(grouped, 'b', shape)[0].groupId).toBeUndefined()
  })

  it.each(['rectangle', 'rounded-rectangle', 'ellipse', 'diamond'] as const)('anchors both path styles to %s boundary extrema after resize', shape => {
    const from = { ...nodes[0], shape, width: 300, height: 200 }
    const to = { ...nodes[0], id: 'other', shape, x: -500, y: -400, width: 120, height: 100 }
    const ports = canvasConnector(from, to)
    expect(ports).toEqual({ x1: 120, y1: 225, x2: -440, y2: -400 })
    // Normalized ellipse equation and diamond equation both equal one at the ports.
    for (const [node, x, y] of [[from, ports.x1, ports.y1], [to, ports.x2, ports.y2]] as const) {
      const dx = (x - node.x - node.width / 2) / (node.width / 2)
      const dy = (y - node.y - node.height / 2) / (node.height / 2)
      expect(dx * dx + dy * dy).toBe(1)
      expect(Math.abs(dx) + Math.abs(dy)).toBe(1)
    }
    expect(canvasConnectorPath(from, to)).toBe('M 120 225 L -440 -400')
    expect(canvasConnectorPath(from, to, 'curved')).toMatch(/^M 120 225 C .* -440 -400$/)
  })
})
