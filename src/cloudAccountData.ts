import type { AuthSession } from './auth'
import {
  AccountStorageError,
  isAccountStorageError,
  loadFailure,
  saveFailure,
  validateData,
  type AccountAdapter,
  type AccountData,
  type AccountRow,
} from './accountStorage'

export const recoveryRequired = 'Unsaved account changes are preserved on this device. Export them before loading a newer cloud copy, or retry after the connection recovers.'
export const conflictRequired = 'This account changed elsewhere. Your unsaved copy is preserved for export. Loading the cloud version requires an explicit recovery choice.'
export const cloudEmpty = 'This account has no cloud data yet. Importing this device is an explicit action and never deletes the local copy.'

export interface AccountRecoveryRecord {
  ownerId: string
  revision: string
  data: AccountData
  dirty: boolean
  updatedAt: string
}

export interface AccountRecoveryCache {
  read(ownerId: string): AccountRecoveryRecord | undefined
  write(record: AccountRecoveryRecord): void
}

export interface LocalAccountSource {
  read(): AccountData | Promise<AccountData>
}

export type CloudAccountPhase = 'local' | 'cloud-empty' | 'cloud' | 'offline' | 'recovery' | 'conflict' | 'blocked'
export type CloudAccountSource = 'local' | 'cloud' | 'recovery'

export interface CloudAccountState {
  phase: CloudAccountPhase
  source: CloudAccountSource
  data: AccountData
  ownerId?: string
  revision?: string
  dirty: boolean
  message?: string
}

interface CloudAccountOptions {
  adapter?: AccountAdapter
  local: LocalAccountSource
  recovery: AccountRecoveryCache
  currentUser: () => string | undefined
  now?: () => string
}

interface KeyValueStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

const recoveryPrefix = 'threadline-account-recovery-v1:'

/** A user-scoped cache for recoverability only. It never uses or replaces local workspace keys. */
export function createAccountRecoveryCache(storage: KeyValueStorage = localStorage): AccountRecoveryCache {
  const key = (ownerId: string) => `${recoveryPrefix}${encodeURIComponent(ownerId)}`
  return {
    read(ownerId) {
      try {
        const raw = storage.getItem(key(ownerId))
        if (raw === null) return undefined
        const value = JSON.parse(raw) as Partial<AccountRecoveryRecord>
        if (value.ownerId !== ownerId || typeof value.revision !== 'string' || !value.revision ||
          typeof value.dirty !== 'boolean' || typeof value.updatedAt !== 'string') return undefined
        return { ...value, data: validateData(value.data) } as AccountRecoveryRecord
      } catch { return undefined }
    },
    write(record) {
      try {
        const safe = { ...record, data: validateData(record.data) }
        storage.setItem(key(record.ownerId), JSON.stringify(safe))
      } catch { /* Cloud access must not depend on browser cache availability. */ }
    },
  }
}

function cloneState(state: CloudAccountState): CloudAccountState {
  return { ...state, data: validateData(state.data) }
}

/**
 * Selects account data by default for a signed-in user while leaving the local workspace intact.
 * Remote writes are revision guarded; failed writes are isolated in the recovery cache.
 */
