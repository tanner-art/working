export type OrganizationTombstone = {
  operationId: string
  deletedAt: string
  deletedBy: 'account-owner-confirmed'
  rootId: string
}

export interface FolderRecord {
  id: string
  name: string
  parentId: string | null
  createdAt: string
  updatedAt: string
  tombstone?: OrganizationTombstone
}

/** Metadata for a saved canvas. Canvas content and immutable capture evidence remain in their own stores. */
export interface CanvasFileRecord {
  id: string
  title: string
  folderId: string | null
  createdAt: string
  updatedAt: string
  captureIds: string[]
  tombstone?: OrganizationTombstone
}

export interface OrganizationState {
  schemaVersion: 1
  folders: FolderRecord[]
  canvasFiles: CanvasFileRecord[]
}

export interface FolderDeletionPreview {
  kind: 'folder-tree'
  targetId: string
  targetName: string
  folderIds: string[]
  canvasFileIds: string[]
  confirmationText: string
}

export interface CanvasDeletionPreview {
  kind: 'canvas-file'
  targetId: string
  targetTitle: string
  confirmationText: string
}

export const emptyOrganizationState = (): OrganizationState => ({ schemaVersion: 1, folders: [], canvasFiles: [] })

const validDate = (value: string) => Number.isFinite(Date.parse(value))
const normalizedName = (value: string) => value.trim().replace(/\s+/g, ' ')
const nameKey = (value: string) => normalizedName(value).toLocaleLowerCase()
const unique = (values: string[]) => values.every(Boolean) && new Set(values).size === values.length
const exactKeys = (value: object, keys: string[]) => Object.keys(value).every(key => keys.includes(key))

function requireDate(value: string) {
  if (!validDate(value)) throw Error('A valid timestamp is required.')
}

function activeFolder(state: OrganizationState, id: string): FolderRecord {
  const folder = state.folders.find(item => item.id === id && !item.tombstone)
  if (!folder) throw Error('The folder is unavailable or in recovery.')
  return folder
}

function ensureSiblingNameAvailable(state: OrganizationState, name: string, parentId: string | null, exceptId?: string) {
  if (state.folders.some(folder => !folder.tombstone && folder.id !== exceptId && folder.parentId === parentId && nameKey(folder.name) === nameKey(name))) {
    throw Error('A folder with this name already exists here.')
  }
}

function descendants(state: OrganizationState, rootId: string): string[] {
  const found = new Set([rootId])
  let changed = true
  while (changed) {
    changed = false
    for (const folder of state.folders) {
      if (!folder.tombstone && folder.parentId && found.has(folder.parentId) && !found.has(folder.id)) {
        found.add(folder.id)
        changed = true
      }
    }
  }
  return [...found].sort()
}

