/** Legacy UI vocabulary only. Persisted SemanticKind deliberately excludes reminders. */
export type ObjectKind = 'idea' | 'action' | 'reminder' | 'project' | 'commitment' | 'person' | 'reference' | 'objective'
export type ObjectStatus = 'inbox' | 'review' | 'confirmed' | 'complete' | 'archived'
export type SourceType = 'text' | 'voice' | 'canvas'

export interface ThoughtObject {
  id: string
  kind: ObjectKind
  originalContent: string
  source: SourceType
  createdAt: string
  context?: string
  interpretation: LegacyInterpretation
  confidence: number
  relationships: Relationship[]
  history: HistoryEvent[]
  status: ObjectStatus
  metadata: ObjectMetadata
}

export interface LegacyInterpretation {
  summary: string
  suggestedKind: ObjectKind
  rationale: string
  suggestedProject?: string
  suggestedDate?: string
}
export interface ObjectMetadata {
  urgency?: 1 | 2 | 3 | 4 | 5
  deadline?: string
  effort?: 'small' | 'medium' | 'large'
  attentionLoad?: 'low' | 'medium' | 'high'
  strategicImportance?: 1 | 2 | 3 | 4 | 5
  resourceCost?: 'low' | 'medium' | 'high'
  roi?: 1 | 2 | 3 | 4 | 5
}
export interface Relationship { targetId: string; type: 'belongs_to' | 'relates_to' | 'depends_on' | 'supports' }
export interface ConfirmationGesture {
  objectId: string
  transition: ObjectKind
  summary: string
  source: 'review-confirmation'
}
export interface HistoryEvent {
  at: string
  event: string
  confirmation?: ConfirmationGesture
  reviewDecision?: 'rejected' | 'reversed' | 'superseded'
}
/** Executable meaning still awaiting a dedicated confirmation gesture. */
export interface ProposedAction { summary: string }
export interface CanvasElement {
  id: string
  type: 'text' | 'container' | 'arrow'
  x: number
  y: number
  width?: number
  height?: number
  text?: string
  fromId?: string
  toId?: string
}
/** Compatibility view consumed by existing screens; model retains canonical evidence. */
export interface AppState { objects: ThoughtObject[]; canvas: CanvasElement[]; model?: PersistedState; temporalHistory?: TemporalDecision[] }

export const objectLabels: Record<ObjectKind, string> = {
  idea: 'Idea', action: 'Action', reminder: 'Reminder', project: 'Project', commitment: 'Commitment', person: 'Person', reference: 'Reference', objective: 'Objective'
}


export type SemanticKind = Exclude<ObjectKind, 'reminder'>
export interface CaptureRecord {
  readonly id: string
  readonly source: SourceType
  readonly createdAt: string
  readonly originalContent: string
  readonly context?: string
  /** The old app recorded text only, even for voice/canvas captures. */
  readonly evidence: 'text-only'
}
export interface Interpretation {
  readonly id: string
  readonly version: number
  readonly previousId?: string
  readonly captureIds: string[]
  readonly recordedAt: string
  readonly summary: string
  readonly rationale: string
  readonly confidence: number
  readonly proposedKind: SemanticKind | 'unresolved'
  readonly proposedAction?: ProposedAction
  readonly reviewState: 'review' | 'accepted' | 'rejected'
  readonly confirmation?: { at: string; transition: 'action' | 'commitment'; objectId?: string; interpretationId?: string; historyIndex?: number; source?: 'review-confirmation' }
  readonly proposedReminder?: ReminderInstruction
  /** Lossless historical UI evidence, not executable meaning or authoritative capture. */
  readonly legacy: Omit<ThoughtObject, 'originalContent' | 'source' | 'createdAt'>
}
export interface ReminderInstruction {
  id: string
  trigger: { kind: 'unresolved'; wording: string; legacyDate?: string }
  deliveryState: 'needs-review'
  captureIds: string[]
}
export interface SemanticObject {
  id: string
  kind: SemanticKind
  captureIds: string[]
  interpretationIds: string[]
  summary: string
  status: ObjectStatus
  metadata: ObjectMetadata
  reminders: ReminderInstruction[]
}
export interface Commitment extends SemanticObject { kind: 'commitment' }
export interface CalendarEvent {
  id: string
  title: string
  startsAt: string
  temporalContext: string
  objectIds: string[]
  captureIds: string[]
  status: 'scheduled' | 'cancelled'
}
/** Retains endpoints without choosing OD-007 membership cardinality. */
export interface SemanticRelationship extends Relationship {
  id: string
  sourceId: string
  scope: 'semantic'
  provenance: { interpretationId: string; evidence: 'legacy-unverified' }
}
export interface PersistedState {
  temporalHistory?: TemporalDecision[]
  schemaVersion: 2
  captures: CaptureRecord[]
  interpretations: Interpretation[]
  semanticObjects: SemanticObject[]
  calendarEvents: CalendarEvent[]
  relationships: SemanticRelationship[]
  /** Active UI identities include unresolved proposals without semantic objects. */
  legacyUiIds: string[]
  canvas: CanvasElement[]
}

/** A snapshot of exactly one proposed temporal fact; never obligation evidence. */
export type TemporalTarget =
  | { kind: 'fixed-deadline'; objectId: string; interpretationId: string; date: string }
  | { kind: 'event-scheduling'; eventId: string; interpretationId: string; startsAt: string; temporalContext: string; title: string; objectIds: string[]; captureIds: string[] }
export interface TemporalDecision {
  id: string
  at: string
  source: 'review-temporal-confirmation'
  decision: 'confirmed' | 'reversed'
  target: TemporalTarget
  /** Reversal names the exact confirmation it withdraws. */
  reverses?: string
}
