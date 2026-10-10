import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, CanvasElement } from './domain'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { LEGACY_CANVAS_ID } from './canvasBank'
import { resizeCanvasNode } from './canvasGeometry'
import { moveCanvasNode } from './canvasGroups'
import { createCanvasRepository } from './canvasRepository'
import { createCanvasSession } from './canvasSession'
import { panCanvasViewport, zoomCanvasViewport } from './canvasViewport'
import { legacyUiProjection } from './migration'
import { canvasObjectDraft } from './objectWorkflow'
import { defaultSettings } from './settings'
import { loadStateResult, makeObject, saveState, serializeState } from './store'

const node: CanvasElement = { id: 'source-node', type: 'text', x: 40, y: 70, width: 190, height: 100, text: 'Original canvas expression' }

function localStore(initial: unknown) {
  let raw: string | null = JSON.stringify(initial)
  vi.stubGlobal('localStorage', {
    getItem: () => raw,
    setItem: (_key: string, value: string) => { raw = value },
  })
}

function accountAdapter(): AccountAdapter {
  let row: AccountRow | null = null
  return {
    async read(ownerId) { return row?.user_id === ownerId ? structuredClone(row) : null },
    async write(ownerId, data, revision) {
      if ((row?.revision ?? null) !== revision) throw Error('Stale account revision')
      row = { user_id: ownerId, revision: `revision:${revision ?? 'first'}`, data: structuredClone(data) }
      return structuredClone(row)
    },
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('WP-07 Canvas semantic integrity', () => {
  it('keeps explicit capture evidence intact through gesture edits and local/account round trips', async () => {
    localStore({ objects: [], canvas: [node] })
    let state = loadStateResult().state
    const canvas = createCanvasRepository(LEGACY_CANVAS_ID, () => state, change => {
      state = change(state)
      expect(saveState(state)).toBeUndefined()
    })
    // Use the same explicit boundary as App's Capture node control.
    const firstDraft = canvasObjectDraft(node)
    expect(firstDraft).not.toBeNull()
    const first = makeObject(firstDraft!)
    state = { ...state, objects: [first] }
    expect(saveState(state)).toBeUndefined()
    const initial = serializeState(loadStateResult().state)
    expect(legacyUiProjection(initial).objects).toEqual(state.objects)
    const firstCapture = initial.captures.find(capture => capture.id === `capture:${first.id}`)
    expect(firstCapture).toMatchObject({ source: 'canvas', originalContent: node.text, evidence: 'text-only' })
    expect(first.status).toBe('review')

    const session = createCanvasSession(canvas)
    session.commit(moveCanvasNode(canvas.read().elements, node.id, 200, 240))
    session.commit(resizeCanvasNode(canvas.read().elements, node.id, 260, 150))
    session.setViewport(panCanvasViewport(canvas.read().viewport, { x: -50, y: 30 }))
    session.setViewport(zoomCanvasViewport(canvas.read().viewport, { x: 100, y: 120 }, 1.4))
    const afterGestures = serializeState(loadStateResult().state)
    expect(afterGestures.captures).toEqual(initial.captures)
    expect(afterGestures.interpretations).toHaveLength(initial.interpretations.length)
    expect(afterGestures.semanticObjects).toEqual(initial.semanticObjects)
    expect(afterGestures.reminderInstructions).toEqual(initial.reminderInstructions)
    expect(afterGestures.stagedActions).toEqual(initial.stagedActions)
    expect(afterGestures.calendarEvents).toEqual(initial.calendarEvents)
    expect(afterGestures.canvasBank?.canvases.find(record => record.id === LEGACY_CANVAS_ID)?.elements.find(item => item.id === node.id)).toMatchObject({ x: 200, y: 240, width: 260, height: 150 })

    // A later expression change needs another deliberate capture; it cannot rewrite the first.
    session.editText(node.id, 'Revised canvas expression')
    session.finishText()
    expect(serializeState(state).captures).toEqual(initial.captures)
    const currentNode = canvas.read().elements.find(item => item.id === node.id)!
    const laterDraft = canvasObjectDraft(currentNode)
    expect(laterDraft).not.toBeNull()
    const later = makeObject(laterDraft!)
    state = { ...state, objects: [later, ...state.objects] }
    expect(saveState(state)).toBeUndefined()
    const finalModel = serializeState(state)
    expect(finalModel.captures.find(capture => capture.id === firstCapture?.id)).toEqual(firstCapture)
    expect(finalModel.captures.find(capture => capture.id === `capture:${later.id}`)).toMatchObject({
      source: 'canvas', originalContent: currentNode.text, evidence: 'text-only',
    })
    expect(finalModel.semanticObjects).toEqual(initial.semanticObjects)
    expect(finalModel.reminderInstructions).toEqual(initial.reminderInstructions)

    // Reloading the device and opening the same account on another device retain both sources.
    expect(serializeState(loadStateResult().state).captures).toEqual(finalModel.captures)
    const adapter = accountAdapter()
    const source: AppState = legacyUiProjection(finalModel)
    const desktop = createAccountSession(adapter, 'owner', () => 'owner')
    await desktop.open(accountData(source, defaultSettings, { enabled: false }))
    const phone = createAccountSession(adapter, 'owner', () => 'owner')
    const reopened = await phone.open()
    expect(reopened.data.model.captures).toEqual(finalModel.captures)
    expect(reopened.data.model.interpretations).toEqual(finalModel.interpretations)
    expect(reopened.data.model.canvasBank).toEqual(finalModel.canvasBank)
    expect(serializeState(reopened.state).captures).toEqual(finalModel.captures)
  })
})
