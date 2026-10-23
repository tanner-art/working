import type { AuthState } from './auth'
import { accountData, createAccountSession, isAccountStorageError, type AccountAdapter } from './accountStorage'
import { defaultSettings } from './settings'

export const BETA_SETUP_PENDING = 'threadline-beta-setup-pending-v1'

/** A fresh signed-in window may be an installed app with separate browser
 * storage. Never let an empty account fall through to the local demo seed. */
export function needsFirstAccountSetup(accountExists: boolean, storage: Pick<Storage, 'getItem'>): boolean {
  if (accountExists) return false
  try { return storage.getItem('thoughtflow-state-v1') === null } catch { return false }
}

/** Only a navigation marker; never stores email, tokens, captures or account data. */
export function betaSetupRequested(path: string, search: string, storage: Pick<Storage, 'getItem'>): boolean {
  if (path === '/beta' || new URLSearchParams(search).get('welcome') === '1') return true
  try { return storage.getItem(BETA_SETUP_PENDING) === 'pending' } catch { return false }
}

export function betaEntryVisible(input: { requested: boolean; landing: string; workspaceShown: boolean; auth: AuthState['status'] }): boolean {
  if (input.workspaceShown) return false
  return input.requested || input.landing === 'landing'
}

/** Explicit "Open Threadline" action. Read first, then insert an EMPTY account
 * only if absent. Never reads or imports the device workspace or demo seed. */
export async function openBetaAccount(adapter: AccountAdapter, userId: string, currentUser: () => string | undefined) {
  const session = createAccountSession(adapter, userId, currentUser)
  try { return { session, ...await session.open() } }
  catch (error) { if (!isAccountStorageError(error, 'empty-account')) throw error }
  try {
    return { session, ...await session.open(accountData({ objects: [], canvas: [] }, { ...defaultSettings, startPage: 'capture' }, { enabled: false })) }
  } catch {
    // Another tab/device may have created the row. Read it, never overwrite it.
    // If storage is unavailable, or identity changed, this read also fails closed.
    return { session, ...await session.open() }
  }
}

export type InstallPlatform = 'iphone' | 'android' | 'desktop'
export function installPlatform(userAgent: string, touchPoints: number): InstallPlatform {
  if (/iPad|iPhone|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && touchPoints > 1)) return 'iphone'
  return /Android/.test(userAgent) ? 'android' : 'desktop'
}
