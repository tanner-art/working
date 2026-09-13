import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState } from './domain'
import { loadStateResult, saveState } from './store'

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

  it('reports unavailable storage and lets a failed write be retried without mutating work', () => {
    const setItem = vi.fn().mockImplementationOnce(() => { throw new Error('Quota exceeded') })
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('Storage denied') }, setItem })
    expect(loadStateResult().error).toBeTruthy()
    const state: AppState = { objects: [], canvas: [{ id: 'unsaved', type: 'text', text: 'Keep this thought', x: 10, y: 20 }] }
    const before = structuredClone(state)
    expect(saveState(state)).toContain('only in this open tab')
    expect(state).toEqual(before)
    expect(saveState(state)).toBeUndefined()
    expect(setItem.mock.calls[1][0]).toBe(key)
    expect(JSON.parse(setItem.mock.calls[1][1])).toEqual(before)
  })

  it('loads saved work again after a transient read failure clears', () => {
    const state: AppState = { objects: [], canvas: [{ id: 'saved', type: 'text', text: 'Original', x: 0, y: 0 }] }
    const getItem = vi.fn().mockImplementationOnce(() => { throw new Error('Storage denied') }).mockReturnValue(JSON.stringify(state))
    const setItem = vi.fn()
    vi.stubGlobal('localStorage', { getItem, setItem })
    expect(loadStateResult().error).toBeTruthy()
    expect(loadStateResult()).toEqual({ state })
    expect(getItem).toHaveBeenCalledWith(key)
    expect(setItem).not.toHaveBeenCalled()
  })

  it('refuses invalid state without replacing the existing stored value', () => {
    const setItem = vi.fn()
    vi.stubGlobal('localStorage', { setItem })
    expect(saveState({ objects: [] } as unknown as AppState)).toContain('format is invalid')
    expect(setItem).not.toHaveBeenCalled()
  })
})
