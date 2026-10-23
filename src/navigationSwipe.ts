export const SWIPE_VIEWS = ['beta-home', 'search', 'capture', 'organize', 'plan'] as const
export type SwipeView = typeof SWIPE_VIEWS[number]

export function primarySwipeView(view: string): string {
  if (['review', 'canvas'].includes(view)) return 'organize'
  if (['schedule', 'calendar', 'commitments'].includes(view)) return 'plan'
  return view
}

export interface SwipeStartGate {
  pointerType: string
  isPrimary: boolean
  view: string
  deepCanvas: boolean
  modalOpen: boolean
  blockedTarget: boolean
  mobile: boolean
  viewportZoomed: boolean
}

export function isViewportZoomed(scale: number | undefined): boolean {
  return typeof scale === 'number' && scale > 1
}

/** Do not turn editing, nested scrolling, or a multi-touch gesture into navigation. */
export function canBeginSwipe(gate: SwipeStartGate): boolean {
  return gate.mobile && !gate.viewportZoomed && gate.pointerType === 'touch' && gate.isPrimary && !gate.deepCanvas &&
    !gate.modalOpen && !gate.blockedTarget && SWIPE_VIEWS.some(view => view === primarySwipeView(gate.view))
}

export function swipeDestination(view: string, deltaX: number, deltaY: number): SwipeView | undefined {
  const index = SWIPE_VIEWS.findIndex(candidate => candidate === primarySwipeView(view))
  if (index < 0 || Math.abs(deltaX) < 72 || Math.abs(deltaX) <= Math.abs(deltaY) * 1.5) return
  return SWIPE_VIEWS[index + (deltaX < 0 ? 1 : -1)]
}

/** Inspect ancestors only within the current content surface; controls retain their own gestures. */
export function swipeTargetIsBlocked(target: EventTarget | null, root: Element): boolean {
  if (typeof Element === 'undefined' || !(target instanceof Element)) return true
  for (let node: Element | null = target; node; node = node.parentElement) {
    if (node.matches('input, textarea, select, [contenteditable], [role="dialog"], [role="slider"], [draggable="true"], .canvas-page, .canvas, [data-swipe-ignore]')) return true
    if (node.scrollWidth > node.clientWidth + 8 && ['auto', 'scroll'].includes(window.getComputedStyle(node).overflowX)) return true
    if (node === root) break
  }
  return false
}

type Contact = { pointerId: number; x: number; y: number }

/** One touch sequence, with irreversible vertical-scroll cancellation. */
export function createNavigationSwipe() {
  let start: (Contact & { view: string }) | undefined
  let suppressClickUntil = 0
  return {
    cancel() { start = undefined },
    begin(contact: Contact, gate: SwipeStartGate) {
      suppressClickUntil = 0
      start = canBeginSwipe(gate) ? { ...contact, view: gate.view } : undefined
    },
    move(contact: Contact) {
      if (!start || contact.pointerId !== start.pointerId) return
      const dx = Math.abs(contact.x - start.x), dy = Math.abs(contact.y - start.y)
      if (dy >= 12 && dy >= dx) start = undefined
    },
    preventHorizontalScroll(x: number, y: number): boolean {
      if (!start) return false
      const dx = Math.abs(x - start.x), dy = Math.abs(y - start.y)
      if (dy >= 12 && dy >= dx) { start = undefined; return false }
      return dx >= 12 && dx > dy * 1.5
    },
    finish(contact: Contact, view: string): SwipeView | undefined {
      const origin = start
      start = undefined
      if (!origin || origin.pointerId !== contact.pointerId || origin.view !== view) return
      const dx = contact.x - origin.x, dy = contact.y - origin.y
      // Even at a tab edge, a deliberate swipe must not activate its starting button.
      if (Math.abs(dx) >= 72 && Math.abs(dx) > Math.abs(dy) * 1.5) suppressClickUntil = Date.now() + 800
      return swipeDestination(view, dx, dy)
    },
    consumeClick(detail: number): boolean {
      const suppress = detail > 0 && Date.now() < suppressClickUntil
      if (suppress) suppressClickUntil = 0
      return suppress
    },
  }
}
