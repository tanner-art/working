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
  interpretation: Interpretation
  confidence: number
  relationships: Relationship[]
  history: HistoryEvent[]
  status: ObjectStatus
  metadata: ObjectMetadata
}

export interface Interpretation {
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
}
export interface Relationship { targetId: string; type: 'belongs_to' | 'relates_to' | 'depends_on' | 'supports' }
export interface HistoryEvent { at: string; event: string }
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
export interface AppState { objects: ThoughtObject[]; canvas: CanvasElement[] }

export const objectLabels: Record<ObjectKind, string> = {
  idea: 'Idea', action: 'Action', reminder: 'Reminder', project: 'Project', commitment: 'Commitment', person: 'Person', reference: 'Reference', objective: 'Objective'
}
