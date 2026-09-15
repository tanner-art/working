import { DIGEST_DELIVERY_KEY } from './digestDelivery'
import { migrateLegacyState } from './migration'

export const SETTINGS_KEY = 'threadline-settings-v1'
// Existing application storage key; keep unrelated origin data untouched.
const STATE_KEY = 'thoughtflow-state-v1'
export interface LocalSettings {
  version: 1
  displayName: string
  startPage: 'today' | 'capture' | 'canvas'
}
export const defaultSettings: LocalSettings = { version: 1, displayName: '', startPage: 'today' }

function validSettings(value: unknown): value is LocalSettings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const item = value as LocalSettings
  return Object.keys(item).length === 3 && item.version === 1 &&
    typeof item.displayName === 'string' && item.displayName.length <= 80 &&
    item.displayName === item.displayName.trim() && ['today', 'capture', 'canvas'].includes(item.startPage)
}

export function readSettings(storage: Pick<Storage, 'getItem'>): LocalSettings {
  const raw = storage.getItem(SETTINGS_KEY)
  if (raw === null) return { ...defaultSettings }
  const value: unknown = JSON.parse(raw)
  if (!validSettings(value)) throw new Error('Local settings could not be read. Stored settings are untouched.')
  return value
}

export function writeSettings(storage: Pick<Storage, 'getItem' | 'setItem'>, settings: LocalSettings) {
  if (!validSettings(settings)) throw new Error('Invalid local settings.')
  readSettings(storage) // Never overwrite corrupt or unsupported settings.
  storage.setItem(SETTINGS_KEY, JSON.stringify(settings))
}

/** Call only after a deliberate confirmation; the UI must stop active writers first. */
export function clearLocalData(storage: Pick<Storage, 'setItem' | 'removeItem'>, confirmation: string) {
  if (confirmation !== 'CLEAR') throw new Error('Type CLEAR to confirm.')
  // A valid empty document prevents the existing first-run seed from reappearing.
  storage.setItem(STATE_KEY, JSON.stringify(migrateLegacyState({ objects: [], canvas: [] })))
  storage.removeItem(DIGEST_DELIVERY_KEY)
  storage.removeItem(SETTINGS_KEY)
}
