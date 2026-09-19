import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SupabaseClient } from '@supabase/supabase-js'
import { accountData, createAccountAdapter, createAccountSession, loadFailure, mergeAccountData, saveFailure, validateData, type AccountAdapter, type AccountRow } from './accountStorage'
import { defaultSettings } from './settings'
import { loadStateResult, makeObject, saveState } from './store'
import { legacyUiProjection } from './migration'
import { bankObjects, confirmObject, reviewObjects, updateObject } from './objectWorkflow'

const payload = () => accountData({ objects: [], canvas: [] }, defaultSettings, { enabled: false })
function database() {
  let saved: AccountRow | null = null
  let denied = false
  const calls: { operation: string; filters: Record<string, string>; options?: unknown }[] = []
  const client = { from: vi.fn(() => {
    let operation = 'read'
    let next: AccountRow
    let options: unknown
    const filters: Record<string, string> = {}
    const execute = () => {
      calls.push({ operation, filters, options })
      if (denied) return { data: null, error: Error('private detail') }
      if (operation === 'upsert' && !saved) saved = structuredClone(next)
      if (operation === 'update' && saved?.user_id === filters.user_id && saved?.revision === filters.revision) saved = structuredClone(next)
      const matches = operation !== 'update' || saved?.revision === next.revision
      return { data: matches && (!filters.user_id || saved?.user_id === filters.user_id) ? saved : null, error: null }
    }
    const query = {
      select: () => query, abortSignal: () => query,
      eq: (key: string, value: string) => { filters[key] = value; return query },
      upsert: (value: AccountRow, opts: unknown) => { operation = 'upsert'; next = value; options = opts; return query },
      update: (value: AccountRow) => { operation = 'update'; next = value; return query },
      maybeSingle: async () => execute(), single: async () => execute(),
    }
    return query
  }) }
  const adapter = createAccountAdapter(client as unknown as SupabaseClient, 'account_data')!
  return { adapter, calls, client, deny: () => { denied = true }, saved: () => saved }
}

afterEach(() => vi.unstubAllGlobals())
describe('account adapter', () => {
  it('requires a client and explicit non-secret table configuration', () => {
    expect(createAccountAdapter(undefined, 'account_data')).toBeUndefined()
    const client = {} as SupabaseClient
    for (const table of [undefined, '', 'private.table', 'unsafe-name']) expect(createAccountAdapter(client, table)).toBeUndefined()
  })
  it('reads only the user row, creates with a non-overwriting upsert, and updates with a revision guard', async () => {
    const db = database()
    expect(await db.adapter.read('a')).toBeNull()
    const created = await db.adapter.write('a', payload(), null)
    expect(db.calls[1]).toMatchObject({ operation: 'upsert', options: { onConflict: 'user_id', ignoreDuplicates: true } })
    expect(await db.adapter.read('b')).toBeNull()
    expect(await db.adapter.read('a')).toEqual(created)
    const changed = await db.adapter.write('a', { ...payload(), settings: { ...defaultSettings, displayName: 'Phone' } }, created.revision)
    expect(changed.revision).not.toBe(created.revision)
    expect(db.calls.at(-1)).toMatchObject({ operation: 'update', filters: { user_id: 'a', revision: created.revision } })
    await expect(db.adapter.write('a', payload(), created.revision)).rejects.toThrow(saveFailure)
    await expect(db.adapter.write('a', payload(), null)).rejects.toThrow(saveFailure)
    expect(db.saved()).toEqual(changed)
  })
  it('fails closed on denied reads/writes without exposing provider details', async () => {
    const db = database(); db.deny()
    await expect(db.adapter.read('a')).rejects.toThrow(loadFailure)
    await expect(db.adapter.write('a', payload(), null)).rejects.toThrow(saveFailure)
  })
  it('rejects malformed model, settings and digest', () => {
    for (const value of [null, { ...payload(), model: {} }, { ...payload(), settings: {} }, { ...payload(), digest: { enabled: true } }]) {
      expect(() => validateData(value)).toThrow()
    }
  })
})

