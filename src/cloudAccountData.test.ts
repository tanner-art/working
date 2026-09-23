import { describe, expect, it, vi } from 'vitest'
import { accountData, AccountStorageError, type AccountAdapter, type AccountRow } from './accountStorage'
import { createCloudAccountData, type AccountRecoveryCache, type AccountRecoveryRecord } from './cloudAccountData'
import { defaultSettings } from './settings'
import { makeObject } from './store'

const data = (name = '') => accountData(
  { objects: [], canvas: [] },
  { ...defaultSettings, displayName: name },
  { enabled: false },
)

function recoveryCache() {
  const records = new Map<string, AccountRecoveryRecord>()
  const cache: AccountRecoveryCache = {
    read: ownerId => records.get(ownerId) && structuredClone(records.get(ownerId)!),
    write: record => { records.set(record.ownerId, structuredClone(record)) },
  }
  return { cache, records }
}

function accountDatabase() {
  const rows = new Map<string, AccountRow>()
  let offline = false
  const adapter: AccountAdapter = {
    async read(ownerId) {
      if (offline) throw new AccountStorageError('load-unavailable', 'offline')
      const row = rows.get(ownerId)
      return row ? structuredClone(row) : null
    },
    async write(ownerId, payload, revision) {
      if (offline) throw new AccountStorageError('save-unavailable', 'offline')
      const current = rows.get(ownerId)
      if ((revision === null && current) || (revision !== null && current?.revision !== revision)) {
        throw new AccountStorageError('conflict', 'stale')
      }
      const row = { user_id: ownerId, revision: crypto.randomUUID(), data: structuredClone(payload) }
      rows.set(ownerId, row)
      return structuredClone(row)
    },
  }
  return { adapter, rows, setOffline: (value: boolean) => { offline = value } }
}

function setup(initial = data('Local')) {
  const db = accountDatabase()
  const recovery = recoveryCache()
  let user: string | undefined
  const local = { read: vi.fn(() => structuredClone(initial)) }
  const coordinator = createCloudAccountData({ adapter: db.adapter, local, recovery: recovery.cache, currentUser: () => user, now: () => '2026-09-23T10:00:00.000Z' })
  return { db, recovery, local, coordinator, setUser: (next?: string) => { user = next } }
}

