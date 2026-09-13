import type { AppState, CanvasElement, HistoryEvent, Interpretation, ObjectKind, ObjectMetadata, ObjectStatus, Relationship, SourceType, ThoughtObject } from './domain'

const KEY = 'thoughtflow-state-v1'
const uid = () => crypto.randomUUID()
const today = new Date().toISOString().slice(0, 10)
const objectKinds: ObjectKind[] = ['idea', 'action', 'reminder', 'project', 'commitment', 'person', 'reference', 'objective']
const objectStatuses: ObjectStatus[] = ['inbox', 'review', 'confirmed', 'complete', 'archived']
const sourceTypes: SourceType[] = ['text', 'voice', 'canvas']
const relationshipTypes: Relationship['type'][] = ['belongs_to', 'relates_to', 'depends_on', 'supports']
const canvasTypes: CanvasElement['type'][] = ['text', 'container', 'arrow']
const effortValues: Required<ObjectMetadata>['effort'][] = ['small', 'medium', 'large']
const attentionValues: Required<ObjectMetadata>['attentionLoad'][] = ['low', 'medium', 'high']

const seed: AppState = {
  objects: [
    { id: 'welcome-action', kind: 'action', originalContent: 'Shape the first vertical slice', source: 'text', createdAt: new Date().toISOString(), interpretation: { summary: 'Define the MVP interaction loop', suggestedKind: 'action', rationale: 'Explicit next step' }, confidence: .94, relationships: [], history: [], status: 'confirmed', metadata: { urgency: 3, effort: 'medium', attentionLoad: 'high', strategicImportance: 5 } },
    { id: 'welcome-commitment', kind: 'commitment', originalContent: 'Product planning block', source: 'text', createdAt: new Date().toISOString(), interpretation: { summary: 'Fixed planning time', suggestedKind: 'commitment', rationale: 'Time-specific commitment', suggestedDate: today }, confidence: .96, relationships: [], history: [], status: 'confirmed', metadata: { deadline: today } }
  ],
  canvas: [
    { id: 'canvas-container', type: 'container', x: 120, y: 80, width: 480, height: 300, text: 'Explore the outcome' },
    { id: 'canvas-idea', type: 'text', x: 180, y: 180, width: 180, text: 'Thought-to-execution system' },
    { id: 'canvas-action', type: 'text', x: 410, y: 265, width: 140, text: 'First vertical slice' },
    { id: 'canvas-arrow', type: 'arrow', x: 0, y: 0, fromId: 'canvas-idea', toId: 'canvas-action' }
  ]
}

export function loadState(): AppState {
  return loadStateResult().state
}
export function loadStateResult(): { state: AppState; error?: string } {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw === null) return { state: seed }
    const saved = JSON.parse(raw)
    return isAppState(saved) ? { state: saved } : { state: seed, error: 'Saved thoughts could not be read. Your stored data has been left untouched.' }
  } catch { return { state: seed, error: 'Saved thoughts could not be read. Your stored data has been left untouched.' } }
}
export function saveState(state: AppState): string | undefined {
  if (!isAppState(state)) return 'Changes could not be saved because their format is invalid.'
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
    return undefined
  } catch {
    return 'Changes are only in this open tab. Saving failed; keep this tab open and retry or download a backup.'
  }
}
export function isAppState(value: unknown): value is AppState {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<AppState>
  return Array.isArray(candidate.objects) &&
    Array.isArray(candidate.canvas) &&
    candidate.objects.every(isThoughtObject) &&
    candidate.canvas.every(isCanvasElement)
}
export function makeObject(partial: Pick<ThoughtObject, 'kind' | 'originalContent' | 'source' | 'interpretation' | 'confidence'>): ThoughtObject {
  const now = new Date().toISOString()
  return { id: uid(), createdAt: now, context: undefined, relationships: [], history: [{ at: now, event: 'Captured' }], status: partial.confidence < .8 ? 'review' : 'confirmed', metadata: {}, ...partial }
}
export function newCanvasElement(type: CanvasElement['type'], x: number, y: number): CanvasElement {
  return { id: uid(), type, x, y, width: type === 'container' ? 320 : 190, height: type === 'container' ? 210 : undefined, text: type === 'container' ? 'Untitled group' : 'New thought' }
}

function isThoughtObject(value: unknown): value is ThoughtObject {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<ThoughtObject>
  return typeof item.id === 'string' &&
    objectKinds.includes(item.kind as ObjectKind) &&
    typeof item.originalContent === 'string' &&
    sourceTypes.includes(item.source as SourceType) &&
    typeof item.createdAt === 'string' &&
    isInterpretation(item.interpretation) &&
    typeof item.confidence === 'number' &&
    item.confidence >= 0 &&
    item.confidence <= 1 &&
    Array.isArray(item.relationships) &&
    item.relationships.every(isRelationship) &&
    Array.isArray(item.history) &&
    item.history.every(isHistoryEvent) &&
    objectStatuses.includes(item.status as ObjectStatus) &&
    isMetadata(item.metadata) &&
    (item.context === undefined || typeof item.context === 'string')
}

function isInterpretation(value: unknown): value is Interpretation {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<Interpretation>
  return typeof item.summary === 'string' &&
    objectKinds.includes(item.suggestedKind as ObjectKind) &&
    typeof item.rationale === 'string' &&
    (item.suggestedProject === undefined || typeof item.suggestedProject === 'string') &&
    (item.suggestedDate === undefined || typeof item.suggestedDate === 'string')
}

function isRelationship(value: unknown): value is Relationship {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<Relationship>
  return typeof item.targetId === 'string' && relationshipTypes.includes(item.type as Relationship['type'])
}

function isHistoryEvent(value: unknown): value is HistoryEvent {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<HistoryEvent>
  return typeof item.at === 'string' && typeof item.event === 'string'
}

function isMetadata(value: unknown): value is ObjectMetadata {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<ObjectMetadata>
  return optionalScore(item.urgency) &&
    optionalScore(item.strategicImportance) &&
    optionalScore(item.roi) &&
    (item.deadline === undefined || typeof item.deadline === 'string') &&
    (item.effort === undefined || effortValues.includes(item.effort)) &&
    (item.attentionLoad === undefined || attentionValues.includes(item.attentionLoad)) &&
    (item.resourceCost === undefined || attentionValues.includes(item.resourceCost))
}

function optionalScore(value: unknown) {
  return value === undefined || ([1, 2, 3, 4, 5] as const).includes(value as 1 | 2 | 3 | 4 | 5)
}

function isCanvasElement(value: unknown): value is CanvasElement {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<CanvasElement>
  return typeof item.id === 'string' &&
    canvasTypes.includes(item.type as CanvasElement['type']) &&
    typeof item.x === 'number' &&
    typeof item.y === 'number' &&
    (item.width === undefined || typeof item.width === 'number') &&
    (item.height === undefined || typeof item.height === 'number') &&
    (item.text === undefined || typeof item.text === 'string') &&
    (item.fromId === undefined || typeof item.fromId === 'string') &&
    (item.toId === undefined || typeof item.toId === 'string') &&
    (item.type !== 'arrow' || (typeof item.fromId === 'string' && typeof item.toId === 'string'))
}