export function validateOrganizationState(value: unknown): OrganizationState {
  if (!value || typeof value !== 'object') throw Error('Organization data is invalid.')
  const state = value as OrganizationState
  if (!exactKeys(state, ['schemaVersion', 'folders', 'canvasFiles']) || state.schemaVersion !== 1 ||
      !Array.isArray(state.folders) || !Array.isArray(state.canvasFiles) ||
      !unique([...state.folders, ...state.canvasFiles].map(item => item.id))) throw Error('Organization data is invalid.')
  const folderIds = new Set(state.folders.map(item => item.id))
  const folderById = new Map(state.folders.map(item => [item.id, item]))
  const activeSiblingNames = new Set<string>()
  const validTombstone = (value: OrganizationTombstone | undefined) => !value ||
    Boolean(exactKeys(value, ['operationId', 'deletedAt', 'deletedBy', 'rootId']) && value.operationId && validDate(value.deletedAt) && value.deletedBy === 'account-owner-confirmed' && value.rootId)
  for (const folder of state.folders) {
    if (!exactKeys(folder, ['id', 'name', 'parentId', 'createdAt', 'updatedAt', 'tombstone']) ||
        !folder.id || normalizedName(folder.name) !== folder.name || !folder.name || folder.name.length > 120 ||
        !validDate(folder.createdAt) || !validDate(folder.updatedAt) || (folder.parentId !== null && !folderIds.has(folder.parentId)) ||
        !validTombstone(folder.tombstone)) throw Error('Organization data is invalid.')
    if (!folder.tombstone) {
      const siblingKey = `${folder.parentId ?? '<root>'}\u0000${nameKey(folder.name)}`
      if (activeSiblingNames.has(siblingKey)) throw Error('A folder with this name already exists here.')
      activeSiblingNames.add(siblingKey)
    }
  }
  for (const folder of state.folders) {
    const seen = new Set([folder.id])
    let parentId = folder.parentId
    while (parentId) {
      if (seen.has(parentId)) throw Error('Folders cannot contain themselves.')
      seen.add(parentId)
      parentId = folderById.get(parentId)?.parentId ?? null
    }
    if (!folder.tombstone && folder.parentId && folderById.get(folder.parentId)?.tombstone) {
      throw Error('An active folder cannot be inside a deleted folder.')
    }
  }
  for (const file of state.canvasFiles) {
    if (!exactKeys(file, ['id', 'title', 'folderId', 'createdAt', 'updatedAt', 'captureIds', 'tombstone']) ||
        !file.id || normalizedName(file.title) !== file.title || !file.title || file.title.length > 160 ||
        !validDate(file.createdAt) || !validDate(file.updatedAt) || !unique(file.captureIds) ||
        (file.folderId !== null && !folderIds.has(file.folderId)) || !validTombstone(file.tombstone)) throw Error('Organization data is invalid.')
    if (!file.tombstone && file.folderId && folderById.get(file.folderId)?.tombstone) {
      throw Error('An active canvas cannot be inside a deleted folder.')
    }
  }
  const deleted = [...state.folders, ...state.canvasFiles].filter(item => item.tombstone)
  for (const operationId of new Set(deleted.map(item => item.tombstone!.operationId))) {
    const entries = deleted.filter(item => item.tombstone!.operationId === operationId)
    const rootIds = new Set(entries.map(item => item.tombstone!.rootId))
    if (rootIds.size !== 1) throw Error('Organization recovery provenance is invalid.')
    const rootId = [...rootIds][0]
    const rootIsDeletedFolder = state.folders.some(item => item.id === rootId && item.tombstone?.operationId === operationId)
    const rootIsOnlyCanvas = entries.length === 1 && state.canvasFiles.some(item => item.id === rootId && item.tombstone?.operationId === operationId)
    if (!rootIsDeletedFolder && !rootIsOnlyCanvas) throw Error('Organization recovery provenance is invalid.')
    if (rootIsDeletedFolder) {
      const deletedFolderIds = new Set(state.folders.filter(item => item.tombstone?.operationId === operationId).map(item => item.id))
      for (const folder of state.folders.filter(item => item.tombstone?.operationId === operationId)) {
        let cursor: string | null = folder.id
        while (cursor !== null && cursor !== rootId) cursor = folderById.get(cursor)?.parentId ?? null
        if (cursor !== rootId) throw Error('Organization recovery provenance is invalid.')
      }
      if (state.canvasFiles.some(item => item.tombstone?.operationId === operationId &&
        (item.folderId === null || !deletedFolderIds.has(item.folderId)))) throw Error('Organization recovery provenance is invalid.')
    }
  }
  return structuredClone(state)
}

function requireUnusedOperation(state: OrganizationState, operationId: string) {
  if (!operationId || [...state.folders, ...state.canvasFiles].some(item => item.tombstone?.operationId === operationId)) {
    throw Error('Deletion operation identity must be new and unique.')
  }
}

