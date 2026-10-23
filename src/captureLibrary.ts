import type { ThoughtObject } from './domain'
import { createFolder, editFolder, moveFolder, validateOrganizationState, type FolderRecord, type FolderColor } from './organization'

/** Organization only: IDs reference the compatibility capture identity, never copied source text. */
export interface CaptureLibraryState {
  folders: FolderRecord[]
  placements: { id: string; folderId: string | null }[]
  /** Capture organization, not semantic Action/Commitment completion. */
  completions?: { id: string; completed: boolean }[]
}
const tree = (library: CaptureLibraryState) => ({ schemaVersion: 1 as const, folders: library.folders, canvasFiles: [] })
const normalize = (value: string) => value.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase().replace(/[^\p{L}\p{N}\p{Extended_Pictographic}]+/gu, ' ').trim()

export function isCaptureLibrary(value: unknown, objectIds: readonly string[]): value is CaptureLibraryState {
  try {
    if (!value || typeof value !== 'object') return false
    const library = value as CaptureLibraryState
    if (Object.keys(library).some(key => !['folders', 'placements', 'completions'].includes(key)) || !Array.isArray(library.placements) || !Array.isArray(library.folders)) return false
    if (!library.folders.every(folder => typeof folder.id === 'string' &&
      (folder.parentId === null || typeof folder.parentId === 'string') && typeof folder.createdAt === 'string' && typeof folder.updatedAt === 'string')) return false
    validateOrganizationState(tree(library))
    const ids = new Set(objectIds)
    if (library.completions !== undefined && (!Array.isArray(library.completions) ||
      new Set(library.completions.map(item => item.id)).size !== library.completions.length ||
      !library.completions.every(item => Object.keys(item).every(key => ['id', 'completed'].includes(key)) &&
        typeof item.id === 'string' && ids.has(item.id) && typeof item.completed === 'boolean'))) return false
    const folderIds = new Set(library.folders.filter(folder => !folder.tombstone).map(folder => folder.id))
    return new Set(library.placements.map(item => item.id)).size === library.placements.length && library.placements.every(item =>
      Object.keys(item).every(key => ['id', 'folderId'].includes(key)) && typeof item.id === 'string' && ids.has(item.id) && (item.folderId === null || folderIds.has(item.folderId)))
  } catch { return false }
}

/** One-time compatibility view. Once saved, folder membership no longer follows semantic context edits. */
export function captureLibraryFor(objects: readonly ThoughtObject[], saved?: CaptureLibraryState): CaptureLibraryState {
  if (saved) return saved
  const library: CaptureLibraryState = { folders: [], placements: [] }
  for (const object of objects) {
    const context = object.context?.trim().toLowerCase()
    const name = context === 'personal' || context === 'home' ? 'Personal' : context === 'business' || context === 'work' ? 'Business' : undefined
    if (!name) continue
    const id = `capture-folder:${name.toLowerCase()}`
    if (!library.folders.some(folder => folder.id === id)) library.folders.push({ id, name, parentId: null, createdAt: '1970-01-01T00:00:00.000Z', updatedAt: '1970-01-01T00:00:00.000Z' })
    library.placements.push({ id: object.id, folderId: id })
  }
  return library
}

export type LibraryChange =
  | { type: 'create'; id: string; name: string; parentId: string | null; color?: FolderColor; emoji?: string }
  | { type: 'edit'; id: string; name: string; color?: FolderColor; emoji?: string }
  | { type: 'move-folder'; id: string; parentId: string | null }
  | { type: 'move-capture'; id: string; folderId: string | null }
  | { type: 'complete-capture'; id: string; completed: boolean }

export function changeCaptureLibrary(library: CaptureLibraryState, objects: readonly ThoughtObject[], change: LibraryChange, at = new Date().toISOString()): CaptureLibraryState {
  const ids = objects.map(object => object.id)
  if (!isCaptureLibrary(library, ids)) throw Error('Folder data is invalid. No changes were made.')
  let next: CaptureLibraryState
  switch (change.type) {
    case 'create': {
      const created = createFolder(tree(library), { ...change, at })
      next = { ...library, folders: editFolder(created, { ...change, folderId: change.id, at }).folders }
      break
    }
    case 'edit': next = { ...library, folders: editFolder(tree(library), { ...change, folderId: change.id, at }).folders }; break
    case 'move-folder': next = { ...library, folders: moveFolder(tree(library), { folderId: change.id, parentId: change.parentId, at }).folders }; break
    case 'move-capture': next = { ...library, placements: [...library.placements.filter(item => item.id !== change.id), { id: change.id, folderId: change.folderId }] }; break
    case 'complete-capture': next = { ...library, completions: [...(library.completions ?? []).filter(item => item.id !== change.id), { id: change.id, completed: change.completed }] }; break
  }
  if (!isCaptureLibrary(next, ids)) throw Error('The destination or capture is no longer available. No changes were made.')
  return next
}

export function folderTrail(library: CaptureLibraryState, id: string | null): FolderRecord[] {
  const trail: FolderRecord[] = []
  const seen = new Set<string>()
  while (id) {
    if (seen.has(id)) break
    seen.add(id)
    const folder = library.folders.find(folder => folder.id === id && !folder.tombstone)
    if (!folder) break
    trail.unshift(folder)
    id = folder.parentId
  }
  return trail
}

export function folderDestinations(library: CaptureLibraryState, movingFolderId?: string): FolderRecord[] {
  return library.folders.filter(folder => !folder.tombstone && !folderTrail(library, folder.id).some(parent => parent.id === movingFolderId))
    .sort((a, b) => folderTrail(library, a.id).map(f => f.name).join('/').localeCompare(folderTrail(library, b.id).map(f => f.name).join('/')))
}

export function captureFolderId(library: CaptureLibraryState, id: string): string | null {
  return library.placements.find(item => item.id === id)?.folderId ?? null
}

export type CaptureCompletionFilter = 'all' | 'open' | 'completed'
export function isCaptureCompleted(library: CaptureLibraryState, object: ThoughtObject): boolean {
  return library.completions?.find(item => item.id === object.id)?.completed ?? object.status === 'complete'
}
export function filterCaptureCompletion(objects: readonly ThoughtObject[], library: CaptureLibraryState, filter: CaptureCompletionFilter): ThoughtObject[] {
  return objects.filter(object => filter === 'all' || isCaptureCompleted(library, object) === (filter === 'completed'))
}

/** All lifecycle states are searchable; source evidence and corrected text both remain discoverable. */
export function searchCaptures(objects: readonly ThoughtObject[], query: string, library: CaptureLibraryState): ThoughtObject[] {
  const tokens = normalize(query).split(' ').filter(Boolean)
  if (query.trim() && !tokens.length) return objects.filter(object => [object.originalContent, object.currentContent, object.interpretation.summary].some(text => text?.includes(query.trim())))
  return objects.filter(object => {
    const content = normalize([object.originalContent, object.currentContent, object.interpretation.summary, object.context,
      ...folderTrail(library, captureFolderId(library, object.id)).map(folder => folder.name)].filter(Boolean).join(' '))
    return tokens.every(token => content.includes(token))
  }).sort((a, b) => b.createdAt.localeCompare(a.createdAt) || a.id.localeCompare(b.id))
}