describe('explicit account session', () => {
  it('does not read, migrate or save on sign-in; local-only storage continues unchanged', async () => {
    const db = database()
    const session = createAccountSession(db.adapter, 'a', () => 'a')
    expect(db.client.from).not.toHaveBeenCalled()
    await expect(session.save(payload())).rejects.toThrow(saveFailure)
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) })
    const loaded = loadStateResult()
    expect(saveState(loaded.state)).toBeUndefined()
    expect(loadStateResult().error).toBeUndefined()
    expect(db.client.from).not.toHaveBeenCalled()
    const before = [...storage]
    await session.open(accountData(loaded.state, defaultSettings, { enabled: false }))
    expect([...storage]).toEqual(before)
  })
  it('only activates after a successful load or import, preserves local data, and reports empty account', async () => {
    const db = database()
    const session = createAccountSession(db.adapter, 'a', () => 'a')
    await expect(session.open()).rejects.toThrow('No account data yet')
    await expect(session.save(payload())).rejects.toThrow(saveFailure)
    const source = payload(); const before = structuredClone(source)
    await session.open(source)
    expect(source).toEqual(before)
    const phone = createAccountSession(db.adapter, 'a', () => 'a')
    expect((await phone.open()).data).toEqual(source)
    await expect(phone.open(source)).rejects.toThrow('may already contain data')
  })
  it('surfaces offline load/save failures and stops automatic retries until explicit retry', async () => {
    const db = database()
    const adapter: AccountAdapter = { read: vi.fn(async () => { throw Error('offline') }), write: db.adapter.write }
    const session = createAccountSession(adapter, 'a', () => 'a')
    await expect(session.open()).rejects.toThrow(loadFailure)
    await session.open(payload())
    const write = vi.fn().mockRejectedValueOnce(Error('offline')).mockImplementation(db.adapter.write)
    adapter.write = write
    await expect(session.save(payload())).rejects.toThrow(saveFailure)
    await expect(session.save(payload())).rejects.toThrow(saveFailure)
    expect(write).toHaveBeenCalledOnce()
    await session.save(payload(), true)
    expect(write).toHaveBeenCalledTimes(2)
  })
  it('rejects stale devices instead of losing Review or Bank changes', async () => {
    const db = database()
    const desktop = createAccountSession(db.adapter, 'a', () => 'a')
    const phone = createAccountSession(db.adapter, 'a', () => 'a')
    await desktop.open(payload()); await phone.open()
    await desktop.save({ ...payload(), settings: { ...defaultSettings, displayName: 'Desktop' } })
    await expect(phone.save(payload())).rejects.toThrow(saveFailure)
    expect(db.saved()?.data.settings.displayName).toBe('Desktop')
  })
  it('serializes rapid saves and retains intermediate evidence revisions', async () => {
    const db = database()
    const session = createAccountSession(db.adapter, 'a', () => 'a')
    const item = makeObject({ kind: 'idea', originalContent: 'Original evidence', source: 'text', confidence: .9, interpretation: { summary: 'Idea', rationale: 'Explicit', suggestedKind: 'idea' } })
    const opened = await session.open(accountData({ objects: [item], canvas: [] }, defaultSettings, { enabled: false }))
    const first = updateObject(opened.state.objects[0], { ...opened.state.objects[0], context: 'Personal' })
    const second = updateObject(first, { ...first, context: 'Business' })
    await Promise.all([
      session.save(accountData({ ...opened.state, objects: [first] }, defaultSettings, { enabled: false })),
      session.save(accountData({ ...opened.state, objects: [second] }, defaultSettings, { enabled: false })),
    ])
    expect(db.saved()?.data.model.interpretations.length).toBe(3)
    expect(db.saved()?.data.model.captures).toEqual(opened.data.model.captures)
  })
  it('preserves Review, Bank folders, canvas, settings, digest and raw evidence through roundtrip', async () => {
    const idea = makeObject({ kind: 'idea', originalContent: 'Original idea', source: 'text', confidence: .9, interpretation: { summary: 'Idea', rationale: 'Explicit', suggestedKind: 'idea' } })
    const proposal = makeObject({ kind: 'action', originalContent: 'Maybe do this', source: 'text', confidence: .5, interpretation: { summary: 'Proposal', rationale: 'Uncertain', suggestedKind: 'action' } })
    const confirmed = confirmObject({ ...idea, context: 'Business' }, 'idea')
    const data = accountData({ objects: [confirmed, proposal], canvas: [{ id: 'node', type: 'text', text: 'Canvas evidence', x: 1, y: 2 }] }, { ...defaultSettings, displayName: 'Me', startPage: 'canvas' }, { enabled: true, confirmedAt: '2026-09-15T07:00:00Z' })
    const db = database(); await db.adapter.write('a', data, null)
    const loaded = (await createAccountSession(db.adapter, 'a', () => 'a').open())
    expect(loaded.data).toEqual(data)
    expect(reviewObjects(loaded.state.objects).map(o => o.id)).toContain(proposal.id)
    expect(bankObjects(loaded.state.objects).Business.map(o => o.id)).toContain(confirmed.id)
    expect(bankObjects(loaded.state.objects)).toEqual(bankObjects(legacyUiProjection(data.model).objects))
    expect(loaded.state.canvas).toEqual(data.model.canvas)
  })
  it('blocks writes and stale load completion after logout/account switching', async () => {
    const db = database(); let user: string | undefined = 'a'
    const session = createAccountSession(db.adapter, 'a', () => user)
    await session.open(payload()); user = 'b'
    const count = db.calls.length
    await expect(session.save(payload())).rejects.toThrow('session changed')
    expect(db.calls).toHaveLength(count)
    user = 'a'
    let resolve!: (row: AccountRow) => void
    const pending = createAccountSession({ ...db.adapter, read: () => new Promise(done => { resolve = done }) }, 'a', () => user).open()
    user = undefined; resolve(db.saved()!)
    await expect(pending).rejects.toThrow(loadFailure)
  })
})