export function createFolder(state: OrganizationState, input: { id: string; name: string; parentId?: string | null; at: string }): OrganizationState {
  const current = validateOrganizationState(state)
  const name = normalizedName(input.name)
  const parentId = input.parentId ?? null
  requireDate(input.at)
  if (!input.id || [...current.folders, ...current.canvasFiles].some(item => item.id === input.id)) throw Error('Folder identity must be unique.')
  if (!name || name.length > 120) throw Error('Folder name must be between 1 and 120 characters.')
  if (parentId) activeFolder(current, parentId)
  ensureSiblingNameAvailable(current, name, parentId)
  return validateOrganizationState({ ...current, folders: [...current.folders, { id: input.id, name, parentId, createdAt: input.at, updatedAt: input.at }] })
}

export function moveFolder(state: OrganizationState, input: { folderId: string; parentId: string | null; at: string }): OrganizationState {
  const current = validateOrganizationState(state)
  const folder = activeFolder(current, input.folderId)
  requireDate(input.at)
  if (input.parentId) activeFolder(current, input.parentId)
  if (input.parentId === folder.id || (input.parentId && descendants(current, folder.id).includes(input.parentId))) {
    throw Error('A folder cannot be moved into itself or one of its descendants.')
  }
  ensureSiblingNameAvailable(current, folder.name, input.parentId, folder.id)
  return validateOrganizationState({ ...current, folders: current.folders.map(item => item.id === folder.id ? { ...item, parentId: input.parentId, updatedAt: input.at } : item) })
}

export function createCanvasFile(state: OrganizationState, input: { id: string; title: string; folderId?: string | null; captureIds?: string[]; at: string }): OrganizationState {
  const current = validateOrganizationState(state)
  const title = normalizedName(input.title)
  const folderId = input.folderId ?? null
  requireDate(input.at)
  if (!input.id || [...current.folders, ...current.canvasFiles].some(item => item.id === input.id)) throw Error('Canvas identity must be unique.')
  if (!title || title.length > 160) throw Error('Canvas title must be between 1 and 160 characters.')
  if (folderId) activeFolder(current, folderId)
  const captureIds = [...(input.captureIds ?? [])]
  if (!unique(captureIds)) throw Error('Canvas provenance must contain unique capture identities.')
  return validateOrganizationState({ ...current, canvasFiles: [...current.canvasFiles, { id: input.id, title, folderId, captureIds, createdAt: input.at, updatedAt: input.at }] })
}

export function moveCanvasFile(state: OrganizationState, input: { canvasId: string; folderId: string | null; at: string }): OrganizationState {
  const current = validateOrganizationState(state)
  const file = current.canvasFiles.find(item => item.id === input.canvasId && !item.tombstone)
  if (!file) throw Error('The canvas is unavailable or in recovery.')
  requireDate(input.at)
  if (input.folderId) activeFolder(current, input.folderId)
  return validateOrganizationState({ ...current, canvasFiles: current.canvasFiles.map(item => item.id === file.id ? { ...item, folderId: input.folderId, updatedAt: input.at } : item) })
}

export function previewFolderDeletion(state: OrganizationState, folderId: string): FolderDeletionPreview {
  const current = validateOrganizationState(state)
  const folder = activeFolder(current, folderId)
  const folderIds = descendants(current, folderId)
  return {
    kind: 'folder-tree', targetId: folder.id, targetName: folder.name, folderIds,
    canvasFileIds: current.canvasFiles.filter(item => !item.tombstone && item.folderId !== null && folderIds.includes(item.folderId)).map(item => item.id).sort(),
    confirmationText: `DELETE ${folder.name}`,
  }
}

