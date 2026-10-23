import { describe, expect, it, vi } from 'vitest'
import { BETA_SETUP_PENDING, betaEntryVisible, betaSetupRequested, installPlatform, needsFirstAccountSetup, openBetaAccount } from './betaWelcome'
import { accountData, type AccountAdapter, type AccountRow } from './accountStorage'
import { defaultSettings } from './settings'
import { makeObject } from './store'

const empty = () => accountData({ objects: [], canvas: [] }, defaultSettings, { enabled: false })
function backend() {
  let row: AccountRow | null = null
  const adapter: AccountAdapter = {
    read: vi.fn(async () => structuredClone(row)),
    write: vi.fn(async (id, data, revision) => {
      if (row || revision !== null) throw Error('conflict')
      row = { user_id: id, data: structuredClone(data), revision: 'revision-1' }
      return structuredClone(row)
    }),
  }
  return { adapter, set: (value: AccountRow) => { row = value }, row: () => row }
}
describe('beta entry routing', () => {
  it('routes a fresh authenticated root/installed window with no account row to setup, not demo data', () => {
    expect(needsFirstAccountSetup(false, { getItem: () => null })).toBe(true)
    expect(needsFirstAccountSetup(true, { getItem: () => null })).toBe(false)
    for (const local of ['{}', '{malformed', '{"objects":[],"canvas":[],"canvasBank":{"items":[{}]}}']) {
      expect(needsFirstAccountSetup(false, { getItem: () => local })).toBe(false)
    }
    expect(needsFirstAccountSetup(false, { getItem: () => { throw Error('unreadable') } })).toBe(false)
  })
  const storage = { getItem: vi.fn(() => null as string | null) }
  it('supports a shareable beta URL and a cross-browser email callback', () => {
    expect(betaSetupRequested('/beta', '', storage)).toBe(true)
    expect(betaSetupRequested('/', '?welcome=1', storage)).toBe(true)
    expect(betaSetupRequested('/', '?welcome=0', storage)).toBe(false)
  })
  it('resumes a pending signup after a reload without storing email or secrets', () => {
    expect(betaSetupRequested('/', '', { getItem: key => key === BETA_SETUP_PENDING ? 'pending' : null })).toBe(true)
    expect(betaSetupRequested('/', '', { getItem: () => { throw Error('blocked') } })).toBe(false)
  })
  it.each(['loading', 'signed-out', 'signed-in', 'error'] as const)('keeps the same entry component mounted through %s', auth => {
    expect(betaEntryVisible({ requested: true, landing: 'loading', workspaceShown: false, auth })).toBe(true)
  })
  it('does not replace an already open workspace or returning account with setup', () => {
    expect(betaEntryVisible({ requested: true, landing: 'landing', workspaceShown: true, auth: 'signed-out' })).toBe(false)
    expect(betaEntryVisible({ requested: false, landing: 'app', workspaceShown: false, auth: 'signed-in' })).toBe(false)
  })
  it('detects iPhone, iPad desktop user agent, Android and desktop', () => {
    expect(installPlatform('iPhone Safari', 5)).toBe('iphone')
    expect(installPlatform('Macintosh Safari', 5)).toBe('iphone')
    expect(installPlatform('Macintosh Safari', 0)).toBe('desktop')
    expect(installPlatform('Android Chrome', 5)).toBe('android')
  })
})
describe('explicit first account opening', () => {
  it('creates an empty synced account without importing local demo or user data', async () => {
    const db = backend()
    const storage = { getItem: vi.fn(() => '{private device work}'), setItem: vi.fn() }
    vi.stubGlobal('localStorage', storage)
    try {
      const opened = await openBetaAccount(db.adapter, 'owner', () => 'owner')
      expect(opened.state.objects).toEqual([])
      expect(opened.data.model.captures).toEqual([])
      expect(opened.state.canvas).toEqual([])
      expect(opened.data.settings.startPage).toBe('capture')
      expect(db.adapter.write).toHaveBeenCalledTimes(1)
      expect(db.adapter.write).toHaveBeenCalledWith('owner', expect.anything(), null)
      expect(storage.getItem).not.toHaveBeenCalled(); expect(storage.setItem).not.toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })
  it('opens existing account data without writing to it', async () => {
    const db = backend(); const data = empty()
    data.settings.displayName = 'Existing person'
    db.set({ user_id: 'owner', revision: 'existing', data })
    const result = await openBetaAccount(db.adapter, 'owner', () => 'owner')
    expect(result.data).toEqual(data); expect(db.adapter.write).not.toHaveBeenCalled()
  })
  it('reads the winning account if another device creates it during signup', async () => {
    const db = backend()
    const data = accountData({ objects: [makeObject({ kind: 'idea', source: 'text', originalContent: 'Keep this', confidence: .7, interpretation: { summary: 'Keep', rationale: 'Fixture', suggestedKind: 'idea' } })], canvas: [] }, defaultSettings, { enabled: false })
    vi.mocked(db.adapter.write).mockImplementationOnce(async () => {
      db.set({ user_id: 'owner', revision: 'winner', data }); throw Error('conflict')
    })
    expect((await openBetaAccount(db.adapter, 'owner', () => 'owner')).state.objects).toHaveLength(1)
    expect(db.row()!.revision).toBe('winner')
    expect(db.adapter.write).toHaveBeenCalledTimes(1)
  })
  it('does not create an account after a failed, denied or corrupt read', async () => {
    const db = backend(); vi.mocked(db.adapter.read).mockRejectedValueOnce(Error('denied'))
    await expect(openBetaAccount(db.adapter, 'owner', () => 'owner')).rejects.toThrow()
    expect(db.adapter.write).not.toHaveBeenCalled()
    db.set({ user_id: 'owner', revision: 'bad', data: {} as never })
    await expect(openBetaAccount(db.adapter, 'owner', () => 'owner')).rejects.toThrow()
    expect(db.adapter.write).not.toHaveBeenCalled()
  })
  it('cannot activate a workspace after sign-out or a different account response', async () => {
    const db = backend(); let user: string | undefined = 'owner'
    vi.mocked(db.adapter.read).mockImplementationOnce(async () => { user = undefined; return null })
    await expect(openBetaAccount(db.adapter, 'owner', () => user)).rejects.toThrow()
    expect(db.adapter.write).not.toHaveBeenCalled()
    db.set({ user_id: 'other', revision: 'wrong', data: empty() })
    await expect(openBetaAccount(db.adapter, 'owner', () => 'owner')).rejects.toThrow()
    expect(db.adapter.write).not.toHaveBeenCalled()
  })
  it('reports initialization failure instead of falling through to local-only mode', async () => {
    const db = backend(); vi.mocked(db.adapter.write).mockRejectedValueOnce(Error('offline'))
    await expect(openBetaAccount(db.adapter, 'owner', () => 'owner')).rejects.toThrow()
    expect(db.row()).toBeNull()
  })
})
