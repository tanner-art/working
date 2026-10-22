import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { CaptureLibrary } from './CaptureLibraryView'
import { captureLibraryFor, changeCaptureLibrary, captureFolderId, folderDestinations, folderTrail, isCaptureLibrary, searchCaptures, type CaptureLibraryState, type LibraryChange } from './captureLibrary'
import { makeObject, loadStateResult, saveState, serializeState } from './store'
import { isPersistedState, legacyUiProjection } from './migration'
import { accountData, createAccountSession, mergeAccountData, validateData, type AccountAdapter, type AccountRow } from './accountStorage'
import { defaultSettings } from './settings'
import { jsonbRoundTrip } from './testSupport/jsonbRoundTrip'
import { correctOriginal } from './reviewRevision'

const at = '2026-10-22T12:00:00.000Z'
const thought = (id: string, text = 'Remember the café project') => ({ ...makeObject({ kind: 'idea', originalContent: text, source: 'text', interpretation: { summary: 'Project notes', suggestedKind: 'idea', rationale: 'Captured thought' }, confidence: .5 }), id, createdAt: at })
const objects = [thought('one'), thought('two', 'A birthday gift')]
const empty = (): CaptureLibraryState => ({ folders: [], placements: [] })
const change = (library: CaptureLibraryState, change: LibraryChange) => changeCaptureLibrary(library, objects, change, at)
const folder = (library: CaptureLibraryState, id: string, parentId: string | null = null) => change(library, { type: 'create', id, name: id, parentId })
afterEach(() => vi.unstubAllGlobals())

describe('capture folders', () => {
  it('preserves context-based organization once, without copying or reclassifying captures', () => {
    const source = [{ ...objects[0], context: ' HOME ' }, { ...objects[1], context: 'Work' }]
    const before = structuredClone(source)
    const legacy = captureLibraryFor(source)
    expect(legacy.folders.map(f => f.name)).toEqual(['Personal', 'Business'])
    expect(captureFolderId(legacy, 'one')).toBe('capture-folder:personal')
    expect(captureLibraryFor([{ ...source[0], context: 'Work' }], legacy)).toBe(legacy)
    expect(source).toEqual(before)
  })
  it('nests, renames, decorates and moves a populated tree without changing capture identity', () => {
    let library = folder(folder(folder(empty(), 'Projects'), 'Art', 'Projects'), 'Archive')
    library = change(library, { type: 'move-capture', id: 'one', folderId: 'Art' })
    library = change(library, { type: 'edit', id: 'Art', name: '  My   art  ', color: 'purple', emoji: '🎨' })
    library = change(library, { type: 'move-folder', id: 'Projects', parentId: 'Archive' })
    expect(folderTrail(library, 'Art').map(f => f.name)).toEqual(['Archive', 'Projects', 'My art'])
    expect(library.folders.find(f => f.id === 'Art')).toMatchObject({ color: 'purple', emoji: '🎨' })
    expect(captureFolderId(library, 'one')).toBe('Art')
    library = change(library, { type: 'move-capture', id: 'one', folderId: null })
    expect(captureFolderId(library, 'one')).toBeNull()
  })
  it('rejects cycles, missing destinations, duplicates and unknown captures without mutating input', () => {
    const library = folder(folder(empty(), 'Parent'), 'Child', 'Parent')
    const before = structuredClone(library)
    for (const operation of [
      { type: 'move-folder', id: 'Parent', parentId: 'Child' },
      { type: 'move-folder', id: 'Child', parentId: 'Child' },
      { type: 'move-folder', id: 'Child', parentId: 'missing' },
      { type: 'move-capture', id: 'one', folderId: 'missing' },
      { type: 'move-capture', id: 'missing', folderId: 'Parent' },
      { type: 'create', id: 'duplicate', name: ' PARENT ', parentId: null },
      { type: 'edit', id: 'Child', name: ' ' },
    ] as LibraryChange[]) expect(() => change(library, operation)).toThrow()
    expect(library).toEqual(before)
    expect(folderDestinations(library, 'Parent')).toEqual([])
    expect(folderDestinations(library, 'Child').map(f => f.id)).toEqual(['Parent'])
  })
  it('rejects duplicate destination names during moves and invalid stored presentation', () => {
    let library = folder(folder(empty(), 'a'), 'b')
    library = change(library, { type: 'create', id: 'nested', name: 'a', parentId: 'b' })
    expect(() => change(library, { type: 'move-folder', id: 'nested', parentId: null })).toThrow('already exists')
    for (const invalid of [null, {}, { folders: [], placements: [{ id: 'unknown', folderId: null }] },
      { ...library, folders: library.folders.map(f => ({ ...f, color: 'url(unsafe)' })) },
      { ...library, placements: [{ id: 'one', folderId: null }, { id: 'one', folderId: null }] },
      { ...library, extra: true }]) expect(isCaptureLibrary(invalid, ['one', 'two'])).toBe(false)
    expect(isCaptureLibrary({ ...library, folders: library.folders.map(f => ({ ...f, id: 123 })) }, ['one', 'two'])).toBe(false)
  })
})