export function deleteFolderTree(state: OrganizationState, input: { preview: FolderDeletionPreview; confirmationText: string; operationId: string; at: string }): OrganizationState {
  const current = validateOrganizationState(state)
  requireDate(input.at)
  requireUnusedOperation(current, input.operationId)
  const latest = previewFolderDeletion(current, input.preview.targetId)
  if (JSON.stringify(latest) !== JSON.stringify(input.preview)) throw Error('Folder contents changed. Review the deletion again.')
  if (input.confirmationText !== latest.confirmationText) throw Error(`Type ${latest.confirmationText} to confirm.`)
  const tombstone: OrganizationTombstone = { operationId: input.operationId, deletedAt: input.at, deletedBy: 'account-owner-confirmed', rootId: latest.targetId }
  const folderSet = new Set(latest.folderIds)
  const fileSet = new Set(latest.canvasFileIds)
  return validateOrganizationState({
    ...current,
    folders: current.folders.map(item => folderSet.has(item.id) ? { ...item, updatedAt: input.at, tombstone } : item),
    canvasFiles: current.canvasFiles.map(item => fileSet.has(item.id) ? { ...item, updatedAt: input.at, tombstone } : item),
  })
}

export function restoreFolderTree(state: OrganizationState, input: { operationId: string; at: string; parentId?: string | null }): OrganizationState {
  const current = validateOrganizationState(state)
  requireDate(input.at)
  const folders = current.folders.filter(item => item.tombstone?.operationId === input.operationId)
  if (!folders.length) throw Error('No recoverable folder deletion was found.')
  const root = folders.find(item => item.id === item.tombstone?.rootId)
  if (!root) throw Error('The recovery record is incomplete.')
  const parentId = input.parentId === undefined ? root.parentId : input.parentId
  if (parentId) activeFolder(current, parentId)
  const restoredIds = new Set(folders.map(item => item.id))
  const candidate: OrganizationState = {
    ...current,
    folders: current.folders.map(item => restoredIds.has(item.id)
      ? { ...item, parentId: item.id === root.id ? parentId : item.parentId, updatedAt: input.at, tombstone: undefined }
      : item),
    canvasFiles: current.canvasFiles.map(item => item.tombstone?.operationId === input.operationId
      ? { ...item, updatedAt: input.at, tombstone: undefined }
      : item),
  }
  return validateOrganizationState(candidate)
}

export function previewCanvasDeletion(state: OrganizationState, canvasId: string): CanvasDeletionPreview {
  const current = validateOrganizationState(state)
  const file = current.canvasFiles.find(item => item.id === canvasId && !item.tombstone)
  if (!file) throw Error('The canvas is unavailable or in recovery.')
  return { kind: 'canvas-file', targetId: file.id, targetTitle: file.title, confirmationText: `DELETE ${file.title}` }
}

export function deleteCanvasFile(state: OrganizationState, input: { preview: CanvasDeletionPreview; confirmationText: string; operationId: string; at: string }): OrganizationState {
  const current = validateOrganizationState(state)
  requireDate(input.at)
  requireUnusedOperation(current, input.operationId)
  const latest = previewCanvasDeletion(current, input.preview.targetId)
  if (JSON.stringify(latest) !== JSON.stringify(input.preview)) throw Error('Canvas details changed. Review the deletion again.')
  if (input.confirmationText !== latest.confirmationText) throw Error(`Type ${latest.confirmationText} to confirm.`)
  const tombstone: OrganizationTombstone = { operationId: input.operationId, deletedAt: input.at, deletedBy: 'account-owner-confirmed', rootId: latest.targetId }
  return validateOrganizationState({ ...current, canvasFiles: current.canvasFiles.map(item => item.id === latest.targetId ? { ...item, updatedAt: input.at, tombstone } : item) })
}

export function restoreCanvasFile(state: OrganizationState, input: { canvasId: string; at: string; folderId?: string | null }): OrganizationState {
  const current = validateOrganizationState(state)
  const file = current.canvasFiles.find(item => item.id === input.canvasId && item.tombstone)
  if (!file) throw Error('No recoverable canvas deletion was found.')
  requireDate(input.at)
  const folderId = input.folderId === undefined ? file.folderId : input.folderId
  if (folderId) activeFolder(current, folderId)
  return validateOrganizationState({ ...current, canvasFiles: current.canvasFiles.map(item => item.id === file.id ? { ...item, folderId, updatedAt: input.at, tombstone: undefined } : item) })
}
