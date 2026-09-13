import type { AppState, CanvasElement, ThoughtObject } from './domain'

const KEY = 'thoughtflow-state-v1'
const uid = () => crypto.randomUUID()
const today = new Date().toISOString().slice(0, 10)

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
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? '')
    return isAppState(saved) ? saved : seed
  } catch { return seed }
}
export function saveState(state: AppState) { localStorage.setItem(KEY, JSON.stringify(state)) }
export function isAppState(value: unknown): value is AppState {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<AppState>
  return Array.isArray(candidate.objects) && Array.isArray(candidate.canvas) && candidate.objects.every(item =>
    item && typeof item.id === 'string' && typeof item.originalContent === 'string' && typeof item.kind === 'string' && typeof item.status === 'string'
  ) && candidate.canvas.every(item => item && typeof item.id === 'string' && typeof item.type === 'string')
}
export function makeObject(partial: Pick<ThoughtObject, 'kind' | 'originalContent' | 'source' | 'interpretation' | 'confidence'>): ThoughtObject {
  const now = new Date().toISOString()
  return { id: uid(), createdAt: now, context: undefined, relationships: [], history: [{ at: now, event: 'Captured' }], status: partial.confidence < .8 ? 'review' : 'confirmed', metadata: {}, ...partial }
}
export function newCanvasElement(type: CanvasElement['type'], x: number, y: number): CanvasElement {
  return { id: uid(), type, x, y, width: type === 'container' ? 320 : 190, height: type === 'container' ? 210 : undefined, text: type === 'container' ? 'Untitled group' : 'New thought' }
}