describe('guided account merge', () => {
  const thought = (content: string) => makeObject({ kind: 'idea', originalContent: content, source: 'text', confidence: .9,
    interpretation: { summary: content, rationale: 'Explicit', suggestedKind: 'idea' } })

  it('combines disjoint device histories without mutating either source', () => {
    const account = accountData({ objects: [thought('Mac idea')], canvas: [{ id: 'mac-node', type: 'text', x: 1, y: 2 }] },
      { ...defaultSettings, displayName: 'Mac' }, { enabled: false })
    const device = accountData({ objects: [thought('Phone idea')], canvas: [{ id: 'phone-node', type: 'text', x: 3, y: 4 }] },
      { ...defaultSettings, displayName: 'Phone' }, { enabled: true, confirmedAt: '2026-09-19T07:00:00Z' })
    const before = structuredClone({ account, device })
    const result = mergeAccountData(account, device, { settings: 'device', digest: 'account' })
    expect({ account, device }).toEqual(before)
    expect(legacyUiProjection(result.data.model).objects.map(item => item.originalContent)).toEqual(['Mac idea', 'Phone idea'])
    expect(result.data.model.canvas.map(item => item.id)).toEqual(['mac-node', 'phone-node'])
    expect(result.data.settings.displayName).toBe('Phone')
    expect(result.data.digest.enabled).toBe(false)
    expect(result.preview.added).toEqual({ captures: 1, thoughts: 1, canvas: 1, events: 0 })
  })

  it('deduplicates identical records and stops on conflicting stable identities', () => {
    const item = thought('Shared idea')
    const account = accountData({ objects: [item], canvas: [] }, defaultSettings, { enabled: false })
    const duplicate = structuredClone(account)
    const result = mergeAccountData(account, duplicate, { settings: 'account', digest: 'account' })
    expect(result.data.model.captures).toHaveLength(1)
    expect(result.data.model.interpretations).toHaveLength(1)
    const conflict = structuredClone(duplicate)
    conflict.model.captures[0] = { ...conflict.model.captures[0], originalContent: 'Changed elsewhere' }
    expect(() => mergeAccountData(account, conflict, { settings: 'account', digest: 'account' })).toThrow('Merge stopped: capture identity')
  })

  it('previews before writing and rejects a stale account revision', async () => {
    const db = database()
    const account = accountData({ objects: [thought('Account')], canvas: [] }, defaultSettings, { enabled: false })
    const device = accountData({ objects: [thought('Device')], canvas: [] }, defaultSettings, { enabled: false })
    const original = await db.adapter.write('a', account, null)
    const session = createAccountSession(db.adapter, 'a', () => 'a')
    const plan = await session.previewMerge(device, { settings: 'account', digest: 'account' })
    expect(db.saved()?.revision).toBe(original.revision)
    await db.adapter.write('a', { ...account, settings: { ...defaultSettings, displayName: 'Other device' } }, original.revision)
    await expect(session.confirmMerge(plan)).rejects.toThrow('Merge was not saved')
    expect(db.saved()?.data.settings.displayName).toBe('Other device')
  })

  it('confirms the exact preview and preserves Review and Bank items through roundtrip', async () => {
    const db = database()
    const mac = confirmObject({ ...thought('Mac bank item'), context: 'Business' }, 'idea')
    const phone = { ...thought('Phone review item'), confidence: .5, status: 'review' as const }
    await db.adapter.write('a', accountData({ objects: [mac], canvas: [] }, defaultSettings, { enabled: false }), null)
    const session = createAccountSession(db.adapter, 'a', () => 'a')
    const plan = await session.previewMerge(accountData({ objects: [phone], canvas: [] }, defaultSettings, { enabled: false }),
      { settings: 'account', digest: 'device' })
    const merged = await session.confirmMerge(plan)
    expect(bankObjects(merged.state.objects).Business.map(item => item.originalContent)).toContain('Mac bank item')
    expect(reviewObjects(merged.state.objects).map(item => item.originalContent)).toContain('Phone review item')
    await expect(session.confirmMerge(plan)).rejects.toThrow('preview expired')
  })
})
