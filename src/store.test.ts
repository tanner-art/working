import { updateObject } from './objectWorkflow'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, CanvasElement } from './domain'
import { migrateLegacyState } from './migration'
import { correctOriginal, reviewTextSnapshot, reviseInterpretation } from './reviewRevision'
import { loadStateResult, saveState, serializeState, makeObject } from './store'

const key = 'thoughtflow-state-v1'

describe('persistence failure handling (ported from 7c0ee6b)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('distinguishes a new workspace from unreadable saved thoughts without overwriting them', () => {
    const setItem = vi.fn()
    const getItem = vi.fn().mockReturnValue(null)
    vi.stubGlobal('localStorage', { getItem, setItem })
    expect(loadStateResult().error).toBeUndefined()
    for (const raw of ['{broken', '{"objects": []}', '', 'null']) {
      getItem.mockReturnValue(raw)
      expect(loadStateResult().error).toContain('left untouched')
    }
    expect(setItem).not.toHaveBeenCalled()
  })

  it('lets a failed write be retried without mutating work', () => {
    const setItem = vi.fn().mockImplementationOnce(() => { throw new Error('Quota exceeded') })
    vi.stubGlobal('localStorage', { getItem: () => null, setItem })
    const state: AppState = { objects: [], canvas: [{ id: 'unsaved', type: 'text', text: 'Keep this thought', x: 10, y: 20 }] }
    const before = structuredClone(state)
    expect(saveState(state)).toContain('only in this open tab')
    expect(state).toEqual(before)
    expect(saveState(state)).toBeUndefined()
    expect(setItem.mock.calls[1][0]).toBe(key)
    expect(JSON.parse(setItem.mock.calls[1][1])).toEqual(serializeState(before))
  })

  it('loads saved work again after a transient read failure clears', () => {
    const state: AppState = { objects: [], canvas: [{ id: 'saved', type: 'text', text: 'Original', x: 0, y: 0 }] }
    const getItem = vi.fn().mockImplementationOnce(() => { throw new Error('Storage denied') }).mockReturnValue(JSON.stringify(state))
    const setItem = vi.fn()
    vi.stubGlobal('localStorage', { getItem, setItem })
    expect(loadStateResult().error).toBeTruthy()
    expect(loadStateResult()).toMatchObject({ state })
    expect(getItem).toHaveBeenCalledWith(key)
    expect(setItem).not.toHaveBeenCalled()
  })

  it('refuses invalid state without replacing the existing stored value', () => {
    const setItem = vi.fn()
    vi.stubGlobal('localStorage', { setItem })
    expect(saveState({ objects: [] } as unknown as AppState)).toContain('format is invalid')
    expect(setItem).not.toHaveBeenCalled()
  })

  it('fails loudly for invalid connection styling without replacing stored data', () => {
    const setItem = vi.fn()
    vi.stubGlobal('localStorage', { getItem: () => null, setItem })
    const invalid: AppState = { objects: [], canvas: [{ id: 'edge', type: 'arrow', x: 0, y: 0, fromId: 'a', toId: 'b', connectionPattern: 'wavy' as 'solid' }] }
    expect(saveState(invalid)).toContain('format is invalid')
    const misplaced: AppState = { objects: [], canvas: [{ id: 'block', type: 'text', x: 0, y: 0, connectionWeight: 'bold' }] }
    expect(saveState(misplaced)).toContain('format is invalid')
    expect(setItem).not.toHaveBeenCalled()
  })
})


