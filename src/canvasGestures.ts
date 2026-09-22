export const CANVAS_GESTURE_SLOP = 8

export type GestureTarget =
  | { kind: 'canvas' }
  | { kind: 'node'; id: string }
  | { kind: 'textarea'; id: string }
  | { kind: 'resize'; id: string }

export interface PointerSample { pointerId: number; x: number; y: number }
export type GestureMode = 'idle' | 'pressed' | 'moving-node' | 'panning' | 'edit-menu' | 'pinch-zooming' | 'resizing'
export interface GestureState {
  mode: GestureMode
  target?: GestureTarget
  primary?: PointerSample
  pointers: Record<number, PointerSample>
  menuOpened: boolean
}

export type GestureAction =
  | { type: 'pointer-down'; sample: PointerSample; target: GestureTarget }
  | { type: 'hold'; pointerId: number }
  | { type: 'pointer-move'; sample: PointerSample }
  | { type: 'pointer-up'; pointerId: number }
  | { type: 'pointer-cancel'; pointerId: number }
  | { type: 'enter-edit-mode' }
  | { type: 'exit-edit-mode' }
  | { type: 'outside-tap' }
  | { type: 'reset' }

export type GestureEffect =
  | { type: 'select'; id: string }
  | { type: 'open-edit-menu'; id: string }
  | { type: 'begin-move'; id: string; start: PointerSample }
  | { type: 'preview-move'; id: string; delta: { x: number; y: number } }
  | { type: 'commit-move'; id: string; delta: { x: number; y: number } }
  | { type: 'begin-pan'; start: PointerSample }
  | { type: 'preview-pan'; delta: { x: number; y: number } }
  | { type: 'commit-pan'; delta: { x: number; y: number } }
  | { type: 'begin-resize'; id: string; start: PointerSample }
  | { type: 'preview-resize'; id: string; delta: { x: number; y: number } }
  | { type: 'commit-resize'; id: string; delta: { x: number; y: number } }
  | { type: 'begin-pinch'; first: PointerSample; second: PointerSample }
  | { type: 'preview-pinch'; first: PointerSample; second: PointerSample }
  | { type: 'commit-pinch' }
  | { type: 'cancel' }

export interface GestureResult { state: GestureState; effects: GestureEffect[] }

export const idleGestureState = (): GestureState => ({ mode: 'idle', pointers: {}, menuOpened: false })
const pointDelta = (from: PointerSample, to: PointerSample) => ({ x: to.x - from.x, y: to.y - from.y })
const moved = (from: PointerSample, to: PointerSample) => Math.hypot(to.x - from.x, to.y - from.y) >= CANVAS_GESTURE_SLOP
const isNodeTarget = (target?: GestureTarget): target is { kind: 'node'; id: string } => target?.kind === 'node'
const activePointers = (pointers: Record<number, PointerSample>) => Object.values(pointers)
const pinchPair = (pointers: Record<number, PointerSample>) => activePointers(pointers).slice(0, 2) as [PointerSample, PointerSample]

function clearPointer(state: GestureState, pointerId: number): GestureState {
  const pointers = { ...state.pointers }
  delete pointers[pointerId]
  return { ...state, pointers }
}

