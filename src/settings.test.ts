import { describe, expect, it, vi } from 'vitest'
import { clearLocalData, dismissMobileInstall, shouldShowMobileInstall, MOBILE_INSTALL_KEY, defaultSettings, readSettings, resetSettings, SETTINGS_KEY, writeSettings } from './settings'
import { DIGEST_DELIVERY_KEY } from './digestDelivery'
import { isPersistedState, legacyUiProjection } from './migration'

const corruptSettingsRaw = ['{', 'null', '[]', '{}', '{"version":2,"displayName":"","startPage":"today"}',
  JSON.stringify({ ...defaultSettings, startPage: 'unknown' }),
  JSON.stringify({ ...defaultSettings, displayName: 4 }),
  JSON.stringify({ ...defaultSettings, displayName: 'x'.repeat(81) }),
  JSON.stringify({ ...defaultSettings, displayName: ' padded ' }),
  JSON.stringify({ ...defaultSettings, unexpected: true }),
]

function storage() {
  const data = new Map<string, string>()
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: vi.fn((key: string, value: string) => { data.set(key, value) }),
    removeItem: vi.fn((key: string) => { data.delete(key) }),
  }
}

describe('local settings', () => {
  it('defaults without writing and returns independent defaults', () => {
    const store = storage()
    const first = readSettings(store)
    first.displayName = 'Changed'
    expect(readSettings(store)).toEqual(defaultSettings)
    expect(store.setItem).not.toHaveBeenCalled()
  })
  it('persists the local label and start page across reads', () => {
    const store = storage()
    const settings = { ...defaultSettings, displayName: 'My space', startPage: 'canvas' as const }
    writeSettings(store, settings)
    expect(readSettings(store)).toEqual(settings)
  })
  it.each(corruptSettingsRaw)('read rejects corrupt or unsupported settings and leaves them untouched: %s', raw => {
    const store = storage()
    store.setItem(SETTINGS_KEY, raw)
    expect(() => readSettings(store)).toThrow()
    expect(store.getItem(SETTINGS_KEY)).toBe(raw)
  })
  it.each(corruptSettingsRaw)('a valid new settings object overwrites corrupt or unsupported stored settings: %s', raw => {
    const store = storage()
    store.setItem(SETTINGS_KEY, raw)
    const settings = { ...defaultSettings, displayName: 'Recovered' }
    writeSettings(store, settings)
    expect(readSettings(store)).toEqual(settings)
  })
  it.each(corruptSettingsRaw)('an invalid new settings object never overwrites corrupt or unsupported stored settings: %s', raw => {
    const store = storage()
    store.setItem(SETTINGS_KEY, raw)
    expect(() => writeSettings(store, { ...defaultSettings, displayName: 'x'.repeat(81) })).toThrow()
    expect(store.getItem(SETTINGS_KEY)).toBe(raw)
  })
  it('rejects invalid writes and surfaces read and quota failures', () => {
    const store = storage()
    expect(() => writeSettings(store, { ...defaultSettings, displayName: 'x'.repeat(81) })).toThrow()
    expect(store.setItem).not.toHaveBeenCalled()
    expect(() => readSettings({ getItem: () => { throw Error('blocked') } })).toThrow('blocked')
    store.setItem.mockImplementation(() => { throw Error('quota') })
    expect(() => writeSettings(store, defaultSettings)).toThrow('quota')
    expect(store.getItem(SETTINGS_KEY)).toBeNull()
  })
})

describe('settings-only recovery', () => {
  it.each(corruptSettingsRaw)('resets only settings to defaults, leaving corrupt value replaced: %s', raw => {
    const store = storage()
    store.setItem(SETTINGS_KEY, raw)
    const value = resetSettings(store)
    expect(value).toEqual(defaultSettings)
    expect(readSettings(store)).toEqual(defaultSettings)
  })
  it('does not touch thoughts, canvas, digest or other app state', () => {
    const store = storage()
    store.setItem(SETTINGS_KEY, '{')
    store.setItem('thoughtflow-state-v1', 'thoughts and canvas')
    store.setItem(DIGEST_DELIVERY_KEY, 'digest')
    store.setItem('unrelated', 'keep')
    resetSettings(store)
    expect(store.getItem('thoughtflow-state-v1')).toBe('thoughts and canvas')
    expect(store.getItem(DIGEST_DELIVERY_KEY)).toBe('digest')
    expect(store.getItem('unrelated')).toBe('keep')
  })
  it('surfaces quota failures without pretending the reset succeeded', () => {
    const store = storage()
    store.setItem(SETTINGS_KEY, '{')
    store.setItem.mockImplementation(() => { throw Error('quota') })
    expect(() => resetSettings(store)).toThrow('quota')
  })
})

