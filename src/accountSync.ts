import { createAccountSession, isAccountStorageError, type AccountAdapter, type AccountData, type AccountSession } from './accountStorage'
import type { AppState } from './domain'

export type AccountWorkspace = { session: AccountSession; state: AppState; data: AccountData }

/** Signing in reads existing account data; it never uploads the device implicitly. */
export async function openSignedInWorkspace(adapter: AccountAdapter, userId: string, currentUser: () => string | undefined): Promise<AccountWorkspace | undefined> {
  const session = createAccountSession(adapter, userId, currentUser)
  try { return { session, ...await session.open() } }
  catch (error) {
    if (isAccountStorageError(error, 'empty-account')) return undefined
    throw error
  }
}

/** Editors keep drafts, including drafts owned inside child components that the
 * workspace cannot introspect. Updates appear on the next non-editing surface. */
export function canRefreshWorkspace(input: {
  view: string; draft: string; selected: boolean; busy: boolean; saveError: boolean;
  pendingCanvas: boolean; focusedEditor: boolean; customSurface: boolean;
}) {
  return ['today', 'capture', 'digest', 'beta-home'].includes(input.view)
    && !input.draft && !input.selected && !input.busy && !input.saveError
    && !input.pendingCanvas && !input.focusedEditor && !input.customSurface
}

export function deviceOnlyCaptureCount(local: AccountData, account: AccountData): number {
  const ids = new Set(account.model.captures.map(capture => capture.id))
  return local.model.captures.filter(capture => !ids.has(capture.id)).length
}
