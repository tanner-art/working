import { DEFAULT_CANVAS_VIEWPORT, isCanvasElements, isCanvasViewport } from './canvasDocument'
import type { AppState, CanvasBank, CanvasElement, CanvasRecord, CanvasViewport } from './domain'

export const LEGACY_CANVAS_ID = 'canvas:legacy'
export const LEGACY_CANVAS_TITLE = 'My first canvas'
const LEGACY_CANVAS_TIME = '1970-01-01T00:00:00.000Z'
export const DEFAULT_CANVAS_TITLE = 'Untitled canvas'

const copy = <T>(value: T): T => structuredClone(value)
const validDate = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value))

export function isCanvasRecord(value: unknown): value is CanvasRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const record = value as CanvasRecord
  return Object.keys(value).every(key => ['id', 'title', 'createdAt', 'updatedAt', 'elements', 'viewport'].includes(key)) &&
    typeof record.id === 'string' && record.id.length > 0 && record.id.length <= 160 &&
    typeof record.title === 'string' && record.title === record.title.trim() && record.title.length > 0 && record.title.length <= 120 &&
    validDate(record.createdAt) && validDate(record.updatedAt) &&
    Date.parse(record.updatedAt) >= Date.parse(record.createdAt) &&
    isCanvasElements(record.elements) && isCanvasViewport(record.viewport)
}

export function isCanvasBank(value: unknown): value is CanvasBank {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => key !== 'canvases')) return false
  const canvases = (value as CanvasBank).canvases
  return Array.isArray(canvases) && canvases.every(isCanvasRecord) && new Set(canvases.map(item => item.id)).size === canvases.length
}

export function bankFromLegacy(elements: CanvasElement[], viewport?: CanvasViewport): CanvasBank {
  const resolvedViewport = viewport ?? DEFAULT_CANVAS_VIEWPORT
  const nonTrivial = elements.length > 0 || JSON.stringify(resolvedViewport) !== JSON.stringify(DEFAULT_CANVAS_VIEWPORT)
  return { canvases: nonTrivial ? [{
    id: LEGACY_CANVAS_ID,
    title: LEGACY_CANVAS_TITLE,
    createdAt: LEGACY_CANVAS_TIME,
    updatedAt: LEGACY_CANVAS_TIME,
    elements: copy(elements),
    viewport: copy(resolvedViewport),
  }] : [] }
}

export function canvasBankForState(state: Pick<AppState, 'canvasBank' | 'canvas' | 'canvasViewport'>): CanvasBank {
  return copy(state.canvasBank ?? bankFromLegacy(state.canvas, state.canvasViewport))
}

export function createCanvasRecord(now = new Date().toISOString(), id = `canvas:${crypto.randomUUID()}`): CanvasRecord {
  return { id, title: DEFAULT_CANVAS_TITLE, createdAt: now, updatedAt: now, elements: [], viewport: copy(DEFAULT_CANVAS_VIEWPORT) }
}

export function addCanvas(state: AppState, record: CanvasRecord): AppState {
  const bank = canvasBankForState(state)
  if (!isCanvasRecord(record) || bank.canvases.some(item => item.id === record.id)) throw Error('Canvas could not be created safely.')
  return { ...state, canvasBank: { canvases: [...bank.canvases, copy(record)] } }
}

export function renameCanvas(state: AppState, id: string, title: string, updatedAt = new Date().toISOString()): AppState {
  const bank = canvasBankForState(state)
  const clean = title.trim()
  if (!clean || clean.length > 120 || !validDate(updatedAt)) throw Error('Canvas title must contain 1–120 characters.')
  let found = false
  const canvases = bank.canvases.map(item => {
    if (item.id !== id) return item
    found = true
    if (Date.parse(updatedAt) < Date.parse(item.createdAt)) throw Error('Canvas title could not be saved with an invalid edit time.')
    return { ...item, title: clean, updatedAt }
  })
  if (!found) throw Error('Canvas no longer exists. Return to the Bank and reopen it.')
  return { ...state, canvasBank: { canvases } }
}

export function listCanvases(bank: CanvasBank): CanvasRecord[] {
  return copy(bank.canvases).sort((left, right) =>
    Date.parse(right.updatedAt) - Date.parse(left.updatedAt) || left.title.localeCompare(right.title) || left.id.localeCompare(right.id))
}
