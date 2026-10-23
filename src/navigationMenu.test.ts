import { afterEach, describe, expect, it, vi } from 'vitest'
import { closeMoreMenu, dismissMoreMenuOutside } from './navigationMenu'

afterEach(() => vi.unstubAllGlobals())

describe('secondary navigation menu', () => {
  it('restores focus to summary when Escape closes an open menu', () => {
    const focus = vi.fn()
    const menu = { open: true, querySelector: () => ({ focus }) } as unknown as HTMLDetailsElement
    expect(closeMoreMenu(menu, true)).toBe(true)
    expect(menu.open).toBe(false)
    expect(focus).toHaveBeenCalledOnce()
    expect(closeMoreMenu(menu, true)).toBe(false)
  })

  it('dismisses only a pointer outside the open menu', () => {
    class FakeNode {}
    vi.stubGlobal('Node', FakeNode)
    const inside = new FakeNode()
    const outside = new FakeNode()
    const menu = { open: true, contains: (target: FakeNode) => target === inside } as unknown as HTMLDetailsElement
    expect(dismissMoreMenuOutside(menu, inside as unknown as EventTarget)).toBe(false)
    expect(menu.open).toBe(true)
    expect(dismissMoreMenuOutside(menu, outside as unknown as EventTarget)).toBe(true)
    expect(menu.open).toBe(false)
    expect(dismissMoreMenuOutside(menu, outside as unknown as EventTarget)).toBe(false)
  })
})
