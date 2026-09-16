import { DIGEST_DELIVERY_KEY } from './digestDelivery'
import { migrateLegacyState } from './migration'

export const MOBILE_INSTALL_KEY = 'threadline-mobile-install-v1'

/** Installation is manual; standalone only describes this window, not other installs. */
export function shouldShowMobileInstall(storage: Pick<Storage, 'getItem'>, mobile: boolean, standalone: boolean): boolean {
  if (!mobile || standalone) return false
  try { return storage.getItem(MOBILE_INSTALL_KEY) !== 'dismissed' }
  catch { return true } // Help remains available when browser storage is blocked.
}

export function dismissMobileInstall(storage: Pick<Storage, 'setItem'>) {
  storage.setItem(MOBILE_INSTALL_KEY, 'dismissed')
}

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

export function writeSettings(storage: Pick<Storage, 'setItem'>, settings: LocalSettings) {
  // A valid new object is always allowed to overwrite a corrupt or unsupported stored
  // value — that's how the settings-only recovery path lets a user save their way out.
  if (!validSettings(settings)) throw new Error('Invalid local settings.')
  storage.setItem(SETTINGS_KEY, JSON.stringify(settings))
}

/** Scoped recovery for a corrupt or unsupported stored value: resets only local settings
 *  to defaults. Leaves thoughts, canvas, digest delivery and all other app state untouched. */
export function resetSettings(storage: Pick<Storage, 'setItem'>): LocalSettings {
  const value = { ...defaultSettings }
  storage.setItem(SETTINGS_KEY, JSON.stringify(value))
  return value
}

/** Call only after a deliberate confirmation; the UI must stop active writers first. */
export function clearLocalData(storage: Pick<Storage, 'setItem' | 'removeItem'>, confirmation: string) {
  if (confirmation !== 'CLEAR') throw new Error('Type CLEAR to confirm.')
  // A valid empty document prevents the existing first-run seed from reappearing.
  storage.setItem(STATE_KEY, JSON.stringify(migrateLegacyState({ objects: [], canvas: [] })))
  storage.removeItem(DIGEST_DELIVERY_KEY)
  storage.removeItem(SETTINGS_KEY)
  storage.removeItem(MOBILE_INSTALL_KEY)
}