export function reduceCanvasGesture(state: GestureState, action: GestureAction): GestureResult {
  if (action.type === 'reset' || action.type === 'outside-tap' || action.type === 'exit-edit-mode') return { state: idleGestureState(), effects: state.mode === 'idle' ? [] : [{ type: 'cancel' }] }
  if (action.type === 'enter-edit-mode') return { state: { ...state, mode: 'edit-menu', menuOpened: true }, effects: [] }

  if (action.type === 'pointer-down') {
    const pointers = { ...state.pointers, [action.sample.pointerId]: action.sample }
    if (Object.keys(pointers).length > 1) {
      const [first, second] = pinchPair(pointers)
      return { state: { ...state, mode: 'pinch-zooming', pointers, menuOpened: false }, effects: [...(state.mode === 'idle' ? [] : [{ type: 'cancel' as const }]), { type: 'begin-pinch', first, second }] }
    }
    if (action.target.kind === 'resize') {
      if (state.mode !== 'edit-menu' && !state.menuOpened) return { state, effects: [] }
      return { state: { mode: 'resizing', target: action.target, primary: action.sample, pointers, menuOpened: true }, effects: [{ type: 'begin-resize', id: action.target.id, start: action.sample }] }
    }
    if (action.target.kind === 'textarea') return { state: { mode: 'pressed', target: action.target, primary: action.sample, pointers, menuOpened: false }, effects: [] }
    return { state: { mode: 'pressed', target: action.target, primary: action.sample, pointers, menuOpened: false }, effects: [] }
  }

  if (action.type === 'hold') {
    if (state.mode !== 'pressed' || state.primary?.pointerId !== action.pointerId || !isNodeTarget(state.target)) return { state, effects: [] }
    return { state: { ...state, mode: 'edit-menu', menuOpened: true }, effects: [{ type: 'open-edit-menu', id: state.target.id }] }
  }

  if (action.type === 'pointer-move') {
    const previous = state.pointers[action.sample.pointerId]
    if (!previous) return { state, effects: [] }
    const pointers = { ...state.pointers, [action.sample.pointerId]: action.sample }
    if (state.mode === 'pinch-zooming') {
      const [first, second] = pinchPair(pointers)
      return { state: { ...state, pointers }, effects: [{ type: 'preview-pinch', first, second }] }
    }
    if (!state.primary || state.primary.pointerId !== action.sample.pointerId) return { state: { ...state, pointers }, effects: [] }
    const delta = pointDelta(state.primary, action.sample)
    if (state.mode === 'resizing' && state.target?.kind === 'resize') return { state: { ...state, pointers }, effects: [{ type: 'preview-resize', id: state.target.id, delta }] }
    if (!moved(state.primary, action.sample)) return { state: { ...state, pointers }, effects: [] }
    if (isNodeTarget(state.target)) {
      if (state.mode === 'moving-node') return { state: { ...state, pointers }, effects: [{ type: 'preview-move', id: state.target.id, delta }] }
      return { state: { ...state, mode: 'moving-node', pointers, menuOpened: false }, effects: [{ type: 'cancel' }, { type: 'begin-move', id: state.target.id, start: state.primary }] }
    }
    if (state.target?.kind === 'canvas') {
      if (state.mode === 'panning') return { state: { ...state, pointers }, effects: [{ type: 'preview-pan', delta }] }
      return { state: { ...state, mode: 'panning', pointers }, effects: [{ type: 'cancel' }, { type: 'begin-pan', start: state.primary }] }
    }
    if (state.mode === 'pressed') return { state: { ...state, mode: 'idle', pointers }, effects: [{ type: 'cancel' }] }
    return { state: { ...state, pointers }, effects: [] }
  }

  if (action.type === 'pointer-up' || action.type === 'pointer-cancel') {
    const pointer = state.pointers[action.pointerId]
    const effects: GestureEffect[] = []
    if (pointer && state.primary?.pointerId === action.pointerId) {
      const delta = pointDelta(state.primary, pointer)
      if (action.type === 'pointer-up' && state.mode === 'pressed' && isNodeTarget(state.target)) effects.push({ type: 'select', id: state.target.id })
      if (action.type === 'pointer-up' && state.mode === 'moving-node' && isNodeTarget(state.target)) effects.push({ type: 'commit-move', id: state.target.id, delta })
      if (action.type === 'pointer-up' && state.mode === 'panning' && state.target?.kind === 'canvas') effects.push({ type: 'commit-pan', delta })
      if (action.type === 'pointer-up' && state.mode === 'resizing' && state.target?.kind === 'resize') effects.push({ type: 'commit-resize', id: state.target.id, delta })
    }
    const next = clearPointer(state, action.pointerId)
    if (state.mode === 'pinch-zooming') return { state: idleGestureState(), effects: action.type === 'pointer-cancel' ? [{ type: 'cancel' }] : [{ type: 'commit-pinch' }] }
    return { state: idleGestureState(), effects: action.type === 'pointer-cancel' ? [{ type: 'cancel' }] : effects }
  }
  return { state, effects: [] }
}