describe('TASK-024 shape persistence', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('migrates and roundtrips every shape with groups and styled connectors without semantic changes', () => {
    const canvas: CanvasElement[] = [
      { id: 'group', type: 'container', x: 0, y: 0 },
      { id: 'legacy', type: 'text', x: 10, y: 20, text: 'Unchanged' },
      ...(['rectangle', 'rounded-rectangle', 'ellipse', 'diamond'] as const).map((shape, index) => ({ id: shape, type: 'text' as const, shape, x: index * 200, y: -100, width: 180, height: 120, text: 'Preserved', groupId: 'group' })),
      { id: 'edge', type: 'arrow', x: 0, y: 0, fromId: 'ellipse', toId: 'diamond', connectionPath: 'curved', connectionPattern: 'dotted', connectionWeight: 'bold' },
    ]
    let raw = JSON.stringify({ objects: [], canvas })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const loaded = loadStateResult()
    expect(loaded.error).toBeUndefined()
    expect(loaded.state.canvas).toEqual(canvas)
    expect(saveState(loaded.state)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(reloaded.state.canvas).toEqual(canvas)
    expect(reloaded.state.model).toEqual({ ...loaded.state.model, canvasBank: loaded.state.canvasBank })
    expect(reloaded.state.model?.semanticObjects).toEqual([])
    expect(reloaded.state.canvas[1]).not.toHaveProperty('shape')
  })
  it.each([
    { type: 'text', shape: 'triangle' },
    { type: 'container', shape: 'ellipse' },
    { type: 'arrow', shape: 'diamond', fromId: 'a', toId: 'b' },
  ])('rejects unsupported or misplaced shape metadata: %j', patch => {
    const state = { objects: [], canvas: [{ id: 'invalid', x: 0, y: 0, ...patch }] } as AppState
    const raw = JSON.stringify(state), setItem = vi.fn()
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem })
    expect(loadStateResult().error).toContain('left untouched')
    expect(saveState(state)).toContain('format is invalid')
    expect(setItem).not.toHaveBeenCalled()
  })
})

describe('account import serialization', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('includes every saved evidence revision without writing local storage during serialization', () => {
    let raw: string | null = null
    const setItem = vi.fn((_key: string, value: string) => { raw = value })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem })
    const item = makeObject({ kind: 'idea', originalContent: 'Immutable original', source: 'text', confidence: .9, interpretation: { summary: 'Idea', suggestedKind: 'idea', rationale: 'Explicit' } })
    raw = JSON.stringify(migrateLegacyState({ objects: [item], canvas: [] }))
    let state = loadStateResult().state
    state = { ...state, objects: [updateObject(state.objects[0], { ...state.objects[0], context: 'Personal' })] }
    expect(saveState(state)).toBeUndefined()
    state = { ...state, objects: [updateObject(state.objects[0], { ...state.objects[0], context: 'Business' })] }
    expect(saveState(state)).toBeUndefined()
    const before = raw
    const exported = serializeState(state)
    expect(exported.interpretations.slice(0, JSON.parse(raw!).interpretations.length)).toEqual(JSON.parse(raw!).interpretations)
    expect(exported.interpretations.map(item => item.legacy.context)).toEqual(expect.arrayContaining([undefined, 'Personal', 'Business']))
    expect(exported.captures).toEqual(JSON.parse(raw!).captures)
    expect(raw).toBe(before)
    expect(setItem).toHaveBeenCalledTimes(2)
  })
})

describe('TASK-046 review revision persistence', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('reloads revisions and corrections through storage with source preserved', () => {
    let raw = JSON.stringify({ objects: [makeObject({ kind: 'idea', originalContent: 'orginal', source: 'text', confidence: .9,
      interpretation: { summary: 'First', rationale: 'r', suggestedKind: 'idea' } })], canvas: [] })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    vi.stubGlobal('crypto', { randomUUID: () => 'fix-1' })
    const loaded = loadStateResult()
    const id = loaded.state.objects[0].id
    let state = reviseInterpretation(loaded.state, id, 'Second', '2026-09-20T01:00:00.000Z')
    state = correctOriginal(state, id, 'original', true, '2026-09-20T02:00:00.000Z')
    expect(saveState(state)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(reloaded.state.objects[0]).toMatchObject({ originalContent: 'orginal', currentContent: 'original' })
    const snapshot = reviewTextSnapshot(reloaded.state, id)
    expect(snapshot.revisions).toEqual([{ at: '2026-09-20T01:00:00.000Z', from: 'First', to: 'Second' }])
    expect(snapshot.corrections).toHaveLength(1)
    expect(reloaded.state.model?.interpretations).toHaveLength(2)
  })
})