describe('capture search', () => {
  it('searches pending, complete and archived captures, original/current text, meaning and folder paths', () => {
    const source = [objects[0], { ...objects[1], status: 'archived' as const }, { ...thought('three', 'first wording'), status: 'complete' as const, currentContent: 'Corrected content' }]
    let library = folder(empty(), 'Research')
    library = change(library, { type: 'move-capture', id: 'one', folderId: 'Research' })
    expect(searchCaptures(source, 'CAFE project', library).map(o => o.id)).toEqual(['one'])
    expect(searchCaptures(source, 'birthday', library).map(o => o.id)).toEqual(['two'])
    expect(searchCaptures(source, 'first wording', library).map(o => o.id)).toEqual(['three'])
    expect(searchCaptures(source, 'corrected', library).map(o => o.id)).toEqual(['three'])
    expect(searchCaptures(source, 'Research', library).map(o => o.id)).toEqual(['one'])
    expect(searchCaptures(source, 'Project notes', library)).toHaveLength(3)
    expect(searchCaptures(source, 'not-found-at-all', library)).toEqual([])
    expect(searchCaptures(source, '  ', library)).toHaveLength(3)
    expect(searchCaptures([thought('emoji', 'Plant a garden 🌱'), ...source], '🌱', library).map(o => o.id)).toEqual(['emoji'])
    expect(searchCaptures(source, '!!!', library)).toEqual([])
  })
  it('provides accessible search, folder controls and capture movement without dragging', () => {
    const html = renderToStaticMarkup(createElement(CaptureLibrary, { objects, library: folder(empty(), 'Projects'), onChange: () => {}, onOpen: () => {} }))
    for (const text of ['Search all captures', 'Open folder Projects', 'Options for folder Projects', 'Rename / customize', 'Move to…', 'Move capture Remember', 'draggable="true"']) expect(html).toContain(text)
  })
})

