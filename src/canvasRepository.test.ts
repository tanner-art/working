import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, CanvasElement } from './domain'
import { addCanvas, bankFromLegacy, createCanvasRecord, LEGACY_CANVAS_ID, renameCanvas } from './canvasBank'
import { createCanvasRepository } from './canvasRepository'
import { createCanvasSession } from './canvasSession'
import { DEFAULT_CANVAS_VIEWPORT } from './canvasDocument'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { loadStateResult, makeObject, saveState, serializeState } from './store'
import { moveCanvasNode } from './canvasGroups'
import { createCanvasStrokeSmoothingRefinement } from './canvasStrokes'

const elements: CanvasElement[] = [
  { id: 'group', type: 'container', x: 0, y: 0, text: 'Original group' },
  { id: 'note', type: 'text', x: 25, y: 40, text: 'Original thought', groupId: 'group' },
  { id: 'shape', type: 'text', shape: 'diamond', x: 300, y: 150, text: 'Shape' },
  { id: 'edge', type: 'arrow', x: 0, y: 0, fromId: 'note', toId: 'shape', connectionPath: 'curved' },
]

function storage(initial: unknown) {
  let raw = typeof initial === 'string' ? initial : JSON.stringify(initial)
  let failing = false
  const setItem = vi.fn((_key: string, value: string) => { if (failing) throw Error('Quota'); raw = value })
  vi.stubGlobal('localStorage', { getItem: () => raw, setItem })
  return { get raw() { return raw }, set raw(value: string) { raw = value }, setItem, fail(value: boolean) { failing = value } }
}
function open(canvasId = LEGACY_CANVAS_ID) {
  const result = loadStateResult()
  let state = result.state
  let error = result.error
  const repository = createCanvasRepository(canvasId, () => state, change => {
    if (result.error) throw Error('Load failed; editing paused')
    state = change(state)
    error = saveState(state)
  })
  return { repository, session: createCanvasSession(repository), get state() { return state }, get error() { return error } }
}

afterEach(() => vi.unstubAllGlobals())

