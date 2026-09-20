import type { AppState, HistoryEvent, LegacyInterpretation, ObjectKind, ObjectMetadata, ObjectStatus, Relationship, SourceType, ThoughtObject, PersistedState } from './domain'
import { isCanvasElements, isCanvasViewport } from './canvasDocument'
export { newCanvasElement } from './canvasDocument'
import { migrateLegacyState, isPersistedState, legacyUiProjection, reconcileLegacyUi } from './migration'

const sessions = new WeakMap<PersistedState, { model: PersistedState; raw: string | null }>()
const KEY = 'thoughtflow-state-v1'
const uid = () => crypto.randomUUID()
const today = new Date().toISOString().slice(0, 10)
const objectKinds: ObjectKind[] = ['idea', 'action', 'reminder', 'project', 'commitment', 'person', 'reference', 'objective']
const objectStatuses: ObjectStatus[] = ['inbox', 'review', 'confirmed', 'complete', 'archived']
const sourceTypes: SourceType[] = ['text', 'voice', 'canvas']
const relationshipTypes: Relationship['type'][] = ['belongs_to', 'relates_to', 'depends_on', 'supports']
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
    if (raw === null) {
      const state = legacyUiProjection(migrateLegacyState(seed))
      sessions.set(state.model!, { model: structuredClone(state.model!), raw })
      return { state }
    }
    const saved = JSON.parse(raw)
    const model = isPersistedState(saved) ? saved : migrateLegacyState(saved)
    const state = legacyUiProjection(model)
    sessions.set(state.model!, { model: structuredClone(state.model!), raw })
    return { state }
  } catch { return { state: seed, error: 'Saved thoughts could not be read. Your stored data has been left untouched.' } }
}
/** Serialize against the last saved evidence, including revisions added in this session. */
export function serializeState(state: AppState): PersistedState {
  const session = state.model && sessions.get(state.model)
  return reconcileLegacyUi({ ...state, model: session?.model ?? state.model })
}
export function saveState(state: AppState): string | undefined {
  if (!isAppState(state)) return 'Changes could not be saved because their format is invalid.'
  try {
    const session = state.model && sessions.get(state.model)
    const raw = localStorage.getItem(KEY)
    // Never replace unreadable data or a concurrent tab's changes with a stale snapshot.
    if (session ? raw !== session.raw : raw !== null) return 'Stored data changed or was not loaded by this session. Reload before saving; stored data has been left untouched.'
    const model = serializeState(state)
    const nextRaw = JSON.stringify(model)
    localStorage.setItem(KEY, nextRaw)
    if (state.model) sessions.set(state.model, { model, raw: nextRaw })
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
    isCanvasElements(candidate.canvas) &&
    (candidate.canvasViewport === undefined || isCanvasViewport(candidate.canvasViewport))
}
export function makeObject(partial: Pick<ThoughtObject, 'kind' | 'originalContent' | 'source' | 'interpretation' | 'confidence'>): ThoughtObject {
  const now = new Date().toISOString()
  return { id: uid(), createdAt: now, context: undefined, relationships: [], history: [{ at: now, event: 'Captured' }], status: partial.confidence < .8 || ['action', 'commitment', 'reminder'].includes(partial.kind) ? 'review' : 'confirmed', metadata: {}, ...partial }
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

function isInterpretation(value: unknown): value is LegacyInterpretation {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<LegacyInterpretation>
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