describe('folder persistence and account compatibility', () => {
  it('roundtrips local save/reload and export, preserving source, history and search after correction', () => {
    let raw: string | null = JSON.stringify({ objects, canvas: [] })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    let state = loadStateResult().state
    const original = structuredClone(state.model!.captures)
    state = correctOriginal(state, 'one', 'Updated wording', true)
    const library = change(folder(empty(), 'Art'), { type: 'move-capture', id: 'one', folderId: 'Art' })
    state = { ...state, captureLibrary: library }
    expect(saveState(state)).toBeUndefined()
    const loaded = loadStateResult()
    expect(loaded.error).toBeUndefined()
    expect(loaded.state.captureLibrary).toEqual(library)
    expect(loaded.state.model!.captures).toEqual(original)
    expect(searchCaptures(loaded.state.objects, 'cafe', loaded.state.captureLibrary!)).toHaveLength(1)
    expect(searchCaptures(loaded.state.objects, 'updated wording', loaded.state.captureLibrary!)).toHaveLength(1)
    const exported = JSON.parse(JSON.stringify(serializeState(loaded.state)))
    expect(isPersistedState(exported)).toBe(true)
    raw = JSON.stringify({ ...loaded.state.model, captureLibrary: { ...library, placements: [{ id: 'one', folderId: 'missing' }] } })
    const bad = raw
    expect(loadStateResult().error).toContain('untouched')
    expect(raw).toBe(bad)
  })
  it('retains the stale-tab write guard for folder-only edits', () => {
    let raw: string | null = JSON.stringify({ objects, canvas: [] })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const first = loadStateResult().state
    const stale = loadStateResult().state
    expect(saveState({ ...first, captureLibrary: folder(empty(), 'Phone') })).toBeUndefined()
    const saved = raw
    expect(saveState({ ...stale, captureLibrary: folder(empty(), 'Laptop') })).toContain('Stored data changed')
    expect(raw).toBe(saved)
  })
  it('saves folder-only changes through the account session and reads them on a second device', async () => {
    let row: AccountRow | null = null
    const adapter: AccountAdapter = {
      read: async () => row,
      write: async (userId, data, revision) => {
        if (revision !== (row?.revision ?? null)) throw Error('conflict')
        row = jsonbRoundTrip({ user_id: userId, revision: crypto.randomUUID(), data: validateData(data) })
        return row!
      },
    }
    const phone = createAccountSession(adapter, 'owner', () => 'owner')
    const laptop = createAccountSession(adapter, 'owner', () => 'owner')
    const opened = await phone.open(accountData({ objects, canvas: [] }, defaultSettings, { enabled: false }))
    await laptop.open()
    const library = change(folder(empty(), 'Phone folder'), { type: 'move-capture', id: 'two', folderId: 'Phone folder' })
    await phone.save(phone.snapshot({ ...opened.state, captureLibrary: library }, defaultSettings, { enabled: false }))
    const refreshed = await laptop.refresh(() => true)
    expect(refreshed.status).toBe('updated')
    if (refreshed.status !== 'updated') throw Error('Expected updated account snapshot')
    expect(refreshed.state.captureLibrary).toEqual(library)
    expect(searchCaptures(refreshed.state.objects, 'birthday', library).map(o => o.id)).toEqual(['two'])
  })
  it('unions independent folders, deduplicates identical metadata, and refuses conflicting identities', () => {
    const account = accountData({ objects, canvas: [], captureLibrary: folder(empty(), 'Account') }, defaultSettings, { enabled: false })
    const device = accountData({ objects, canvas: [], captureLibrary: folder(empty(), 'Device') }, defaultSettings, { enabled: false })
    const choices = { settings: 'account', digest: 'account' } as const
    const merged = mergeAccountData(account, device, choices).data
    expect(legacyUiProjection(merged.model).captureLibrary!.folders.map(f => f.id)).toEqual(['Account', 'Device'])
    expect(mergeAccountData(merged, merged, choices).data.model.captureLibrary).toEqual(merged.model.captureLibrary)
    const conflict = structuredClone(account)
    conflict.model.captureLibrary!.folders[0].name = 'Changed elsewhere'
    expect(() => mergeAccountData(account, conflict, choices)).toThrow('folder identity')
    const nameConflict = structuredClone(device)
    nameConflict.model.captureLibrary!.folders[0].name = 'Account'
    expect(() => mergeAccountData(account, nameConflict, choices)).toThrow('folder names or destinations conflict')
    const placed = structuredClone(account)
    placed.model.captureLibrary = change(placed.model.captureLibrary!, { type: 'move-capture', id: 'one', folderId: 'Account' })
    const unfiled = structuredClone(placed)
    unfiled.model.captureLibrary = change(unfiled.model.captureLibrary!, { type: 'move-capture', id: 'one', folderId: null })
    expect(() => mergeAccountData(placed, unfiled, choices)).toThrow('capture folder placement identity')
    const legacy = accountData({ objects: [{ ...thought('old'), context: 'Personal' }], canvas: [] }, defaultSettings, { enabled: false })
    expect(mergeAccountData(account, legacy, choices).data.model.captureLibrary!.placements).toContainEqual({ id: 'old', folderId: 'capture-folder:personal' })
  })
})
