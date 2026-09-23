import { describe, expect, it } from 'vitest'
import {
  createCanvasFile, createFolder, deleteCanvasFile, deleteFolderTree, emptyOrganizationState, moveCanvasFile, moveFolder,
  previewCanvasDeletion, previewFolderDeletion, restoreCanvasFile, restoreFolderTree, validateOrganizationState,
} from './organization'

const at = '2026-09-23T10:00:00.000Z'

describe('nested organization state', () => {
  it('supports deep folder trees and prevents cycles and duplicate sibling names', () => {
    let state = validateOrganizationState({
      schemaVersion: 1,
      folders: Array.from({ length: 125 }, (_, index) => ({
        id: `folder-${index}`, name: `Level ${index}`, parentId: index ? `folder-${index - 1}` : null, createdAt: at, updatedAt: at,
      })),
      canvasFiles: [],
    })
    state = createFolder(state, { id: 'folder-125', name: 'Level 125', parentId: 'folder-124', at })
    expect(state.folders.at(-1)?.parentId).toBe('folder-124')
    expect(() => moveFolder(state, { folderId: 'folder-0', parentId: 'folder-125', at })).toThrow('descendants')
    expect(() => createFolder(state, { id: 'duplicate', name: '  LEVEL   125  ', parentId: 'folder-124', at })).toThrow('already exists')
    expect(validateOrganizationState(state)).toEqual(state)
  })

  it('moves canvases only into active folders', () => {
    let state = createFolder(emptyOrganizationState(), { id: 'one', name: 'One', at })
    state = createFolder(state, { id: 'two', name: 'Two', at })
    state = createCanvasFile(state, { id: 'canvas', title: 'Plan', folderId: 'one', captureIds: ['capture:a'], at })
    state = moveCanvasFile(state, { canvasId: 'canvas', folderId: 'two', at: '2026-09-23T10:01:00.000Z' })
    expect(state.canvasFiles[0].folderId).toBe('two')
    expect(() => moveCanvasFile(state, { canvasId: 'canvas', folderId: 'missing', at })).toThrow('unavailable')
    expect(() => createFolder(state, { id: 'canvas', name: 'Identity collision', at })).toThrow('unique')
  })
})

describe('confirmed recoverable deletion', () => {
  function tree() {
    let state = createFolder(emptyOrganizationState(), { id: 'root', name: 'Projects', at })
    state = createFolder(state, { id: 'child', name: 'Launch', parentId: 'root', at })
    return createCanvasFile(state, { id: 'canvas', title: 'Launch map', folderId: 'child', captureIds: ['capture:source'], at })
  }

  it('requires exact confirmation and a fresh impact preview before tombstoning a folder subtree', () => {
    let state = tree()
    const preview = previewFolderDeletion(state, 'root')
    expect(preview).toMatchObject({ folderIds: ['child', 'root'], canvasFileIds: ['canvas'], confirmationText: 'DELETE Projects' })
    expect(() => deleteFolderTree(state, { preview, confirmationText: 'delete Projects', operationId: 'delete-1', at })).toThrow('Type DELETE Projects')

    state = createCanvasFile(state, { id: 'new-canvas', title: 'Late addition', folderId: 'root', at })
    expect(() => deleteFolderTree(state, { preview, confirmationText: preview.confirmationText, operationId: 'delete-1', at })).toThrow('changed')
    const fresh = previewFolderDeletion(state, 'root')
    state = deleteFolderTree(state, { preview: fresh, confirmationText: fresh.confirmationText, operationId: 'delete-1', at })

    expect(state.folders.every(item => item.tombstone?.operationId === 'delete-1')).toBe(true)
    expect(state.canvasFiles.every(item => item.tombstone?.deletedBy === 'account-owner-confirmed')).toBe(true)
    expect(state.canvasFiles.find(item => item.id === 'canvas')?.captureIds).toEqual(['capture:source'])
    expect(() => createCanvasFile(state, { id: 'blocked', title: 'Blocked', folderId: 'root', at })).toThrow('recovery')

    state = restoreFolderTree(state, { operationId: 'delete-1', at: '2026-09-23T11:00:00.000Z' })
    expect(state.folders.every(item => !item.tombstone)).toBe(true)
    expect(state.canvasFiles.every(item => !item.tombstone)).toBe(true)
    expect(state.folders.find(item => item.id === 'child')?.parentId).toBe('root')
  })

  it('keeps deleted canvases recoverable with capture provenance intact', () => {
    let state = tree()
    const preview = previewCanvasDeletion(state, 'canvas')
    expect(() => deleteCanvasFile(state, { preview, confirmationText: '', operationId: 'canvas-delete', at })).toThrow('Type DELETE Launch map')
    state = deleteCanvasFile(state, { preview, confirmationText: preview.confirmationText, operationId: 'canvas-delete', at })
    expect(state.canvasFiles[0]).toMatchObject({ captureIds: ['capture:source'], tombstone: { rootId: 'canvas' } })
    state = restoreCanvasFile(state, { canvasId: 'canvas', at: '2026-09-23T11:00:00.000Z' })
    expect(state.canvasFiles[0].tombstone).toBeUndefined()
    expect(state.canvasFiles[0].captureIds).toEqual(['capture:source'])
  })

  it('rejects reused operation identities so one recovery cannot revive unrelated data', () => {
    let state = tree()
    const canvasPreview = previewCanvasDeletion(state, 'canvas')
    state = deleteCanvasFile(state, { preview: canvasPreview, confirmationText: canvasPreview.confirmationText, operationId: 'one-operation', at })
    const folderPreview = previewFolderDeletion(state, 'root')
    expect(() => deleteFolderTree(state, { preview: folderPreview, confirmationText: folderPreview.confirmationText, operationId: 'one-operation', at })).toThrow('new and unique')
  })

  it('allows a replacement folder name while an old folder is in recovery, then refuses an ambiguous restore', () => {
    let state = tree()
    const preview = previewFolderDeletion(state, 'root')
    state = deleteFolderTree(state, { preview, confirmationText: preview.confirmationText, operationId: 'delete-1', at })
    state = createFolder(state, { id: 'replacement', name: 'Projects', at: '2026-09-23T11:00:00.000Z' })
    expect(() => restoreFolderTree(state, { operationId: 'delete-1', at: '2026-09-23T12:00:00.000Z' })).toThrow('already exists')
    const restored = restoreFolderTree(state, { operationId: 'delete-1', parentId: 'replacement', at: '2026-09-23T12:00:00.000Z' })
    expect(restored.folders.find(item => item.id === 'root')?.parentId).toBe('replacement')
  })
})