export function createCloudAccountData(options: CloudAccountOptions) {
  const now = options.now ?? (() => new Date().toISOString())
  const listeners = new Set<() => void>()
  let state: CloudAccountState | undefined
  let generation = 0
  let queue = Promise.resolve()

  const enqueue = <T>(task: () => Promise<T>): Promise<T> => {
    const operation = queue.then(task)
    queue = operation.then(() => undefined, () => undefined)
    return operation
  }

  const publish = (next: CloudAccountState) => {
    state = cloneState(next)
    listeners.forEach(listener => listener())
    return cloneState(next)
  }
  const localData = async () => validateData(await options.local.read())
  const assertOwner = (ownerId: string, operation = generation) => {
    if (operation !== generation || options.currentUser() !== ownerId) {
      throw new AccountStorageError('owner-mismatch', 'The signed-in account changed. Account data was not opened or saved.')
    }
  }
  const cache = (ownerId: string, row: Pick<AccountRow, 'revision' | 'data'>, dirty: boolean) => {
    try { options.recovery.write({ ownerId, revision: row.revision, data: row.data, dirty, updatedAt: now() }) } catch { /* Best effort only. */ }
  }
  const cloudState = (ownerId: string, row: AccountRow) => {
    if (row.user_id !== ownerId) throw new AccountStorageError('owner-mismatch', 'Account ownership could not be verified.')
    cache(ownerId, row, false)
    return publish({ phase: 'cloud', source: 'cloud', ownerId, revision: row.revision, data: row.data, dirty: false })
  }
  const failedWriteState = (ownerId: string, revision: string, data: AccountData, error: unknown) => {
    cache(ownerId, { revision, data }, true)
    const conflict = isAccountStorageError(error, 'conflict')
    return publish({
      phase: conflict ? 'conflict' : 'offline',
      source: 'recovery', ownerId, revision, data, dirty: true,
      message: conflict ? conflictRequired : recoveryRequired,
    })
  }

  const open = async (session: AuthSession | null): Promise<CloudAccountState> => {
    const operation = ++generation
    const local = await localData()
    if (session === null) return publish({ phase: 'local', source: 'local', data: local, dirty: false })
    const ownerId = session.user.id.trim()
    if (!ownerId || options.currentUser() !== ownerId) {
      throw new AccountStorageError('owner-mismatch', 'The signed-in account could not be verified.')
    }
    if (!options.adapter) {
      return publish({ phase: 'blocked', source: 'local', ownerId, data: local, dirty: false, message: 'Account storage is not configured. Local data remains available.' })
    }
    let recovered: AccountRecoveryRecord | undefined
    try { recovered = options.recovery.read(ownerId) } catch { recovered = undefined }
    try {
      const row = await options.adapter.read(ownerId)
      assertOwner(ownerId, operation)
      if (!row) {
        if (recovered?.dirty) {
          return publish({ phase: 'conflict', source: 'recovery', ownerId, revision: recovered.revision, data: recovered.data, dirty: true, message: conflictRequired })
        }
        return publish({ phase: 'cloud-empty', source: 'local', ownerId, data: local, dirty: false, message: cloudEmpty })
      }
      if (recovered?.dirty) {
        const conflict = recovered.revision !== row.revision
        return publish({
          phase: conflict ? 'conflict' : 'recovery', source: 'recovery', ownerId,
          revision: recovered.revision, data: recovered.data, dirty: true,
          message: conflict ? conflictRequired : recoveryRequired,
        })
      }
      return cloudState(ownerId, row)
    } catch (error) {
      assertOwner(ownerId, operation)
      if (isAccountStorageError(error, 'owner-mismatch')) {
        return publish({ phase: 'blocked', source: 'local', ownerId, data: local, dirty: false, message: 'Account ownership could not be verified. Local data remains untouched.' })
      }
      if (recovered) {
        return publish({ phase: 'offline', source: 'recovery', ownerId, revision: recovered.revision, data: recovered.data, dirty: recovered.dirty, message: loadFailure })
      }
      return publish({ phase: 'offline', source: 'local', ownerId, data: local, dirty: false, message: loadFailure })
    }
  }

  const importLocal = (): Promise<CloudAccountState> => {
    const queuedOwnerId = state?.ownerId
    const queuedGeneration = generation
    const adapter = options.adapter
    return enqueue(async () => {
      if (!queuedOwnerId || !adapter || state?.ownerId !== queuedOwnerId || state.phase !== 'cloud-empty') {
        throw new Error('Local import is only available for an empty signed-in account.')
      }
      assertOwner(queuedOwnerId, queuedGeneration)
      const local = await localData()
      assertOwner(queuedOwnerId, queuedGeneration)
      try {
        const row = await adapter.write(queuedOwnerId, local, null)
        assertOwner(queuedOwnerId, queuedGeneration)
        return cloudState(queuedOwnerId, row)
      } catch (error) {
        assertOwner(queuedOwnerId, queuedGeneration)
        if (isAccountStorageError(error, 'conflict')) throw new Error('Local data was not imported because this account already contains cloud data. Load the cloud copy and review it first; this device’s local data is untouched.')
        throw new Error(saveFailure)
      }
    })
  }

  const save = (next: AccountData): Promise<CloudAccountState> => {
    const snapshot = validateData(next)
    const queuedOwnerId = state?.ownerId
    const queuedGeneration = generation
    const adapter = options.adapter
    return enqueue(async () => {
      if (!queuedOwnerId || !adapter) throw new Error('Account storage is not active. Local data remains the current source.')
      assertOwner(queuedOwnerId, queuedGeneration)
      if (!state?.revision || state.ownerId !== queuedOwnerId || !['cloud', 'offline', 'recovery', 'conflict'].includes(state.phase)) {
        throw new Error('Account storage is not active. Local data remains the current source.')
      }
      const ownerId = queuedOwnerId
      const revision = state.revision
      assertOwner(ownerId, queuedGeneration)
      if (state.phase !== 'cloud') {
        cache(ownerId, { revision, data: snapshot }, true)
        return publish({ ...state, source: 'recovery', data: snapshot, dirty: true })
      }
      try {
        const row = await adapter.write(ownerId, snapshot, revision)
        assertOwner(ownerId, queuedGeneration)
        return cloudState(ownerId, row)
      } catch (error) {
        assertOwner(ownerId, queuedGeneration)
        if (isAccountStorageError(error, 'owner-mismatch')) {
          cache(ownerId, { revision, data: snapshot }, true)
          return publish({ phase: 'blocked', source: 'recovery', ownerId, revision, data: snapshot, dirty: true, message: 'Account ownership could not be verified. Unsaved changes are preserved for export.' })
        }
        return failedWriteState(ownerId, revision, snapshot, error)
      }
    })
  }

  const retry = (): Promise<CloudAccountState> => {
    const queuedOwnerId = state?.ownerId
    const queuedGeneration = generation
    const adapter = options.adapter
    return enqueue(async () => {
      if (!queuedOwnerId || !adapter) throw new Error('There are no recoverable account changes to retry.')
      assertOwner(queuedOwnerId, queuedGeneration)
      if (!state?.revision || state.ownerId !== queuedOwnerId || state.source !== 'recovery' || !state.dirty) {
        throw new Error('There are no recoverable account changes to retry.')
      }
      if (state.phase === 'conflict') throw new Error(conflictRequired)
      const revision = state.revision
      const data = validateData(state.data)
      try {
        const row = await adapter.write(queuedOwnerId, data, revision)
        assertOwner(queuedOwnerId, queuedGeneration)
        return cloudState(queuedOwnerId, row)
      } catch (error) {
        assertOwner(queuedOwnerId, queuedGeneration)
        if (isAccountStorageError(error, 'owner-mismatch')) {
          cache(queuedOwnerId, { revision, data }, true)
          return publish({ phase: 'blocked', source: 'recovery', ownerId: queuedOwnerId, revision, data, dirty: true, message: 'Account ownership could not be verified. Unsaved changes are preserved for export.' })
        }
        return failedWriteState(queuedOwnerId, revision, data, error)
      }
    })
  }

  const reloadCloud = async (discardRecovery = false): Promise<CloudAccountState> => {
    if (!state?.ownerId || !options.adapter) throw new Error('No signed-in account is available.')
    if (state.dirty && !discardRecovery) throw new Error('Export the preserved changes, then explicitly discard them before loading the cloud version.')
    const ownerId = state.ownerId
    const operation = generation
    assertOwner(ownerId, operation)
    const row = await options.adapter.read(ownerId)
    assertOwner(ownerId, operation)
    if (row) return cloudState(ownerId, row)
    const local = await localData()
    assertOwner(ownerId, operation)
    return publish({ phase: 'cloud-empty', source: 'local', ownerId, data: local, dirty: false, message: cloudEmpty })
  }

  return {
    getState: () => state && cloneState(state),
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } },
    open,
    importLocal,
    save,
    retry,
    reloadCloud,
    exportRecovery() { return state?.dirty ? validateData(state.data) : undefined },
  }
}

export type CloudAccountData = ReturnType<typeof createCloudAccountData>
