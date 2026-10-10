export const SWIPE_VIEWS = ['beta-home', 'today', 'capture', 'review', 'schedule', 'calendar', 'canvas'] as const
export type SwipeView = typeof SWIPE_VIEWS[number]

export interface SwipeStartGate {
  pointerType: string
  isPrimary: boolean
  view: string
  deepCanvas: boolean
  modalOpen: boolean
  blockedTarget: boolean
  mobile: boolean
}

/** Do not turn editing, nested scrolling, or a multi-touch gesture into navigation. */
export function canBeginSwipe(gate: SwipeStartGate): boolean {
  return gate.mobile && gate.pointerType === 'touch' && gate.isPrimary && !gate.deepCanvas &&
    !gate.modalOpen && !gate.blockedTarget && SWIPE_VIEWS.some(view => view === gate.view)
}

export function swipeDestination(view: string, deltaX: number, deltaY: number): SwipeView | undefined {
  const index = SWIPE_VIEWS.findIndex(candidate => candidate === view)
  if (index < 0 || Math.abs(deltaX) < 72 || Math.abs(deltaX) <= Math.abs(deltaY) * 1.5) return
  return SWIPE_VIEWS[index + (deltaX < 0 ? 1 : -1)]
}

/** Inspect ancestors only within the current content surface; controls retain their own gestures. */
export function swipeTargetIsBlocked(target: EventTarget | null, root: Element): boolean {
  if (typeof Element === 'undefined' || !(target instanceof Element)) return true
  for (let node: Element | null = target; node; node = node.parentElement) {
    if (node.matches('input, textarea, select, button, a, summary, [contenteditable], [role="dialog"], .canvas-page, .canvas, [data-swipe-ignore]')) return true
    if (node.scrollWidth > node.clientWidth + 8 && ['auto', 'scroll'].includes(window.getComputedStyle(node).overflowX)) return true
    if (node === root) break
  }
  return false
}
