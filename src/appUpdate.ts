/**
 * Pure state machine for the app-shell update lifecycle.
 *
 * This module deliberately has no browser or service-worker dependencies. A
 * caller owns the actual check/apply/reload effects and must dispatch the
 * resulting events explicitly.
 */

export type AppUpdateStatus =
  | 'checking'
  | 'current'
  | 'update-available'
  | 'applying'
  | 'applied'
  | 'offline'
  | 'failed'

export interface AppUpdateState {
  status: AppUpdateStatus
  checkId: string | null
  version: string | null
  error: string | null
}

export type AppUpdateEvent =
  | { type: 'check-started'; checkId: string }
  | { type: 'check-succeeded'; checkId: string; updateAvailable: boolean; version?: string }
  | { type: 'check-failed'; checkId: string; error?: string }
  | { type: 'offline' }
  | { type: 'online' }
  | { type: 'apply-requested' }
  | { type: 'apply-succeeded' }
  | { type: 'apply-failed'; error?: string }

export interface AppUpdateView {
  canOfferReload: boolean
  guidance: string
}

export function createAppUpdateState(): AppUpdateState {
  return { status: 'current', checkId: null, version: null, error: null }
}

function isCurrentCheck(state: AppUpdateState, checkId: string): boolean {
  return state.status === 'checking' && state.checkId === checkId
}

/** Apply one explicit event without performing any side effect. */
export function transitionAppUpdate(state: AppUpdateState, event: AppUpdateEvent): AppUpdateState {
  switch (event.type) {
    case 'check-started':
      return {
        status: 'checking',
        checkId: event.checkId,
        version: null,
        error: null,
      }

    case 'check-succeeded':
      if (!isCurrentCheck(state, event.checkId)) return state
      return {
        status: event.updateAvailable ? 'update-available' : 'current',
        checkId: event.checkId,
        version: event.updateAvailable ? event.version ?? null : null,
        error: null,
      }

    case 'check-failed':
      if (!isCurrentCheck(state, event.checkId)) return state
      return {
        status: 'failed',
        checkId: event.checkId,
        version: null,
        error: event.error ?? 'Update check failed.',
      }

    case 'offline':
      return { ...state, status: 'offline', error: null }

    case 'online':
      return state.status === 'offline'
        ? { ...state, status: 'current', error: null }
        : state

    case 'apply-requested':
      return state.status === 'update-available' ? { ...state, status: 'applying', error: null } : state

    case 'apply-succeeded':
      return state.status === 'applying' ? { ...state, status: 'applied', error: null } : state

    case 'apply-failed':
      return state.status === 'applying'
        ? { ...state, status: 'failed', error: event.error ?? 'Update could not be applied.' }
        : state
  }
}

export function getAppUpdateView(state: AppUpdateState): AppUpdateView {
  switch (state.status) {
    case 'checking':
      return { canOfferReload: false, guidance: 'Checking for an update.' }
    case 'current':
      return { canOfferReload: false, guidance: 'You are using the latest version.' }
    case 'update-available':
      return { canOfferReload: false, guidance: 'An update is ready. Apply it when convenient.' }
    case 'applying':
      return { canOfferReload: false, guidance: 'Applying the update. Please wait.' }
    case 'applied':
      return { canOfferReload: true, guidance: 'The update is ready. Reload when convenient.' }
    case 'offline':
      return { canOfferReload: false, guidance: 'You are offline. The installed app can continue to work.' }
    case 'failed':
      return { canOfferReload: false, guidance: state.error ?? 'The update check failed. Try again later.' }
  }
}

export const initialAppUpdateState = createAppUpdateState()
export const appUpdateReducer = transitionAppUpdate