describe('Canvas Bank repository and editing lifecycle', () => {
  it.each(['v1', 'v2'])('projects a lossless %s migration without writing during read', version => {
    const old = { objects: [], canvas: elements }
    const data = version === 'v1' ? old : migrateLegacyState(old)
    const disk = storage(data)
    const original = disk.raw
    const loaded = loadStateResult()
    expect(loaded.error).toBeUndefined()
    expect(loaded.state.canvasBank).toEqual(bankFromLegacy(elements))
    expect(loaded.state.canvas).toEqual(elements)
    expect(disk.raw).toBe(original)
    expect(disk.setItem).not.toHaveBeenCalled()
  })

  it('writes only the selected document and leaves semantic data plus the legacy mirror byte-identical', () => {
    const thought = makeObject({ kind: 'idea', originalContent: 'Immutable expression', source: 'text', confidence: .9, interpretation: { summary: 'Idea', suggestedKind: 'idea', rationale: 'Explicit idea' } })
    storage({ objects: [thought], canvas: elements })
    let state = loadStateResult().state
    const second = createCanvasRecord('2026-09-22T00:00:00.000Z', 'canvas:second')
    state = addCanvas(state, second)
    expect(saveState(state)).toBeUndefined()
    const frozenMirror = structuredClone(state.canvas)
    const semantic = structuredClone(serializeState(state).captures)
    const repo = createCanvasRepository(LEGACY_CANVAS_ID, () => state, change => { state = change(state) })
    repo.write({ elements: moveCanvasNode(repo.read().elements, 'group', 44, 55), viewport: { x: -20, y: 30, scale: 1.3 } })
    expect(state.canvasBank?.canvases.find(item => item.id === LEGACY_CANVAS_ID)?.elements[0]).toMatchObject({ x: 44, y: 55 })
    expect(state.canvasBank?.canvases.find(item => item.id === 'canvas:second')).toEqual(second)
    expect(state.canvas).toEqual(frozenMirror)
    expect(serializeState(state).canvas).toEqual(frozenMirror)
    expect(serializeState(state).captures).toEqual(semantic)
  })

  it('autosaves text and viewport, keeps per-canvas undo, and reloads the current document', () => {
    storage({ objects: [], canvas: elements })
    const workspace = open()
    workspace.session.editText('note', 'A')
    workspace.session.editText('note', 'Autosaved')
    workspace.session.finishText()
    workspace.session.setViewport({ x: 850, y: -420, scale: 1.6 })
    expect(open().repository.read()).toMatchObject({ viewport: { x: 850, y: -420, scale: 1.6 } })
    expect(open().repository.read().elements[1].text).toBe('Autosaved')
    workspace.session.undo()
    expect(workspace.repository.read().elements).toEqual(elements)
    workspace.session.redo()
    expect(workspace.repository.read().elements[1].text).toBe('Autosaved')
    expect(open().session.canUndo).toBe(false)
  })

  it('persists one completed raw pen stroke as one undoable canvas edit', () => {
    storage({ objects: [], canvas: elements })
    const workspace = open()
    const stroke: CanvasElement = { id: 'stroke', type: 'freehand', x: -12, y: 44, rawPoints: [{ x: -12, y: 44 }, { x: -4, y: 50 }, { x: 9, y: 47 }] }
    workspace.session.commit([...workspace.repository.read().elements, stroke])
    expect(open().repository.read().elements.at(-1)).toEqual(stroke)
    workspace.session.undo()
    expect(workspace.repository.read().elements).toEqual(elements)
    workspace.session.redo()
    expect(workspace.repository.read().elements.at(-1)).toEqual(stroke)
  })

  it('persists accepted smoothing as one reversible projection edit without dropping raw points', () => {
    storage({ objects: [], canvas: elements })
    const workspace = open()
    const stroke: CanvasElement = { id: 'stroke', type: 'freehand', x: -12, y: 44, rawPoints: [{ x: -12, y: 44 }, { x: -4, y: 59 }, { x: 9, y: 47 }] }
    workspace.session.commit([...workspace.repository.read().elements, stroke])
    const refinement = createCanvasStrokeSmoothingRefinement(stroke.id, stroke.rawPoints, '2026-09-22T12:00:00.000Z')!
    const smoothed = workspace.repository.read().elements.map(item => item.id === stroke.id ? { ...item, projection: refinement.result, refinements: [refinement] } : item)
    workspace.session.commit(smoothed)

    const savedStroke = open().repository.read().elements.find(item => item.id === stroke.id)!
    expect(savedStroke).toMatchObject({ rawPoints: stroke.rawPoints, projection: refinement.result, refinements: [refinement] })
    workspace.session.undo()
    expect(workspace.repository.read().elements.find(item => item.id === stroke.id)).toEqual(stroke)
    workspace.session.redo()
    expect(workspace.repository.read().elements.find(item => item.id === stroke.id)).toEqual(savedStroke)
  })

  it('creates and renames permanent canvases with validated titles', () => {
    const initial: AppState = { objects: [], canvas: [], canvasBank: { canvases: [] } }
    const record = createCanvasRecord('2026-09-22T01:00:00.000Z', 'canvas:new')
    const created = addCanvas(initial, record)
    const named = renameCanvas(created, record.id, '  Product map  ', '2026-09-22T02:00:00.000Z')
    expect(named.canvasBank?.canvases[0]).toMatchObject({ id: 'canvas:new', title: 'Product map', elements: [], viewport: DEFAULT_CANVAS_VIEWPORT })
    expect(() => renameCanvas(named, record.id, '   ')).toThrow('1–120')
    expect(() => addCanvas(named, record)).toThrow('safely')
  })

  it('preserves the last good snapshot on quota failure and supports retry without touching the mirror', () => {
    const disk = storage({ objects: [], canvas: elements })
    const workspace = open()
    workspace.session.setViewport({ x: 10, y: 20, scale: 1 })
    const good = disk.raw
    disk.fail(true)
    workspace.session.editText('note', 'Keep unsaved thought')
    expect(workspace.error).toContain('only in this open tab')
    expect(disk.raw).toBe(good)
    expect(serializeState(workspace.state).canvasBank?.canvases[0].elements[1].text).toBe('Keep unsaved thought')
    expect(serializeState(workspace.state).canvas).toEqual(elements)
    disk.fail(false)
    expect(saveState(workspace.state)).toBeUndefined()
    expect(open().repository.read()).toEqual(workspace.repository.read())
  })

  it('rejects invalid writes, missing canvases and removal of an existing Bank document', () => {
    storage({ objects: [], canvas: elements })
    const workspace = open()
    expect(() => workspace.repository.write({ ...workspace.repository.read(), viewport: { x: Infinity, y: 0, scale: 1 } })).toThrow('Invalid canvas')
    expect(() => createCanvasRepository('missing', () => workspace.state, () => {}).read()).toThrow('no longer exists')
    const removed = { ...workspace.state, canvasBank: { canvases: [] } }
    expect(() => serializeState(removed)).toThrow('invalid or ambiguous')
  })

  it('keeps an empty cleared workspace empty rather than restoring a seed canvas', () => {
    const state: AppState = { objects: [], canvas: [], canvasBank: { canvases: [] } }
    const model = serializeState(state)
    expect(model.canvasBank).toEqual({ canvases: [] })
    expect(legacyUiProjection(model).canvasBank).toEqual({ canvases: [] })
  })
})
