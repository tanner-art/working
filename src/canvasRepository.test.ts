import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, CanvasElement } from './domain'
import { createCanvasRepository } from './canvasRepository'
import { createCanvasSession } from './canvasSession'
import { DEFAULT_CANVAS_VIEWPORT } from './canvasDocument'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { loadStateResult, makeObject, saveState, serializeState } from './store'
import { convertCanvasNode, resizeCanvasNode, updateCanvasConnection } from './canvasGeometry'
import { moveCanvasNode, removeCanvasNode } from './canvasGroups'

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
function open() {
  const result = loadStateResult()
  let state = result.state
  let error = result.error
  const repository = createCanvasRepository(() => state, change => {
    if (result.error) throw Error('Load failed; editing paused')
    state = change(state)
    error = saveState(state)
  })
  return { repository, session: createCanvasSession(repository), get state() { return state }, get error() { return error } }
}

afterEach(() => vi.unstubAllGlobals())

describe('single-canvas repository and editing lifecycle', () => {
  it.each(['v1', 'v2'])('migrates %s without rewriting source or changing identities, expression, or evidence', version => {
    const old = { objects: [], canvas: elements }
    const data = version === 'v1' ? old : migrateLegacyState(old)
    const disk = storage(data)
    const original = disk.raw
    const workspace = open()
    expect(workspace.error).toBeUndefined()
    expect(workspace.repository.read()).toEqual({ elements, viewport: DEFAULT_CANVAS_VIEWPORT })
    expect(disk.raw).toBe(original)
    workspace.session.setViewport({ x: -345, y: 199, scale: 1.3 })
    expect(workspace.error).toBeUndefined()
    expect(open().repository.read()).toEqual({ elements, viewport: { x: -345, y: 199, scale: 1.3 } })
    expect(serializeState(workspace.state).captures).toEqual([])
    expect(elements[1].text).toBe('Original thought')
  })

  it('roundtrips meaningful edits, viewport, undo and redo without touching semantic data', () => {
    const thought = makeObject({ kind: 'idea', originalContent: 'Immutable expression', source: 'text', confidence: .9, interpretation: { summary: 'Idea', suggestedKind: 'idea', rationale: 'Explicit idea' } })
    storage({ objects: [thought], canvas: elements })
    const workspace = open(), session = workspace.session
    const evidence = structuredClone(workspace.state.model)
    session.editText('note', 'Typing')
    session.editText('note', 'Typed without blur')
    // Reload during active text editing sees the last input, not the focus-time value.
    expect(open().state.canvas[1].text).toBe('Typed without blur')
    session.finishText()
    session.commit(moveCanvasNode(workspace.state.canvas, 'group', -200, 70))
    session.commit(resizeCanvasNode(workspace.state.canvas, 'shape', 260, 190))
    session.commit(convertCanvasNode(workspace.state.canvas, 'shape', 'ellipse'))
    session.commit(updateCanvasConnection(workspace.state.canvas, 'edge', { connectionPattern: 'dotted', connectionWeight: 'bold' }))
    session.setViewport({ x: -80, y: 140, scale: .7 })
    const complete = structuredClone(workspace.state.canvas)
    session.commit(removeCanvasNode(workspace.state.canvas, 'shape'))
    expect(open().state.canvas.some(item => item.id === 'edge')).toBe(false)
    session.undo()
    expect(open().state.canvas).toEqual(complete)
    session.redo()
    expect(open().state.canvas).toEqual(workspace.state.canvas)
    expect(open().repository.read().viewport).toEqual({ x: -80, y: 140, scale: .7 })
    expect(serializeState(workspace.state).captures).toEqual(evidence!.captures)
    expect(serializeState(workspace.state).interpretations).toEqual(evidence!.interpretations)
    expect(serializeState(workspace.state).semanticObjects).toEqual(evidence!.semanticObjects)
  })

  it('groups typing into one undo step while retaining viewport and history through view changes', () => {
    storage({ objects: [], canvas: elements })
    const workspace = open(), session = workspace.session
    session.editText('note', 'A')
    session.editText('note', 'AB')
    session.finishText() // leaving the canvas ends the edit, not the workspace session
    session.setViewport({ x: 850, y: -420, scale: 1.6 })
    expect(workspace.repository.read().viewport).toEqual({ x: 850, y: -420, scale: 1.6 })
    session.undo()
    expect(workspace.state.canvas).toEqual(elements)
    expect(session.canUndo).toBe(false)
    session.redo()
    expect(workspace.state.canvas[1].text).toBe('AB')
    session.editText('note', 'ABC')
    session.undo()
    expect(workspace.state.canvas[1].text).toBe('AB')
    expect(open().session.canUndo).toBe(false) // D-010: reload starts fresh history
    expect(open().repository.read().viewport).toEqual({ x: 850, y: -420, scale: 1.6 })
  })

  it('preserves the last good snapshot on quota failure and retains current text/viewport for export and retry', () => {
    const disk = storage({ objects: [], canvas: elements })
    const workspace = open()
    workspace.session.setViewport({ x: 10, y: 20, scale: 1 })
    const good = disk.raw
    disk.fail(true)
    workspace.session.editText('note', 'Keep unsaved thought')
    workspace.session.setViewport({ x: 40, y: 50, scale: 1.45 })
    expect(workspace.error).toContain('only in this open tab')
    expect(disk.raw).toBe(good)
    const backup = legacyUiProjection(serializeState(workspace.state))
    expect(backup.canvas[1].text).toBe('Keep unsaved thought')
    expect(backup.canvasViewport).toEqual({ x: 40, y: 50, scale: 1.45 })
    disk.fail(false)
    expect(saveState(workspace.state)).toBeUndefined()
    expect(open().repository.read()).toEqual(workspace.repository.read())
  })

  it('refuses stale-tab edits and external corruption without overwriting either saved bytes or in-memory work', () => {
    const disk = storage({ objects: [], canvas: elements })
    const first = open(), second = open()
    first.session.editText('note', 'First tab')
    const good = disk.raw
    second.session.editText('note', 'Second tab')
    expect(second.error).toContain('Stored data changed')
    expect(disk.raw).toBe(good)
    expect(second.state.canvas[1].text).toBe('Second tab')
    disk.raw = '{broken'
    first.session.setViewport({ x: 1, y: 2, scale: 1 })
    expect(first.error).toContain('Stored data changed')
    expect(disk.raw).toBe('{broken')
  })

  it.each([null, { x: 0, y: 0 }, { x: 0, y: 0, scale: 0 }, { x: 'wrong', y: 0, scale: 1 }, { x: 0, y: 0, scale: 5 }])('fails closed on corrupt saved viewport %j', canvasViewport => {
    const disk = storage({ ...migrateLegacyState({ objects: [], canvas: elements }), canvasViewport })
    const original = disk.raw
    expect(loadStateResult().error).toContain('left untouched')
    expect(disk.raw).toBe(original)
    expect(disk.setItem).not.toHaveBeenCalled()
  })

  it('validates writes and isolates mutable caller snapshots', () => {
    storage({ objects: [], canvas: elements })
    const workspace = open(), document = workspace.repository.read()
    document.elements[1].text = 'Changed outside repository'
    expect(workspace.state.canvas[1].text).toBe('Original thought')
    expect(() => workspace.repository.write({ ...document, viewport: { x: Infinity, y: 0, scale: 1 } })).toThrow('Invalid canvas')
    expect(workspace.state.canvas[1].text).toBe('Original thought')
    workspace.repository.write(document)
    document.elements[1].text = 'Mutation after write'
    expect(workspace.state.canvas[1].text).toBe('Changed outside repository')
  })

  it('does not lose undo after unchanged input or an invalid edit', () => {
    storage({ objects: [], canvas: elements })
    const workspace = open(), session = workspace.session
    session.editText('note', 'Original thought')
    expect(session.canUndo).toBe(false)
    session.editText('note', 'Changed')
    expect(() => session.commit([...workspace.state.canvas, workspace.state.canvas[0]])).toThrow('Invalid canvas')
    session.undo()
    expect(workspace.state.canvas).toEqual(elements)
    session.redo()
    expect(workspace.state.canvas[1].text).toBe('Changed')
  })

  it('preserves a viewport when serializing a new state without a canonical model', () => {
    const state: AppState = { objects: [], canvas: elements, canvasViewport: { x: 3, y: 5, scale: .8 } }
    expect(legacyUiProjection(serializeState(state)).canvasViewport).toEqual(state.canvasViewport)
  })
})
