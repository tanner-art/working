import { describe, expect, it, vi } from 'vitest'
import { accountData, createAccountSession, type AccountAdapter, type AccountData, type AccountRow } from './accountStorage'
import { canRefreshWorkspace, deviceOnlyCaptureCount, openSignedInWorkspace } from './accountSync'
import { makeObject } from './store'
import { defaultSettings } from './settings'

const captures = (count: number): AccountData => accountData({ objects: Array.from({ length: count }, (_, n) => makeObject({
  kind: 'idea', originalContent: `Preserved phone capture ${n + 1}`, source: 'text', confidence: .7,
  interpretation: { summary: `Thought ${n + 1}`, rationale: 'Fixture', suggestedKind: 'idea' },
})), canvas: [] }, defaultSettings, { enabled: false })
function backend() {
  let row: AccountRow | null = null
  const adapter: AccountAdapter = {
    read: vi.fn(async userId => row?.user_id === userId ? structuredClone(row) : null),
    write: vi.fn(async (userId, data, revision) => {
      if ((row?.revision ?? null) !== revision || (row && row.user_id !== userId)) throw Error('conflict')
      row = { user_id: userId, data: structuredClone(data), revision: crypto.randomUUID() }
      return structuredClone(row)
    }),
  }
  return { adapter, row: () => structuredClone(row), remove: () => { row = null } }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

describe('automatic cross-device account workspace', () => {
  it('opens all 98 exact captures on laptop sign-in and reload without local writes', async () => {
    const db = backend(); const local = captures(98); const original = structuredClone(local)
    const phone = createAccountSession(db.adapter, 'owner', () => 'owner')
    await phone.open(local)
    const laptop = await openSignedInWorkspace(db.adapter, 'owner', () => 'owner')
    expect(laptop!.data.model.captures).toEqual(original.model.captures)
    expect(laptop!.state.objects).toHaveLength(98)
    expect(local).toEqual(original)
    expect((await openSignedInWorkspace(db.adapter, 'owner', () => 'owner'))!.data).toEqual(local)
    expect(db.adapter.write).toHaveBeenCalledTimes(1)
  })
  it('distinguishes empty account from offline, denied or invalid account reads', async () => {
    const db = backend()
    expect(await openSignedInWorkspace(db.adapter, 'owner', () => 'owner')).toBeUndefined()
    expect(db.adapter.write).not.toHaveBeenCalled()
    vi.mocked(db.adapter.read).mockRejectedValueOnce(Error('offline'))
    await expect(openSignedInWorkspace(db.adapter, 'owner', () => 'owner')).rejects.toThrow('could not be loaded')
  })
  it('does not load a different account or accept a late sign-out response', async () => {
    const db = backend(); await db.adapter.write('owner', captures(98), null)
    expect(await openSignedInWorkspace(db.adapter, 'other', () => 'other')).toBeUndefined()
    const read = deferred<AccountRow | null>(); let current: string | undefined = 'owner'
    vi.mocked(db.adapter.read).mockReturnValueOnce(read.promise)
    const opened = openSignedInWorkspace(db.adapter, 'owner', () => current)
    current = undefined; read.resolve(db.row())
    await expect(opened).rejects.toThrow()
  })
  it('refreshes another device save without echo writes, then saves against the refreshed revision', async () => {
    const db = backend(); const phone = createAccountSession(db.adapter, 'owner', () => 'owner')
    const initial = await phone.open(captures(98))
    const laptop = (await openSignedInWorkspace(db.adapter, 'owner', () => 'owner'))!
    const extra = makeObject({ kind: 'idea', originalContent: 'Capture 99', source: 'text', confidence: .7, interpretation: { summary: '99', rationale: 'Fixture', suggestedKind: 'idea' } })
    await phone.save(phone.snapshot({ ...initial.state, objects: [...initial.state.objects, extra] }, initial.data.settings, initial.data.digest))
    const refreshed = await laptop.session.refresh(() => true)
    expect(refreshed.status).toBe('updated')
    if (refreshed.status !== 'updated') throw Error('expected update')
    expect(refreshed.state.objects).toHaveLength(99)
    expect(db.adapter.write).toHaveBeenCalledTimes(2)
    await laptop.session.save(laptop.session.snapshot(refreshed.state, { ...refreshed.data.settings, displayName: 'Laptop' }, refreshed.data.digest))
    expect(db.row()!.data.model.captures).toHaveLength(99)
    expect((await phone.refresh(() => true)).status).toBe('updated')
  })
  it('does not advance revision if an editor opens or draft changes during the read', async () => {
    const db = backend(); const phone = createAccountSession(db.adapter, 'owner', () => 'owner')
    const initial = await phone.open(captures(98))
    const laptop = (await openSignedInWorkspace(db.adapter, 'owner', () => 'owner'))!
    await phone.save({ ...initial.data, settings: { ...defaultSettings, displayName: 'Phone' } })
    expect((await laptop.session.refresh(() => false)).status).toBe('deferred')
    await expect(laptop.session.save(laptop.data)).rejects.toThrow('could not be saved')
    expect(db.row()!.data.settings.displayName).toBe('Phone')
    expect((await laptop.session.refresh(() => true)).status).toBe('deferred')
  })
  it('does not refresh over a queued save or apply an older read after a save completes', async () => {
    const db = backend(); const laptop = createAccountSession(db.adapter, 'owner', () => 'owner')
    const initial = await laptop.open(captures(98))
    const old = db.row(); const read = deferred<AccountRow | null>()
    vi.mocked(db.adapter.read).mockReturnValueOnce(read.promise)
    const refreshing = laptop.refresh(() => true)
    const saving = laptop.save({ ...initial.data, settings: { ...defaultSettings, displayName: 'Newest' } })
    expect((await laptop.refresh(() => true)).status).toBe('deferred')
    await saving; read.resolve(old)
    expect((await refreshing).status).toBe('deferred')
    expect(db.row()!.data.settings.displayName).toBe('Newest')
    expect((await laptop.refresh(() => true)).status).toBe('unchanged')
  })
  it('preserves the loaded snapshot on failed reads and missing rows instead of replacing it with empty data', async () => {
    const db = backend(); const session = createAccountSession(db.adapter, 'owner', () => 'owner')
    const loaded = await session.open(captures(98))
    vi.mocked(db.adapter.read).mockRejectedValueOnce(Error('offline'))
    await expect(session.refresh(() => true)).rejects.toThrow('could not be loaded')
    db.remove()
    await expect(session.refresh(() => true)).rejects.toThrow('could not be loaded')
    expect(loaded.state.objects).toHaveLength(98)
    expect(db.adapter.write).toHaveBeenCalledTimes(1)
  })
  it('detects device-only captures without comparing or copying private text', () => {
    const local = captures(98)
    expect(deviceOnlyCaptureCount(local, local)).toBe(0)
    expect(deviceOnlyCaptureCount(local, captures(0))).toBe(98)
  })
})

describe('workspace refresh boundaries', () => {
  const safe = { view: 'capture', draft: '', selected: false, busy: false, saveError: false, pendingCanvas: false, focusedEditor: false, customSurface: false }
  it('only refreshes non-editing surfaces', () => {
    for (const view of ['capture', 'today', 'digest', 'beta-home']) expect(canRefreshWorkspace({ ...safe, view })).toBe(true)
    for (const view of ['review', 'canvas', 'calendar', 'schedule', 'settings', 'commitments']) expect(canRefreshWorkspace({ ...safe, view })).toBe(false)
  })
  it('protects drafts, selected-object editors, delayed canvas saves and focused inputs', () => {
    for (const key of ['selected', 'busy', 'saveError', 'pendingCanvas', 'focusedEditor', 'customSurface']) expect(canRefreshWorkspace({ ...safe, [key]: true })).toBe(false)
    expect(canRefreshWorkspace({ ...safe, draft: 'Unsubmitted capture' })).toBe(false)
  })
})
