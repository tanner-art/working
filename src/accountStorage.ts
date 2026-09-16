import { serializeState } from './store'
import type { SupabaseClient } from '@supabase/supabase-js'
import type { AppState, PersistedState } from './domain'
import { isPersistedState, legacyUiProjection, reconcileLegacyUi } from './migration'
import { readSettings, type LocalSettings } from './settings'
import { readDelivery, type DigestDelivery } from './digestDelivery'

export interface AccountData { model: PersistedState; settings: LocalSettings; digest: DigestDelivery }
export interface AccountRow { user_id: string; revision: string; data: AccountData }
export interface AccountAdapter {
  read(userId: string): Promise<AccountRow | null>
  write(userId: string, data: AccountData, revision: string | null): Promise<AccountRow>
}
export const loadFailure = 'Account data could not be loaded. Check your connection, table configuration and account access (RLS), then retry. This device’s data is untouched.'
export const saveFailure = 'Account changes could not be saved. Keep this tab open and download an export. Check your connection and account access (RLS); if another device changed the account, export first, then load its latest data.'
export function accountData(state: AppState, settings: LocalSettings, digest: DigestDelivery): AccountData {
  return validateData({ model: serializeState(state), settings, digest })
}
export function validateData(value: unknown): AccountData {
  const data = value as AccountData
  if (!data || !isPersistedState(data.model)) throw Error('Invalid account data')
  // Reuse the strict local validators without accessing browser storage.
  readSettings({ getItem: () => JSON.stringify(data.settings) })
  readDelivery({ getItem: () => JSON.stringify(data.digest) })
  return structuredClone(data)
}
export function createAccountAdapter(client: SupabaseClient | undefined, table: string | undefined): AccountAdapter | undefined {
  if (!client || !table || !/^[a-z][a-z0-9_]*$/.test(table)) return undefined
  function row(value: unknown, userId: string): AccountRow {
    const result = value as AccountRow
    if (!result || result.user_id !== userId || typeof result.revision !== 'string' || !result.revision) throw Error('Invalid account row')
    return { ...result, data: validateData(result.data) }
  }
  return {
    async read(userId) {
      const { data, error } = await client.from(table).select('*').eq('user_id', userId).abortSignal(AbortSignal.timeout(15000)).maybeSingle()
      if (error) throw Error(loadFailure)
      return data === null ? null : row(data, userId)
    },
    async write(userId, payload, revision) {
      const next = { user_id: userId, revision: crypto.randomUUID(), data: validateData(payload) }
      // Create-only upsert: an existing row is never replaced by a device import.
      const query = revision === null
        ? client.from(table).upsert(next, { onConflict: 'user_id', ignoreDuplicates: true })
        : client.from(table).update(next).eq('user_id', userId).eq('revision', revision)
      const { data, error } = await query.select('*').abortSignal(AbortSignal.timeout(15000)).single()
      if (error || !data || data.revision !== next.revision) throw Error(saveFailure)
      return row(data, userId)
    },
  }
}

/** No constructor/sign-in I/O. Only explicit load/import activates account writes. */
export function createAccountSession(adapter: AccountAdapter, userId: string, currentUser: () => string | undefined) {
  let revision: string | null = null
  let model: PersistedState | undefined
  let active = false
  let failed = false
  let queue = Promise.resolve()
  const check = () => { if (currentUser() !== userId) throw Error('Account session changed. Export unsaved work, then return to local data.') }
  return {
    userId,
    snapshot(state: AppState, settings: LocalSettings, digest: DigestDelivery) {
      return accountData({ ...state, model: model ?? state.model }, settings, digest)
    },
    async open(local?: AccountData) {
      check()
      try {
        const result = local ? await adapter.write(userId, local, null) : await adapter.read(userId)
        check()
        if (!result) throw Error('No account data yet. Copy this device’s local data first.')
        revision = result.revision; model = result.data.model; active = true; failed = false
        return { state: legacyUiProjection(result.data.model), data: result.data }
      } catch (error) {
        if (error instanceof Error && error.message.startsWith('No account data')) throw error
        throw Error(local ? 'Local copy was not imported. The account may already contain data, or storage is unavailable. Load account data instead; local data is untouched.' : loadFailure)
      }
    },
    save(data: AccountData, retry = false) {
      const snapshot = validateData(data)
      const operation = queue.then(async () => {
        check()
        if (!active || (failed && !retry)) throw Error(saveFailure)
        try {
          const data = { ...snapshot, model: reconcileLegacyUi({
            ...legacyUiProjection(snapshot.model), model,
            temporalHistory: snapshot.model.temporalHistory,
          }) }
          const result = await adapter.write(userId, data, revision)
          check(); revision = result.revision; model = result.data.model; failed = false
        } catch { failed = true; throw Error(saveFailure) }
      })
      queue = operation.catch(() => {})
      return operation
    },
  }
}
export type AccountSession = ReturnType<typeof createAccountSession>
