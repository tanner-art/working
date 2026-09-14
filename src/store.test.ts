import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState } from './domain'
import { migrateLegacyState } from './migration'
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

  it('lets a failed write be retried without mutating work', () => {
    const setItem = vi.fn().mockImplementationOnce(() => { throw new Error('Quota exceeded') })
    vi.stubGlobal('localStorage', { getItem: () => null, setItem })
    const state: AppState = { objects: [], canvas: [{ id: 'unsaved', type: 'text', text: 'Keep this thought', x: 10, y: 20 }] }
    const before = structuredClone(state)
    expect(saveState(state)).toContain('only in this open tab')
    expect(state).toEqual(before)
    expect(saveState(state)).toBeUndefined()
    expect(setItem.mock.calls[1][0]).toBe(key)
    expect(JSON.parse(setItem.mock.calls[1][1])).toEqual(migrateLegacyState(before))
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
