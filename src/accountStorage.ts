import { serializeState } from './store'
import type { SupabaseClient } from '@supabase/supabase-js'
import type { AppState, PersistedState } from './domain'
import { isPersistedState, legacyUiProjection, reconcileLegacyUi } from './migration'
import { readSettings, type LocalSettings } from './settings'
import { readDelivery, type DigestDelivery } from './digestDelivery'
import { bankFromLegacy } from './canvasBank'
import { mergeCanvasBanks } from './canvasBankMerge'
import type { GroupingReviewState } from './groupingProposal'

export interface AccountData { model: PersistedState; settings: LocalSettings; digest: DigestDelivery }
export interface AccountRow { user_id: string; revision: string; data: AccountData }
export type AccountMergeSource = 'account' | 'device'
export interface AccountMergeChoices { settings: AccountMergeSource; digest: AccountMergeSource }
export interface AccountMergePreview {
  added: { captures: number; thoughts: number; canvases: number; events: number }
  duplicates: number
  settings: AccountMergeSource
  digest: AccountMergeSource
}
export interface AccountMergePlan {
  userId: string
  revision: string
  localFingerprint: string
  data: AccountData
  preview: AccountMergePreview
}
export interface AccountAdapter {
  read(userId: string): Promise<AccountRow | null>
  write(userId: string, data: AccountData, revision: string | null): Promise<AccountRow>
}
export type AccountStorageErrorCode = 'load-unavailable' | 'save-unavailable' | 'conflict' | 'owner-mismatch'
export class AccountStorageError extends Error {
  constructor(readonly code: AccountStorageErrorCode, message: string) {
    super(message)
    this.name = 'AccountStorageError'
  }
}
export function isAccountStorageError(error: unknown, code?: AccountStorageErrorCode): error is AccountStorageError {
  return error instanceof AccountStorageError && (code === undefined || error.code === code)
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
const accountFingerprint = (value: AccountData) => JSON.stringify(validateData(value))
export async function guardAccountMergePreview(
  local: AccountData,
  prepare: (snapshot: AccountData) => Promise<AccountMergePlan>,
  current: () => AccountData,
): Promise<AccountMergePlan> {
  const fingerprint = accountFingerprint(local)
  const plan = await prepare(local)
  if (accountFingerprint(current()) !== fingerprint) {
    throw Error('Merge preview expired because this device changed while account data was loading. Preview again; both sources are untouched.')
  }
  return plan
}
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
function mergeRecords<T extends { id: string }>(account: T[], device: T[], label: string) {
  const merged = structuredClone(account)
  let added = 0
  let duplicates = 0
  for (const record of device) {
    const existing = merged.find(item => item.id === record.id)
    if (!existing) { merged.push(structuredClone(record)); added++; continue }
    if (!equal(existing, record)) throw Error(`Merge stopped: ${label} identity ${record.id} has different contents on each device. Both sources are untouched.`)
    duplicates++
  }
  return { merged, added, duplicates }
}

/** Pure, fail-closed union. Stable identities are deduplicated only when their complete
 * records agree; Threadline never guesses that differently identified thoughts are equal. */
export function mergeAccountData(accountValue: AccountData, deviceValue: AccountData, choices: AccountMergeChoices): { data: AccountData; preview: AccountMergePreview } {
  const account = validateData(accountValue)
  const device = validateData(deviceValue)
  const captures = mergeRecords(account.model.captures, device.model.captures, 'capture')
  const interpretations = mergeRecords(account.model.interpretations, device.model.interpretations, 'interpretation')
  const sourceCorrections = mergeRecords(account.model.sourceCorrections ?? [], device.model.sourceCorrections ?? [], 'source correction')
  const semanticObjects = mergeRecords(account.model.semanticObjects, device.model.semanticObjects, 'semantic object')
  const calendarEvents = mergeRecords(account.model.calendarEvents, device.model.calendarEvents, 'calendar event')
  const relationships = mergeRecords(account.model.relationships, device.model.relationships, 'relationship')
  const canvasBank = mergeCanvasBanks(
    account.model.canvasBank ?? bankFromLegacy(account.model.canvas, account.model.canvasViewport),
    device.model.canvasBank ?? bankFromLegacy(device.model.canvas, device.model.canvasViewport),
  )
  const temporalHistory = mergeRecords(account.model.temporalHistory ?? [], device.model.temporalHistory ?? [], 'temporal decision')
  const groupingProposals = mergeRecords(account.model.groupingReview?.proposals ?? [], device.model.groupingReview?.proposals ?? [], 'grouping proposal')
  const groupingRelationships = mergeRecords(account.model.groupingReview?.relationships ?? [], device.model.groupingReview?.relationships ?? [], 'grouping relationship')
  const groupingHistory = mergeRecords(account.model.groupingReview?.history ?? [], device.model.groupingReview?.history ?? [], 'grouping decision')
  const groupingReview: GroupingReviewState | undefined = account.model.groupingReview || device.model.groupingReview ? {
    schemaVersion: 1,
    proposals: groupingProposals.merged,
    relationships: groupingRelationships.merged,
    history: groupingHistory.merged,
  } : undefined
  const legacyUiIds = [...account.model.legacyUiIds]
  for (const id of device.model.legacyUiIds) if (!legacyUiIds.includes(id)) legacyUiIds.push(id)
  const model: PersistedState = {
    schemaVersion: 2,
    captures: captures.merged,
    ...(sourceCorrections.merged.length ? { sourceCorrections: sourceCorrections.merged } : {}),
    interpretations: interpretations.merged,
    semanticObjects: semanticObjects.merged,
    calendarEvents: calendarEvents.merged,
    relationships: relationships.merged,
    legacyUiIds,
    // Frozen compatibility mirror: account remains the destination and new edits use canvasBank.
    canvas: structuredClone(account.model.canvas),
    ...(account.model.canvasViewport === undefined ? {} : { canvasViewport: structuredClone(account.model.canvasViewport) }),
    canvasBank: canvasBank.merged,
    ...(temporalHistory.merged.length ? { temporalHistory: temporalHistory.merged } : {}),
    ...(groupingReview ? { groupingReview } : {}),
  }
  const data = validateData({
    model,
    settings: choices.settings === 'account' ? account.settings : device.settings,
    digest: choices.digest === 'account' ? account.digest : device.digest,
  })
  return {
    data,
    preview: {
      added: {
        captures: captures.added,
        thoughts: device.model.legacyUiIds.filter(id => !account.model.legacyUiIds.includes(id)).length,
        canvases: canvasBank.added,
        events: calendarEvents.added,
      },
      duplicates: captures.duplicates + sourceCorrections.duplicates + interpretations.duplicates + semanticObjects.duplicates + calendarEvents.duplicates + relationships.duplicates + canvasBank.duplicates + temporalHistory.duplicates + groupingProposals.duplicates + groupingRelationships.duplicates + groupingHistory.duplicates,
      settings: choices.settings,
      digest: choices.digest,
    },
  }
}
export function createAccountAdapter(client: SupabaseClient | undefined, table: string | undefined): AccountAdapter | undefined {
  if (!client || !table || !/^[a-z][a-z0-9_]*$/.test(table)) return undefined
  function row(value: unknown, userId: string): AccountRow {
    const result = value as AccountRow
    if (!result || result.user_id !== userId || typeof result.revision !== 'string' || !result.revision) {
      throw new AccountStorageError('owner-mismatch', loadFailure)
    }
    return { ...result, data: validateData(result.data) }
  }
  return {
    async read(userId) {
      const { data, error } = await client.from(table).select('*').eq('user_id', userId).abortSignal(AbortSignal.timeout(15000)).maybeSingle()
      if (error) throw new AccountStorageError('load-unavailable', loadFailure)
      return data === null ? null : row(data, userId)
    },
    async write(userId, payload, revision) {
      const next = { user_id: userId, revision: crypto.randomUUID(), data: validateData(payload) }
      // Create-only upsert: an existing row is never replaced by a device import.
      const query = revision === null
        ? client.from(table).upsert(next, { onConflict: 'user_id', ignoreDuplicates: true })
        : client.from(table).update(next).eq('user_id', userId).eq('revision', revision)
      const { data, error } = await query.select('*').abortSignal(AbortSignal.timeout(15000)).maybeSingle()
      if (error) throw new AccountStorageError('save-unavailable', saveFailure)
      if (!data || data.revision !== next.revision) throw new AccountStorageError('conflict', saveFailure)
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
  let pendingMerge: AccountMergePlan | undefined
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
        if (local && isAccountStorageError(error, 'conflict')) {
          throw Error('Local copy was not imported because this account already contains cloud data. Load the account data instead; local data is untouched.')
        }
        throw Error(local ? 'Local copy was not imported. The account may already contain data, or storage is unavailable. Load account data instead; local data is untouched.' : loadFailure)
      }
    },
    async previewMerge(local: AccountData, choices: AccountMergeChoices): Promise<AccountMergePlan> {
      check()
      try {
        const current = await adapter.read(userId)
        check()
        if (!current) throw Error('No account data yet. Copy this device’s local data first.')
        const merged = mergeAccountData(current.data, local, choices)
        pendingMerge = { userId, revision: current.revision, localFingerprint: accountFingerprint(local), ...merged }
        return structuredClone(pendingMerge)
      } catch (error) {
        pendingMerge = undefined
        if (error instanceof Error && (error.message.startsWith('No account data') || error.message.startsWith('Merge stopped:'))) throw error
        throw Error(loadFailure)
      }
    },
    async confirmMerge(plan: AccountMergePlan, currentLocal?: AccountData) {
      check()
      if (!pendingMerge || !equal(pendingMerge, plan) || plan.userId !== userId) throw Error('Merge preview expired. Preview the latest account data again; both sources are untouched.')
      if (currentLocal && accountFingerprint(currentLocal) !== plan.localFingerprint) {
        pendingMerge = undefined
        throw Error('Merge preview expired because this device changed. Preview again; both sources are untouched.')
      }
      try {
        const result = await adapter.write(userId, plan.data, plan.revision)
        check()
        revision = result.revision; model = result.data.model; active = true; failed = false; pendingMerge = undefined
        return { state: legacyUiProjection(result.data.model), data: result.data }
      } catch {
        pendingMerge = undefined
        throw Error('Merge was not saved because the account changed or storage is unavailable. Preview again; both sources are untouched.')
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
