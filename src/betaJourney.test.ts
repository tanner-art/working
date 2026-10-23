import { describe, expect, it, vi } from 'vitest'
import { journeyFrame, observeJourney } from './betaJourney'

describe('cloud-to-ground progression', () => {
  it('starts in the clouds and lands at the ground without changing its final scale', () => {
    expect(journeyFrame(0)['--journey-sky-opacity']).toBe('1')
    expect(journeyFrame(0)['--journey-ground-opacity']).toBe('0')
    expect(journeyFrame(1)['--journey-ground-opacity']).toBe('1')
    expect(journeyFrame(1)['--journey-ground-y']).toBe('0svh')
    expect(journeyFrame(1)['--journey-cloud-opacity']).toBe('0')
    expect(journeyFrame(1)['--journey-wordmark-opacity']).toBe('0')
  })
  it('clamps overscroll, invalid positions and reverse scrolling deterministically', () => {
    expect(journeyFrame(-2)).toEqual(journeyFrame(0))
    expect(journeyFrame(2)).toEqual(journeyFrame(1))
    expect(journeyFrame(NaN)).toEqual(journeyFrame(0))
    const midpoint = journeyFrame(.5)
    journeyFrame(1)
    expect(journeyFrame(.5)).toEqual(midpoint)
    expect(Number(midpoint['--journey-ground-opacity'])).toBeGreaterThan(0)
    expect(Number(midpoint['--journey-ground-opacity'])).toBeLessThan(1)
  })
})

function harness(reduced = false) {
  let top = 0
  let nextId = 0
  const callbacks = new Map<number, FrameRequestCallback>()
  const listeners = new Map<string, () => void>()
  let preferenceChanged = () => {}
  const preference = { matches: reduced, addEventListener: vi.fn((_name, fn) => { preferenceChanged = fn }), removeEventListener: vi.fn() }
  const view = {
    matchMedia: () => preference,
    requestAnimationFrame: vi.fn((fn: FrameRequestCallback) => { callbacks.set(++nextId, fn); return nextId }),
    cancelAnimationFrame: vi.fn((id: number) => callbacks.delete(id)),
    addEventListener: vi.fn((name, fn) => listeners.set(name, fn)),
    removeEventListener: vi.fn((name) => listeners.delete(name)),
  }
  const properties = new Map<string, string>()
  const root = {
    dataset: {} as Record<string, string>,
    style: { setProperty: vi.fn((key, value) => properties.set(key, value)) },
    getBoundingClientRect: () => ({ top }),
    querySelector: () => ({ getBoundingClientRect: () => ({ top: top + 1600 }) }),
  }
  const cleanup = observeJourney(root as unknown as HTMLElement, view as unknown as Window)
  return { root, view, preference, properties, callbacks, cleanup,
    scroll: (value: number) => { top = value; listeners.get('scroll')?.() },
    flush: () => { const entries = [...callbacks.values()]; callbacks.clear(); entries.forEach(fn => fn(0)) },
    reduce: (value: boolean) => { preference.matches = value; preferenceChanged() },
  }
}
describe('scroll observer lifecycle', () => {
  it('coalesces rapid native scroll events without a perpetual animation loop', () => {
    const h = harness()
    expect(h.view.addEventListener).toHaveBeenCalledWith('scroll', expect.any(Function), { passive: true })
    h.scroll(-300); h.scroll(-800); h.scroll(-1600)
    expect(h.callbacks.size).toBe(1)
    h.flush()
    expect(h.properties.get('--journey-ground-opacity')).toBe('1')
    expect(h.callbacks.size).toBe(0)
    h.cleanup()
  })
  it('cleans up pending work and all listeners on sign-in/unmount', () => {
    const h = harness(); h.scroll(-100)
    h.cleanup()
    expect(h.callbacks.size).toBe(0)
    expect(h.view.removeEventListener).toHaveBeenCalledTimes(2)
    expect(h.preference.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    const writes = h.root.style.setProperty.mock.calls.length
    h.scroll(-1600); h.flush()
    expect(h.root.style.setProperty).toHaveBeenCalledTimes(writes)
  })
  it('honors reduced motion initially and when changed during a pending frame', () => {
    const h = harness(true)
    expect(h.root.dataset.motion).toBe('still')
    expect(h.root.style.setProperty).not.toHaveBeenCalled()
    h.reduce(false); h.scroll(-800)
    h.reduce(true)
    expect(h.callbacks.size).toBe(0)
    expect(h.root.dataset.motion).toBe('still')
    h.cleanup()
  })
})
