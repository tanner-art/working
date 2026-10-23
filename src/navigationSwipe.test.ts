import { afterEach, describe, expect, it, vi } from 'vitest'
import { canBeginSwipe, createNavigationSwipe, isViewportZoomed, swipeDestination, swipeTargetIsBlocked, SWIPE_VIEWS } from './navigationSwipe'

afterEach(() => vi.unstubAllGlobals())

describe('mobile primary navigation gestures', () => {
  it('moves one adjacent primary tab at a time, including the brand Home', () => {
    expect(SWIPE_VIEWS).toEqual(['beta-home', 'search', 'capture', 'organize', 'plan'])
    expect(swipeDestination('beta-home', -90, 5)).toBe('search')
    expect(swipeDestination('search', -90, 5)).toBe('capture')
    expect(swipeDestination('search', 90, 5)).toBe('beta-home')
    expect(swipeDestination('capture', 90, 5)).toBe('search')
    expect(swipeDestination('organize', -90, 0)).toBe('plan')
    expect(swipeDestination('organize', 90, 0)).toBe('capture')
    expect(swipeDestination('beta-home', 90, 0)).toBeUndefined()
    expect(swipeDestination('plan', -90, 0)).toBeUndefined()
    expect(swipeDestination('today', -90, 0)).toBeUndefined()
    for (const view of ['review', 'canvas']) {
      expect(swipeDestination(view, -90, 0)).toBe('plan')
      expect(swipeDestination(view, 90, 0)).toBe('capture')
    }
    for (const view of ['schedule', 'calendar', 'commitments']) expect(swipeDestination(view, 90, 0)).toBe('organize')
  })

  const gate = { pointerType: 'touch', isPrimary: true, view: 'review', deepCanvas: false,
    modalOpen: false, blockedTarget: false, mobile: true, viewportZoomed: false }
  const origin = { pointerId: 1, x: 200, y: 100 }
  it('recognizes one swipe and consumes its compatibility click, but not the next tap', () => {
    const gesture = createNavigationSwipe()
    gesture.begin(origin, gate)
    expect(gesture.preventHorizontalScroll(180, 102)).toBe(true)
    expect(gesture.finish({ ...origin, x: 100 }, 'review')).toBe('plan')
    expect(gesture.consumeClick(1)).toBe(true)
    expect(gesture.consumeClick(1)).toBe(false)
    gesture.begin(origin, gate)
    expect(gesture.finish(origin, 'review')).toBeUndefined()
    expect(gesture.consumeClick(1)).toBe(false)
  })
  it('does not turn a vertical scroll that later bends horizontally into navigation', () => {
    const gesture = createNavigationSwipe()
    gesture.begin(origin, gate)
    gesture.move({ ...origin, y: 120 })
    expect(gesture.preventHorizontalScroll(90, 120)).toBe(false)
    expect(gesture.finish({ ...origin, x: 90, y: 120 }, 'review')).toBeUndefined()
    gesture.begin(origin, gate)
    expect(gesture.preventHorizontalScroll(200, 120)).toBe(false)
    expect(gesture.finish({ ...origin, x: 90, y: 120 }, 'review')).toBeUndefined()
  })
  it('cancels multi-touch, pointer cancellation, changed screens, and blocked targets', () => {
    const gesture = createNavigationSwipe()
    for (const cancel of [
      () => gesture.cancel(),
      () => gesture.begin({ ...origin, pointerId: 2 }, { ...gate, isPrimary: false }),
      () => gesture.begin(origin, { ...gate, blockedTarget: true }),
    ]) {
      gesture.begin(origin, gate); cancel()
      expect(gesture.preventHorizontalScroll(100, 100)).toBe(false)
      expect(gesture.finish({ ...origin, x: 100 }, 'review')).toBeUndefined()
    }
    gesture.begin(origin, gate)
    expect(gesture.finish({ ...origin, x: 100 }, 'organize')).toBeUndefined()
  })
  it('suppresses a swipe-click at the last tab without wrapping or swallowing keyboard activation', () => {
    const gesture = createNavigationSwipe()
    gesture.begin(origin, { ...gate, view: 'plan' })
    expect(gesture.finish({ ...origin, x: 100 }, 'plan')).toBeUndefined()
    expect(gesture.consumeClick(0)).toBe(false)
    expect(gesture.consumeClick(1)).toBe(true)
  })

  it('does not interpret short or primarily vertical motions as navigation', () => {
    expect(swipeDestination('capture', -71, 0)).toBeUndefined()
    expect(swipeDestination('capture', -90, 90)).toBeUndefined()
    expect(swipeDestination('capture', -90, 60)).toBeUndefined()
    expect(swipeDestination('settings', -100, 0)).toBeUndefined()
    expect(swipeDestination('digest', -100, 0)).toBeUndefined()
  })

  it('does not begin in desktop, editing, modal, horizontal-scroll, or focused Canvas contexts', () => {
    const eligible = { pointerType: 'touch', isPrimary: true, view: 'organize', deepCanvas: false,
      modalOpen: false, blockedTarget: false, mobile: true, viewportZoomed: false }
    expect(canBeginSwipe(eligible)).toBe(true)
    for (const patch of [
      { pointerType: 'mouse' }, { isPrimary: false }, { view: 'settings' }, { deepCanvas: true },
      { modalOpen: true }, { blockedTarget: true }, { mobile: false }, { viewportZoomed: true },
    ]) expect(canBeginSwipe({ ...eligible, ...patch })).toBe(false)
  })

  it('reserves zoomed-page horizontal gestures for native panning', () => {
    expect(isViewportZoomed(undefined)).toBe(false)
    expect(isViewportZoomed(1)).toBe(false)
    expect(isViewportZoomed(1.25)).toBe(true)
    expect(canBeginSwipe({ pointerType: 'touch', isPrimary: true, view: 'capture', deepCanvas: false,
      modalOpen: false, blockedTarget: false, mobile: true, viewportZoomed: isViewportZoomed(1.25) })).toBe(false)
  })

  it('rejects editable targets and nested horizontal scrollers but accepts ordinary content', () => {
    class FakeElement {
      constructor(public parentElement: FakeElement | null = null, public blocked = false,
        public scrollWidth = 100, public clientWidth = 100, public overflowX = 'visible') {}
      matches() { return this.blocked }
    }
    vi.stubGlobal('Element', FakeElement)
    vi.stubGlobal('window', { getComputedStyle: (node: FakeElement) => ({ overflowX: node.overflowX }) })
    const root = new FakeElement()
    const content = new FakeElement(root)
    expect(swipeTargetIsBlocked(content as unknown as EventTarget, root as unknown as Element)).toBe(false)
    expect(swipeTargetIsBlocked(new FakeElement(content, true) as unknown as EventTarget, root as unknown as Element)).toBe(true)
    const scroll = new FakeElement(root, false, 400, 100, 'auto')
    expect(swipeTargetIsBlocked(new FakeElement(scroll) as unknown as EventTarget, root as unknown as Element)).toBe(true)
    expect(swipeTargetIsBlocked(null, root as unknown as Element)).toBe(true)
  })

  it('lets buttons, links and disclosures start swipes while reserving editors and drag handles', () => {
    class Target {
      parentElement = null
      scrollWidth = 100
      clientWidth = 100
      constructor(readonly selector: string) {}
      matches(selectors: string) { return selectors.split(',').map(value => value.trim()).includes(this.selector) }
    }
    vi.stubGlobal('Element', Target)
    for (const selector of ['button', 'a', 'summary']) {
      const target = new Target(selector) as unknown as Element
      expect(swipeTargetIsBlocked(target, target)).toBe(false)
    }
    for (const selector of ['input', 'textarea', '[contenteditable]', '[draggable="true"]', '.canvas', '[data-swipe-ignore]']) {
      const target = new Target(selector) as unknown as Element
      expect(swipeTargetIsBlocked(target, target)).toBe(true)
    }
  })
})