describe('deliberate local deletion', () => {
  it('requires the exact confirmation without changing anything', () => {
    const store = storage()
    for (const value of ['', 'clear', 'CLEAR ']) expect(() => clearLocalData(store, value)).toThrow()
    expect(store.setItem).not.toHaveBeenCalled()
    expect(store.removeItem).not.toHaveBeenCalled()
  })
  it('clears only Threadline data and persists a valid empty document without seed data', () => {
    const store = storage()
    store.setItem('thoughtflow-state-v1', 'old thoughts')
    store.setItem(SETTINGS_KEY, 'profile')
    store.setItem(DIGEST_DELIVERY_KEY, 'digest')
    store.setItem('unrelated', 'keep')
    clearLocalData(store, 'CLEAR')
    const model = JSON.parse(store.getItem('thoughtflow-state-v1')!)
    expect(isPersistedState(model)).toBe(true)
    expect(legacyUiProjection(model)).toMatchObject({ objects: [], canvas: [] })
    expect(model.captures).toEqual([])
    expect(model.interpretations).toEqual([])
    expect(store.getItem(SETTINGS_KEY)).toBeNull()
    expect(store.getItem(DIGEST_DELIVERY_KEY)).toBeNull()
    expect(store.getItem('unrelated')).toBe('keep')
  })
  it('surfaces failures and supports retry after a partial clear', () => {
    const store = storage()
    store.setItem(SETTINGS_KEY, 'profile')
    store.removeItem.mockImplementationOnce(() => { throw Error('blocked') })
    expect(() => clearLocalData(store, 'CLEAR')).toThrow('blocked')
    expect(store.getItem(SETTINGS_KEY)).toBe('profile')
    clearLocalData(store, 'CLEAR')
    expect(store.getItem(SETTINGS_KEY)).toBeNull()
    store.setItem.mockImplementation(() => { throw Error('quota') })
    expect(() => clearLocalData(store, 'CLEAR')).toThrow('quota')
  })
})


describe('mobile install guidance', () => {
  it('shows on a first mobile browser visit without writing data', () => {
    const store = storage()
    expect(shouldShowMobileInstall(store, true, false)).toBe(true)
    expect(store.setItem).not.toHaveBeenCalled()
  })
  it('does not automatically show on desktop or in a home-screen window', () => {
    const store = storage()
    expect(shouldShowMobileInstall(store, false, false)).toBe(false)
    expect(shouldShowMobileInstall(store, true, true)).toBe(false)
    expect(shouldShowMobileInstall(store, false, true)).toBe(false)
  })
  it('remembers dismissal across reads without modifying profile or thoughts', () => {
    const store = storage()
    writeSettings(store, { ...defaultSettings, displayName: 'Keep me' })
    store.setItem('thoughtflow-state-v1', 'preserved thoughts')
    dismissMobileInstall(store)
    expect(shouldShowMobileInstall(store, true, false)).toBe(false)
    expect(readSettings(store).displayName).toBe('Keep me')
    expect(store.getItem('thoughtflow-state-v1')).toBe('preserved thoughts')
    resetSettings(store)
    expect(shouldShowMobileInstall(store, true, false)).toBe(false)
  })
  it('offers help for an unknown preference and when storage cannot be read', () => {
    const store = storage()
    store.setItem(MOBILE_INSTALL_KEY, 'invalid')
    expect(shouldShowMobileInstall(store, true, false)).toBe(true)
    expect(store.getItem(MOBILE_INSTALL_KEY)).toBe('invalid')
    expect(shouldShowMobileInstall({ getItem: () => { throw Error('blocked') } }, true, false)).toBe(true)
  })
  it('surfaces failed dismissal writes instead of claiming persistence', () => {
    const store = storage()
    store.setItem.mockImplementation(() => { throw Error('quota') })
    expect(() => dismissMobileInstall(store)).toThrow('quota')
    expect(shouldShowMobileInstall(store, true, false)).toBe(true)
  })
  it('clears dismissal only with confirmed local data deletion', () => {
    const store = storage()
    dismissMobileInstall(store)
    expect(() => clearLocalData(store, '')).toThrow()
    expect(shouldShowMobileInstall(store, true, false)).toBe(false)
    clearLocalData(store, 'CLEAR')
    expect(store.getItem(MOBILE_INSTALL_KEY)).toBeNull()
    expect(shouldShowMobileInstall(store, true, false)).toBe(true)
  })
})
