import type { AppState } from './domain'
import { canvasBankForState } from './canvasBank'
import { reconcileLegacyUi } from './migration'
import { searchDocumentsFromAppState, type SearchDocument, type SearchField } from './universalSearch'

export type WorkspaceNavigationRequest =
  | Readonly<{ type: 'open-search-result'; document: SearchDocument; snapshotToken: string }>
  | Readonly<{ type: 'close-surface' }>

export type WorkspaceNavigationOutcome = Readonly<{ ok: true }> | Readonly<{ ok: false; message: string }>

export type SearchDestination =
  | Readonly<{ view: 'review'; objectId: string }>
  | Readonly<{ view: 'review'; reminderId: string }>
  | Readonly<{ view: 'review'; captureId: string }>
  | Readonly<{ view: 'schedule'; actionId: string }>
  | Readonly<{ view: 'schedule'; objectId: string }>
  | Readonly<{ view: 'calendar'; objectId: string }>
  | Readonly<{ view: 'canvas'; canvasId: string }>

export type WorkspaceNavigationContext = Readonly<{
  state: AppState
  snapshotToken: string
  stateIsCurrent: boolean
  available: boolean
  accountUserId?: string
  authenticatedUserId?: string
}>

export type WorkspaceNavigationHost = Readonly<{
  close: () => void
  canOpen?: (destination: SearchDestination) => boolean
  open: (destination: SearchDestination) => void
}>

export type WorkspaceRouteContext = Readonly<{
  available: boolean
  accountUserId?: string
  authenticatedUserId?: string
  prepareCanvasExit: () => boolean
}>

/** Browser history and the Search button share one fail-closed route gate. */
export function performWorkspaceRouteTransition(
  destination: 'workspace' | 'app', context: WorkspaceRouteContext,
  host: Readonly<{ enterSurface: () => void; leaveSurface: () => void }>,
): WorkspaceNavigationOutcome {
  if (!context.available || (context.accountUserId !== undefined && context.accountUserId !== context.authenticatedUserId)) {
    return { ok: false, message: 'Account or workspace is unavailable. Navigation was not completed.' }
  }
  if (destination === 'workspace') {
    if (!context.prepareCanvasExit()) return { ok: false, message: 'Finish saving Canvas changes before leaving the Canvas.' }
    host.enterSurface()
  } else host.leaveSurface()
  return { ok: true }
}

type WorkspaceHistory = Readonly<{
  state: unknown
  back: () => void
  pushState: (data: unknown, unused: string, url: string) => void
  replaceState: (data: unknown, unused: string, url: string) => void
}>
const historyRecord = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}

/** Mark both adjacent entries in this document so Back never crosses a page load. */
export function enterWorkspaceHistory(history: WorkspaceHistory, currentUrl: string, session: string): void {
  history.replaceState({ ...historyRecord(history.state), threadlineSearchOrigin: session }, '', currentUrl)
  history.pushState({ threadlineSearchEntry: session }, '', '/search')
}

export function leaveWorkspaceHistory(history: WorkspaceHistory, path: string, session: string): void {
  if (path === '/search' && historyRecord(history.state).threadlineSearchEntry === session) history.back()
  else history.replaceState({}, '', '/')
}

const unavailable = 'This result has changed or is no longer available. Refresh Search and try again.'
const fields: SearchField[] = ['original', 'corrected-source', 'current-meaning', 'reminder-source', 'canvas-title', 'canvas-element']
const equalIds = (left: readonly string[], right: readonly string[]) => left.length === right.length && left.every((id, index) => id === right[index])
function sameDocument(left: SearchDocument, right: SearchDocument): boolean {
  return left.kind === right.kind && left.id === right.id && left.targetId === right.targetId &&
    equalIds(left.captureIds, right.captureIds) && equalIds(left.interpretationIds, right.interpretationIds) &&
    fields.every(field => (left.fields[field]?.trim() || undefined) === (right.fields[field]?.trim() || undefined))
}

/** Resolve against the current loaded workspace, never a result-list snapshot. */
export function resolveSearchDestination(state: AppState, requested: SearchDocument): SearchDestination | undefined {
  try {
    const fresh = searchDocumentsFromAppState(state).find(document => document.kind === requested?.kind && document.id === requested.id)
    if (!fresh || !sameDocument(fresh, requested)) return undefined
    const model = reconcileLegacyUi(state)
    if (fresh.kind === 'capture') {
      if (!model.captures.some(capture => capture.id === fresh.id)) return undefined
      const object = state.objects.find(item => `capture:${item.id}` === fresh.id)
      return object ? { view: 'review', objectId: object.id } : { view: 'review', captureId: fresh.id }
    }
    if (fresh.kind === 'action' || fresh.kind === 'commitment' || fresh.kind === 'idea') {
      const object = state.objects.find(item => item.id === fresh.id && item.kind === fresh.kind)
      if (!object) return undefined
      if (fresh.kind === 'action') return model.stagedActions?.some(action => action.objectId === object.id && action.status !== 'reversed')
        ? { view: 'schedule', actionId: object.id } : { view: 'schedule', objectId: object.id }
      return fresh.kind === 'commitment' ? { view: 'calendar', objectId: object.id } : { view: 'review', objectId: object.id }
    }
    if (fresh.kind === 'reminder') {
      const instruction = model.reminderInstructions?.find(item => item.id === fresh.id && item.targetId === fresh.targetId)
      if (!instruction) return undefined
      if (instruction.deliveryState === 'active') return { view: 'review', reminderId: instruction.id }
      const source = model.interpretations.find(item => item.id === instruction.sourceInterpretationId)
      const object = state.objects.find(item => item.id === source?.legacy.id)
      return object ? { view: 'review', objectId: object.id } : undefined
    }
    if (fresh.kind === 'canvas' && canvasBankForState(state).canvases.some(canvas => canvas.id === fresh.id)) {
      return { view: 'canvas', canvasId: fresh.id }
    }
  } catch { /* Invalid account/model data cannot become a navigation target. */ }
  return undefined
}

export function unavailableSearchResult(): WorkspaceNavigationOutcome { return { ok: false, message: unavailable } }

/** One checked handoff: rejected commands must never reach a host transition. */
export function performWorkspaceNavigation(
  request: WorkspaceNavigationRequest, context: WorkspaceNavigationContext, host: WorkspaceNavigationHost,
): WorkspaceNavigationOutcome {
  if (!context.available || !context.stateIsCurrent ||
      (context.accountUserId !== undefined && context.accountUserId !== context.authenticatedUserId)) return unavailableSearchResult()
  if (request.type === 'close-surface') { host.close(); return { ok: true } }
  if (request.snapshotToken !== context.snapshotToken) return unavailableSearchResult()
  const destination = resolveSearchDestination(context.state, request.document)
  if (!destination) return unavailableSearchResult()
  if (host.canOpen && !host.canOpen(destination)) return { ok: false, message: 'Finish or save the work you were editing before opening this result.' }
  host.open(destination)
  return { ok: true }
}
