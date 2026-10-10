import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppState, CanvasElement } from './domain'
import { accountData, createAccountSession, mergeAccountData, type AccountAdapter, type AccountRow } from './accountStorage'
import { scheduleStagedAction, stageAction } from './actionStaging'
import { LEGACY_CANVAS_ID } from './canvasBank'
import { resizeCanvasNode } from './canvasGeometry'
import { moveCanvasNode } from './canvasGroups'
import { createCanvasRepository } from './canvasRepository'
import { createCanvasSession } from './canvasSession'
import { panCanvasViewport, zoomCanvasViewport } from './canvasViewport'
import { legacyUiProjection } from './migration'
import { canvasObjectDraft, confirmObject, confirmedActions } from './objectWorkflow'
import { resolveReminderInState } from './reminderWorkflow'
import { defaultSettings } from './settings'
import { loadStateResult, makeObject, saveState, serializeState } from './store'

const node: CanvasElement = { id: 'source-node', type: 'text', x: 40, y: 70, width: 190, height: 100, text: 'Original canvas expression' }
const neighbor: CanvasElement = { id: 'neighbor-node', type: 'text', x: 330, y: 90, width: 160, height: 90, text: 'Visual neighbor' }

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
    localStore({ objects: [], canvas: [node, neighbor] })
    let state = loadStateResult().state
    // Use the same explicit boundary as App's Capture node control.
    const firstDraft = canvasObjectDraft(node)
    expect(firstDraft).not.toBeNull()
    const first = makeObject(firstDraft!)
    const confirmedIdea = confirmObject(first)
    const action = confirmObject({ ...makeObject({ kind: 'action', originalContent: 'Act on the canvas idea', source: 'text', confidence: .9,
      interpretation: { summary: 'Act on the canvas idea', suggestedKind: 'action', rationale: 'Explicit action' } }),
      relationships: [{ type: 'relates_to', targetId: first.id }] })
    const staged = stageAction(makeObject({ kind: 'action', originalContent: 'Schedule a separate action', source: 'text', confidence: .9,
      interpretation: { summary: 'Schedule a separate action', suggestedKind: 'action', rationale: 'Explicit staging' } }))
    const reminder = makeObject({ kind: 'reminder', originalContent: 'Remind me about the action', source: 'text', confidence: .7,
      interpretation: { summary: 'Remind me about the action', suggestedKind: 'reminder', rationale: 'Explicit reminder' } })
    state = { ...state, objects: [confirmedIdea, action, staged, reminder] }
    expect(saveState(state)).toBeUndefined()
    state = loadStateResult().state
    state = scheduleStagedAction(state, staged.id, '2026-10-11T09:00:00.000Z', 'UTC')
    state = resolveReminderInState(state, reminder.id, { targetId: action.id, mode: 'specific', dueAt: '2026-10-11T08:00:00.000Z' })
    const initial = serializeState(state)
    // A pre-existing, populated semantic graph is essential: empty comparisons
    // would not detect dropped confirmations, instructions, or temporal evidence.
    localStore(initial)
    state = loadStateResult().state
    const canvas = createCanvasRepository(LEGACY_CANVAS_ID, () => state, change => {
      state = change(state)
      expect(saveState(state)).toBeUndefined()
    })
    expect(serializeState(state)).toEqual(initial)
    expect(initial.interpretations.length).toBeGreaterThan(0)
    expect(initial.semanticObjects.length).toBeGreaterThan(0)
    expect(initial.reminderInstructions).toHaveLength(1)
    expect(initial.stagedActions).toHaveLength(1)
    expect(initial.calendarEvents).toHaveLength(1)
    expect(initial.relationships).toHaveLength(1)
    expect(initial.temporalHistory).toHaveLength(1)
    expect(initial.semanticObjects.find(item => item.id === first.id)?.status).toBe('confirmed')
    expect(initial.interpretations.find(item => item.legacy.id === action.id && item.confirmation)?.confirmation).toMatchObject({ transition: 'action' })
    expect(confirmedActions(state.objects, initial.relationships).map(item => item.id)).toEqual([action.id])
    const firstCapture = initial.captures.find(capture => capture.id === `capture:${first.id}`)
    expect(firstCapture).toMatchObject({ source: 'canvas', originalContent: node.text, evidence: 'text-only' })
    expect(first.status).toBe('review')

    const session = createCanvasSession(canvas)
    session.commit(moveCanvasNode(canvas.read().elements, node.id, 200, 240))
    session.commit(resizeCanvasNode(canvas.read().elements, node.id, 260, 150))
    session.setViewport(panCanvasViewport(canvas.read().viewport, { x: -50, y: 30 }))
    session.setViewport(zoomCanvasViewport(canvas.read().viewport, { x: 100, y: 120 }, 1.4))
    // A drawn connection is visual expression, never a semantic relationship.
    session.commit([...canvas.read().elements, { id: 'visual-link', type: 'arrow', x: 0, y: 0, fromId: node.id, toId: neighbor.id }])
    const afterGestures = serializeState(loadStateResult().state)
    expect(afterGestures.captures).toEqual(initial.captures)
    expect(afterGestures.interpretations).toEqual(initial.interpretations)
    expect(afterGestures.semanticObjects).toEqual(initial.semanticObjects)
    expect(afterGestures.reminderInstructions).toEqual(initial.reminderInstructions)
    expect(afterGestures.stagedActions).toEqual(initial.stagedActions)
    expect(afterGestures.calendarEvents).toEqual(initial.calendarEvents)
    expect(afterGestures.relationships).toEqual(initial.relationships)
    expect(afterGestures.temporalHistory).toEqual(initial.temporalHistory)
    expect(confirmedActions(legacyUiProjection(afterGestures).objects, afterGestures.relationships).map(item => item.id)).toEqual([action.id])
    expect(afterGestures.canvasBank?.canvases.find(record => record.id === LEGACY_CANVAS_ID)?.elements.find(item => item.id === node.id)).toMatchObject({ x: 200, y: 240, width: 260, height: 150 })
    expect(afterGestures.canvasBank?.canvases.find(record => record.id === LEGACY_CANVAS_ID)?.elements.some(item => item.id === 'visual-link')).toBe(true)

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
    expect(finalModel.semanticObjects.find(object => object.id === first.id)).toEqual(
      initial.semanticObjects.find(object => object.id === first.id),
    )
    expect(finalModel.semanticObjects.some(object => object.id === later.id)).toBe(true)
    expect(finalModel.reminderInstructions).toEqual(initial.reminderInstructions)
    expect(finalModel.stagedActions).toEqual(initial.stagedActions)
    expect(finalModel.calendarEvents).toEqual(initial.calendarEvents)
    expect(finalModel.relationships).toEqual(initial.relationships)
    expect(finalModel.temporalHistory).toEqual(initial.temporalHistory)
    for (const reading of initial.interpretations) expect(finalModel.interpretations.find(item => item.id === reading.id)).toEqual(reading)

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
    expect(reopened.data.model.semanticObjects).toEqual(finalModel.semanticObjects)
    expect(reopened.data.model.reminderInstructions).toEqual(finalModel.reminderInstructions)
    expect(reopened.data.model.stagedActions).toEqual(finalModel.stagedActions)
    expect(reopened.data.model.calendarEvents).toEqual(finalModel.calendarEvents)
    expect(reopened.data.model.relationships).toEqual(finalModel.relationships)
    expect(reopened.data.model.temporalHistory).toEqual(finalModel.temporalHistory)
    expect(serializeState(reopened.state)).toEqual(finalModel)
    expect(confirmedActions(reopened.state.objects, reopened.data.model.relationships).map(item => item.id)).toEqual([action.id])
    const merged = mergeAccountData(accountData(source, defaultSettings, { enabled: false }),
      accountData(source, defaultSettings, { enabled: false }), { settings: 'account', digest: 'account' }).data.model
    expect(merged).toEqual(finalModel)
    expect(confirmedActions(legacyUiProjection(merged).objects, merged.relationships).map(item => item.id)).toEqual([action.id])
  })
})