describe('cloud-first account data orchestration', () => {
  it('keeps signed-out use local and performs no account request', async () => {
    const setupResult = setup()
    const read = vi.spyOn(setupResult.db.adapter, 'read')
    const state = await setupResult.coordinator.open(null)
    expect(state).toMatchObject({ phase: 'local', source: 'local', dirty: false })
    expect(state.data.settings.displayName).toBe('Local')
    expect(read).not.toHaveBeenCalled()
  })

  it('uses the signed-in owner cloud row by default and does not rewrite local captures', async () => {
    const s = setup(); s.setUser('owner-a')
    await s.db.adapter.write('owner-a', data('Cloud'), null)
    const before = structuredClone(await s.local.read())
    const state = await s.coordinator.open({ user: { id: 'owner-a' } })
    expect(state).toMatchObject({ phase: 'cloud', source: 'cloud', ownerId: 'owner-a', dirty: false })
    expect(state.data.settings.displayName).toBe('Cloud')
    expect(await s.local.read()).toEqual(before)
    expect(s.recovery.records.get('owner-a')).toMatchObject({ ownerId: 'owner-a', dirty: false, data: { settings: { displayName: 'Cloud' } } })
  })

  it('keeps cloud authoritative when the optional browser recovery cache is unavailable', async () => {
    const db = accountDatabase()
    await db.adapter.write('owner-a', data('Cloud'), null)
    const coordinator = createCloudAccountData({
      adapter: db.adapter,
      local: { read: () => data('Local') },
      recovery: { read: () => { throw Error('blocked') }, write: () => { throw Error('quota') } },
      currentUser: () => 'owner-a',
    })
    const state = await coordinator.open({ user: { id: 'owner-a' } })
    expect(state).toMatchObject({ phase: 'cloud', source: 'cloud', dirty: false })
    expect(state.data.settings.displayName).toBe('Cloud')
  })

  it('requires an explicit create-only import for an empty account and preserves local data', async () => {
    const capture = makeObject({
      kind: 'idea', originalContent: 'Preserve this local capture', source: 'text', confidence: .9,
      interpretation: { summary: 'Preserved idea', suggestedKind: 'idea', rationale: 'Explicit capture' },
    })
    const local = accountData({ objects: [capture], canvas: [] }, { ...defaultSettings, displayName: 'Local' }, { enabled: false })
    const s = setup(local); s.setUser('owner-a')
    const before = structuredClone(await s.local.read())
    expect(await s.coordinator.open({ user: { id: 'owner-a' } })).toMatchObject({ phase: 'cloud-empty', source: 'local' })
    expect(s.db.rows.has('owner-a')).toBe(false)
    const active = await s.coordinator.importLocal()
    expect(active).toMatchObject({ phase: 'cloud', source: 'cloud' })
    expect(s.db.rows.get('owner-a')?.data).toEqual(before)
    expect(s.db.rows.get('owner-a')?.data.model.captures[0]?.originalContent).toBe('Preserve this local capture')
    expect(await s.local.read()).toEqual(before)
  })

  it('serializes duplicate imports and creates an empty account only once', async () => {
    const s = setup(); s.setUser('owner-a')
    await s.coordinator.open({ user: { id: 'owner-a' } })
    const write = vi.spyOn(s.db.adapter, 'write')
    const results = await Promise.allSettled([s.coordinator.importLocal(), s.coordinator.importLocal()])
    expect(results.map(result => result.status)).toEqual(['fulfilled', 'rejected'])
    expect(write).toHaveBeenCalledOnce()
    expect(s.db.rows.get('owner-a')?.data.settings.displayName).toBe('Local')
  })

  it('reports a create-only import race as existing cloud data', async () => {
    const s = setup(); s.setUser('owner-a')
    const localBefore = structuredClone(await s.local.read())
    await s.coordinator.open({ user: { id: 'owner-a' } })
    await s.db.adapter.write('owner-a', data('Created elsewhere'), null)
    await expect(s.coordinator.importLocal()).rejects.toThrow('already contains cloud data')
    expect(s.db.rows.get('owner-a')?.data.settings.displayName).toBe('Created elsewhere')
    expect(await s.local.read()).toEqual(localBefore)
  })

  it('uses only the current owner recovery cache while offline', async () => {
    const s = setup(); s.setUser('owner-a')
    const original = await s.db.adapter.write('owner-a', data('Cached A'), null)
    s.recovery.cache.write({ ownerId: 'owner-a', revision: original.revision, data: original.data, dirty: false, updatedAt: 'now' })
    s.recovery.cache.write({ ownerId: 'owner-b', revision: 'b-revision', data: data('Cached B'), dirty: true, updatedAt: 'now' })
    s.db.setOffline(true)
    const state = await s.coordinator.open({ user: { id: 'owner-a' } })
    expect(state).toMatchObject({ phase: 'offline', source: 'recovery', ownerId: 'owner-a' })
    expect(state.data.settings.displayName).toBe('Cached A')
    expect(JSON.stringify(state)).not.toContain('Cached B')
  })

  it('falls back to local data offline without treating it as synced', async () => {
    const s = setup(); s.setUser('owner-a'); s.db.setOffline(true)
    const state = await s.coordinator.open({ user: { id: 'owner-a' } })
    expect(state).toMatchObject({ phase: 'offline', source: 'local', dirty: false })
    expect(state.data.settings.displayName).toBe('Local')
    await expect(s.coordinator.save(data('Unsaved'))).rejects.toThrow('not active')
  })

  it('preserves failed cloud saves in recovery storage and retries without overwriting local data', async () => {
    const s = setup(); s.setUser('owner-a')
    await s.db.adapter.write('owner-a', data('Cloud'), null)
    await s.coordinator.open({ user: { id: 'owner-a' } })
    const before = structuredClone(await s.local.read())
    s.db.setOffline(true)
    const offline = await s.coordinator.save(data('Offline edit'))
    expect(offline).toMatchObject({ phase: 'offline', source: 'recovery', dirty: true })
    expect(s.coordinator.exportRecovery()?.settings.displayName).toBe('Offline edit')
    expect(await s.local.read()).toEqual(before)
    s.db.setOffline(false)
    const recovered = await s.coordinator.retry()
    expect(recovered).toMatchObject({ phase: 'cloud', dirty: false })
    expect(s.db.rows.get('owner-a')?.data.settings.displayName).toBe('Offline edit')
  })

  it('restores a dirty recovery snapshot after restart when the cloud revision is unchanged', async () => {
    const s = setup(); s.setUser('owner-a')
    await s.db.adapter.write('owner-a', data('Cloud'), null)
    await s.coordinator.open({ user: { id: 'owner-a' } })
    s.db.setOffline(true)
    await s.coordinator.save(data('Recovered after restart'))
    s.db.setOffline(false)
    const restarted = createCloudAccountData({ adapter: s.db.adapter, local: s.local, recovery: s.recovery.cache, currentUser: () => 'owner-a' })
    const state = await restarted.open({ user: { id: 'owner-a' } })
    expect(state).toMatchObject({ phase: 'recovery', source: 'recovery', dirty: true })
    expect(state.data.settings.displayName).toBe('Recovered after restart')
    await restarted.retry()
    expect(s.db.rows.get('owner-a')?.data.settings.displayName).toBe('Recovered after restart')
  })

  it('serializes duplicate recovery retries against one expected revision', async () => {
    const s = setup(); s.setUser('owner-a')
    await s.db.adapter.write('owner-a', data('Cloud'), null)
    await s.coordinator.open({ user: { id: 'owner-a' } })
    s.db.setOffline(true)
    await s.coordinator.save(data('Recovered once'))
    s.db.setOffline(false)
    const write = vi.spyOn(s.db.adapter, 'write')
    const results = await Promise.allSettled([s.coordinator.retry(), s.coordinator.retry()])
    expect(results.map(result => result.status)).toEqual(['fulfilled', 'rejected'])
    expect(write).toHaveBeenCalledOnce()
    expect(s.db.rows.get('owner-a')?.data.settings.displayName).toBe('Recovered once')
  })

  it('detects competing-device writes, preserves the losing edit, and requires explicit recovery', async () => {
    const s = setup(); s.setUser('owner-a')
    await s.db.adapter.write('owner-a', data('Original'), null)
    const otherCache = recoveryCache()
    const other = createCloudAccountData({ adapter: s.db.adapter, local: s.local, recovery: otherCache.cache, currentUser: () => 'owner-a' })
    await s.coordinator.open({ user: { id: 'owner-a' } })
    await other.open({ user: { id: 'owner-a' } })
    await other.save(data('Phone edit'))
    const conflict = await s.coordinator.save(data('Desktop edit'))
    expect(conflict).toMatchObject({ phase: 'conflict', source: 'recovery', dirty: true })
    expect(s.db.rows.get('owner-a')?.data.settings.displayName).toBe('Phone edit')
    expect(s.coordinator.exportRecovery()?.settings.displayName).toBe('Desktop edit')
    await expect(s.coordinator.retry()).rejects.toThrow('changed elsewhere')
    await expect(s.coordinator.reloadCloud()).rejects.toThrow('explicitly discard')
    const cloud = await s.coordinator.reloadCloud(true)
    expect(cloud.data.settings.displayName).toBe('Phone edit')
  })

  it('does not activate a load that completes after the authenticated owner changes', async () => {
    const recovery = recoveryCache()
    let user: string | undefined = 'owner-a'
    let resolve!: (row: AccountRow | null) => void
    let markStarted!: () => void
    const started = new Promise<void>(done => { markStarted = done })
    const adapter: AccountAdapter = {
      read: () => { markStarted(); return new Promise(done => { resolve = done }) },
      write: async () => { throw new Error('not used') },
    }
    const coordinator = createCloudAccountData({ adapter, local: { read: () => data('Local') }, recovery: recovery.cache, currentUser: () => user })
    const pending = coordinator.open({ user: { id: 'owner-a' } })
    await started
    user = 'owner-b'
    resolve({ user_id: 'owner-a', revision: 'revision-a', data: data('Private A') })
    await expect(pending).rejects.toThrow('account changed')
    expect(coordinator.getState()).toBeUndefined()
    expect(recovery.records.size).toBe(0)
  })

  it('never redirects queued saves into a newly authenticated owner', async () => {
    const db = accountDatabase()
    await db.adapter.write('owner-a', data('Cloud A'), null)
    await db.adapter.write('owner-b', data('Cloud B'), null)
    let user: string | undefined = 'owner-a'
    let release!: () => void
    let markStarted!: () => void
    const started = new Promise<void>(done => { markStarted = done })
    let delay = true
    const writes: string[] = []
    const adapter: AccountAdapter = {
      read: db.adapter.read,
      write(ownerId, payload, revision) {
        writes.push(ownerId)
        if (!delay) return db.adapter.write(ownerId, payload, revision)
        delay = false
        markStarted()
        return new Promise((resolve, reject) => {
          release = () => { void db.adapter.write(ownerId, payload, revision).then(resolve, reject) }
        })
      },
    }
    const coordinator = createCloudAccountData({ adapter, local: { read: () => data('Local') }, recovery: recoveryCache().cache, currentUser: () => user })
    await coordinator.open({ user: { id: 'owner-a' } })
    const first = coordinator.save(data('A first'))
    await started
    const second = coordinator.save(data('A queued'))
    user = 'owner-b'
    await coordinator.open({ user: { id: 'owner-b' } })
    release()
    await expect(first).rejects.toThrow('account changed')
    await expect(second).rejects.toThrow('account changed')
    expect(writes).toEqual(['owner-a'])
    expect(db.rows.get('owner-b')?.data.settings.displayName).toBe('Cloud B')
  })

  it('invalidates in-flight and queued saves when the same owner is reopened', async () => {
    const db = accountDatabase()
    await db.adapter.write('owner-a', data('Cloud A'), null)
    let release!: () => void
    let markStarted!: () => void
    const started = new Promise<void>(done => { markStarted = done })
    let delay = true
    const writes: string[] = []
    const adapter: AccountAdapter = {
      read: db.adapter.read,
      write(ownerId, payload, revision) {
        writes.push(ownerId)
        if (!delay) return db.adapter.write(ownerId, payload, revision)
        delay = false
        markStarted()
        return new Promise((resolve, reject) => {
          release = () => { void db.adapter.write(ownerId, payload, revision).then(resolve, reject) }
        })
      },
    }
    const coordinator = createCloudAccountData({ adapter, local: { read: () => data('Local') }, recovery: recoveryCache().cache, currentUser: () => 'owner-a' })
    await coordinator.open({ user: { id: 'owner-a' } })
    const first = coordinator.save(data('First pending'))
    await started
    const second = coordinator.save(data('Second queued'))
    const reopened = await coordinator.open({ user: { id: 'owner-a' } })
    expect(reopened.data.settings.displayName).toBe('Cloud A')
    release()
    await expect(first).rejects.toThrow('account changed')
    await expect(second).rejects.toThrow('account changed')
    expect(writes).toEqual(['owner-a'])
    expect(coordinator.getState()?.data.settings.displayName).toBe('Cloud A')
    expect(db.rows.get('owner-a')?.data.settings.displayName).toBe('First pending')
  })

  it('fails closed if an adapter returns a row for another owner', async () => {
    const recovery = recoveryCache()
    const adapter: AccountAdapter = {
      read: async () => { throw new AccountStorageError('owner-mismatch', 'wrong owner') },
      write: async (_owner, payload) => ({ user_id: 'owner-b', revision: 'wrong', data: payload }),
    }
    const coordinator = createCloudAccountData({ adapter, local: { read: () => data('Local') }, recovery: recovery.cache, currentUser: () => 'owner-a' })
    const state = await coordinator.open({ user: { id: 'owner-a' } })
    expect(state).toMatchObject({ phase: 'blocked', source: 'local', ownerId: 'owner-a' })
    expect(JSON.stringify(state)).not.toContain('owner-b')
  })
})

describe('account recovery cache', () => {
  it('rejects malformed or cross-owner values without deleting unrelated workspace storage', async () => {
    const values = new Map<string, string>()
    values.set('thoughtflow-state-v1', 'local-captures')
    const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) }
    const { createAccountRecoveryCache } = await import('./cloudAccountData')
    const cache = createAccountRecoveryCache(storage)
    cache.write({ ownerId: 'owner-a', revision: 'revision-a', data: data('Safe'), dirty: true, updatedAt: 'now' })
    expect(cache.read('owner-b')).toBeUndefined()
    expect(values.get('thoughtflow-state-v1')).toBe('local-captures')
    values.set('threadline-account-recovery-v1:owner-a', JSON.stringify({ ownerId: 'owner-b' }))
    expect(cache.read('owner-a')).toBeUndefined()
  })
})
