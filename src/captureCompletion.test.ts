import { afterEach, describe, expect, it, vi } from 'vitest'
import { accountData, createAccountSession, mergeAccountData, validateData, type AccountAdapter, type AccountRow } from './accountStorage'
import { captureLibraryFor, changeCaptureLibrary, filterCaptureCompletion, isCaptureCompleted, isCaptureLibrary } from './captureLibrary'
import { makeObject, loadStateResult, saveState, serializeState } from './store'
import { defaultSettings } from './settings'
import { jsonbRoundTrip } from './testSupport/jsonbRoundTrip'
import { copyCaptureText } from './CopyCaptureButton'

const objects = ['first', 'second'].map(id => ({ ...makeObject({ kind: 'action', source: 'text', originalContent: `Original ${id}`, confidence: .7, interpretation: { summary: id, suggestedKind: 'action', rationale: 'test' } }), id }))
const empty = () => captureLibraryFor(objects)
const complete = () => changeCaptureLibrary(empty(), objects, { type: 'complete-capture', id: 'first', completed: true })
afterEach(() => vi.unstubAllGlobals())

describe('capture completion independent of semantic work', () => {
  it('marks and reopens without changing capture, interpretation, history, or action state', () => {
    const before = structuredClone(objects)
    const library = complete()
    expect(filterCaptureCompletion(objects, library, 'completed').map(o => o.id)).toEqual(['first'])
    expect(filterCaptureCompletion(objects, library, 'open').map(o => o.id)).toEqual(['second'])
    expect(filterCaptureCompletion(objects, library, 'all')).toEqual(objects)
    const reopened = changeCaptureLibrary(library, objects, { type: 'complete-capture', id: 'first', completed: false })
    expect(isCaptureCompleted(reopened, objects[0])).toBe(false)
    expect(isCaptureCompleted(library, objects[0])).toBe(true)
    expect(objects).toEqual(before)
  })
  it('keeps legacy complete captures completed unless explicitly reopened', () => {
    const legacy = { ...objects[0], status: 'complete' as const }
    expect(isCaptureCompleted(empty(), legacy)).toBe(true)
    const reopened = changeCaptureLibrary(empty(), [legacy], { type: 'complete-capture', id: legacy.id, completed: false })
    expect(isCaptureCompleted(reopened, legacy)).toBe(false)
    expect(legacy.status).toBe('complete')
  })
  it('rejects malformed, duplicate and dangling completion records', () => {
    for (const completions of [null, {}, [null], [{ id: 'missing', completed: true }], [{ id: 'first', completed: 'yes' }], [{ id: 'first', completed: true, extra: 1 }], [{ id: 'first', completed: true }, { id: 'first', completed: false }]]) {
      expect(isCaptureLibrary({ ...empty(), completions }, objects.map(o => o.id))).toBe(false)
    }
    expect(() => changeCaptureLibrary(empty(), objects, { type: 'complete-capture', id: 'missing', completed: true })).toThrow()
  })
  it('persists through local reload/export without rewriting source or semantic records', () => {
    let raw: string | null = JSON.stringify({ objects, canvas: [] })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const state = loadStateResult().state
    const before = serializeState(state)
    expect(saveState({ ...state, captureLibrary: complete() })).toBeUndefined()
    const loaded = loadStateResult()
    expect(loaded.error).toBeUndefined()
    const after = serializeState(loaded.state)
    expect(after).toEqual({ ...before, captureLibrary: complete() })
    expect(isCaptureCompleted(loaded.state.captureLibrary!, loaded.state.objects[0])).toBe(true)
  })
  it('syncs completion to a second device with the existing revision guard', async () => {
    let row: AccountRow | null = null
    const adapter: AccountAdapter = { read: async () => row, write: async (userId, data, revision) => {
      if (revision !== (row?.revision ?? null)) throw Error('conflict')
      row = jsonbRoundTrip({ user_id: userId, revision: crypto.randomUUID(), data: validateData(data) }); return row!
    } }
    const phone = createAccountSession(adapter, 'owner', () => 'owner')
    const laptop = createAccountSession(adapter, 'owner', () => 'owner')
    const opened = await phone.open(accountData({ objects, canvas: [] }, defaultSettings, { enabled: false }))
    await laptop.open()
    await phone.save(phone.snapshot({ ...opened.state, captureLibrary: complete() }, defaultSettings, { enabled: false }))
    const refreshed = await laptop.refresh(() => true)
    expect(refreshed.status).toBe('updated')
    if (refreshed.status !== 'updated') throw Error('No refreshed state')
    expect(refreshed.state.captureLibrary).toEqual(complete())
  })
  it('merges new completion records but refuses conflicting Done/Reopen decisions', () => {
    const data = (library = empty()) => accountData({ objects, canvas: [], captureLibrary: library }, defaultSettings, { enabled: false })
    const choices = { settings: 'account', digest: 'account' } as const
    expect(mergeAccountData(data(), data(complete()), choices).data.model.captureLibrary).toEqual(complete())
    expect(mergeAccountData(data(complete()), data(complete()), choices).data.model.captureLibrary).toEqual(complete())
    const reopened = changeCaptureLibrary(complete(), objects, { type: 'complete-capture', id: 'first', completed: false })
    expect(() => mergeAccountData(data(complete()), data(reopened), choices)).toThrow('capture completion identity')
  })
})

describe('copy capture text', () => {
  it('copies the exact provided text, including line breaks and emoji', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    await copyCaptureText('My thought\n🎨 next line', { writeText })
    expect(writeText).toHaveBeenCalledWith('My thought\n🎨 next line')
  })
  it('does not report success when clipboard access is missing or denied', async () => {
    await expect(copyCaptureText('text', undefined)).rejects.toThrow('unavailable')
    await expect(copyCaptureText('text', { writeText: vi.fn().mockRejectedValue(Error('denied')) })).rejects.toThrow('denied')
  })
})
