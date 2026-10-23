import { afterEach, describe, expect, it, vi } from 'vitest'
import { canBeginSwipe, isViewportZoomed, swipeDestination, swipeTargetIsBlocked, SWIPE_VIEWS } from './navigationSwipe'

afterEach(() => vi.unstubAllGlobals())

describe('mobile primary navigation gestures', () => {
  it('moves one adjacent primary tab at a time, including the brand Home', () => {
    expect(SWIPE_VIEWS).toEqual(['beta-home', 'today', 'capture', 'review', 'schedule', 'calendar', 'canvas'])
    expect(swipeDestination('beta-home', -90, 5)).toBe('today')
    expect(swipeDestination('today', 90, 5)).toBe('beta-home')
    expect(swipeDestination('schedule', -90, 0)).toBe('calendar')
    expect(swipeDestination('schedule', 90, 0)).toBe('review')
    expect(swipeDestination('beta-home', 90, 0)).toBeUndefined()
    expect(swipeDestination('canvas', -90, 0)).toBeUndefined()
  })

  it('does not interpret short or primarily vertical motions as navigation', () => {
    expect(swipeDestination('today', -71, 0)).toBeUndefined()
    expect(swipeDestination('today', -90, 90)).toBeUndefined()
    expect(swipeDestination('today', -90, 60)).toBeUndefined()
    expect(swipeDestination('settings', -100, 0)).toBeUndefined()
    expect(swipeDestination('digest', -100, 0)).toBeUndefined()
  })

  it('does not begin in desktop, editing, modal, horizontal-scroll, or focused Canvas contexts', () => {
    const eligible = { pointerType: 'touch', isPrimary: true, view: 'review', deepCanvas: false,
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
    expect(canBeginSwipe({ pointerType: 'touch', isPrimary: true, view: 'today', deepCanvas: false,
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
})
