import { describe, expect, it, vi } from 'vitest'
import { observeJourney } from './betaJourney'

function harness(reduced = false, initial = 0) {
  let nextId = 0
  const callbacks = new Map<number, FrameRequestCallback>()
  const listeners = new Map<string, () => void>()
  const preference = { matches: reduced, addEventListener: vi.fn((_name, fn) => listeners.set('preference', fn)), removeEventListener: vi.fn() }
  const view = {
    matchMedia: () => preference,
    requestAnimationFrame: vi.fn((fn: FrameRequestCallback) => { callbacks.set(++nextId, fn); return nextId }),
    cancelAnimationFrame: vi.fn((id: number) => callbacks.delete(id)),
    addEventListener: vi.fn((name, fn) => listeners.set(name, fn)),
    removeEventListener: vi.fn((name) => listeners.delete(name)),
  }
  const properties = new Map<string, string>()
  const root = {
    dataset: {} as Record<string, string>, scrollTop: 0, scrollHeight: 4000, clientHeight: 800,
    style: { setProperty: vi.fn((key, value) => properties.set(key, value)) },
    addEventListener: vi.fn((name, fn) => listeners.set(name, fn)),
    removeEventListener: vi.fn((name) => listeners.delete(name)),
    scrollTo: vi.fn(),
  }
  const onProgress = vi.fn()
  const cleanup = observeJourney(root as unknown as HTMLElement, view as unknown as Window, initial, onProgress)
  return { root, view, preference, properties, callbacks, cleanup, onProgress,
    scroll: (value: number) => { root.scrollTop = value; listeners.get('scroll')?.() },
    resize: () => listeners.get('resize')?.(),
    flush: () => { const entries = [...callbacks.values()]; callbacks.clear(); entries.forEach(fn => fn(0)) },
    reduce: (value: boolean) => { preference.matches = value; listeners.get('preference')?.() },
  }
}
describe('native upward scroll lifecycle', () => {
  it('initializes at the bottom and coalesces upward scrolling without an animation loop', () => {
    const h = harness()
    expect(h.root.scrollTop).toBe(3200)
    expect(h.onProgress).toHaveBeenLastCalledWith(0)
    expect(h.root.addEventListener).toHaveBeenCalledWith('scroll', expect.any(Function), { passive: true })
    h.scroll(2800); h.scroll(1600); h.scroll(0)
    expect(h.callbacks.size).toBe(1)
    h.flush()
    expect(h.root.style.setProperty).not.toHaveBeenCalled()
    expect(h.onProgress).toHaveBeenLastCalledWith(1)
    expect(h.callbacks.size).toBe(0)
    h.cleanup()
  })
  it('restores progress when returning from information and preserves it across viewport resize', () => {
    const h = harness(false, .5)
    expect(h.root.scrollTop).toBe(1600)
    h.root.scrollHeight = 6000; h.root.clientHeight = 1000
    h.resize(); h.flush()
    expect(h.root.scrollTop).toBe(2500)
    expect(h.onProgress).toHaveBeenLastCalledWith(.5)
    h.cleanup()
  })
  it('cleans up pending work and all listeners', () => {
    const h = harness(); h.scroll(100)
    h.cleanup()
    expect(h.callbacks.size).toBe(0)
    expect(h.root.removeEventListener).toHaveBeenCalledWith('scroll', expect.any(Function))
    expect(h.view.removeEventListener).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(h.preference.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    const writes = h.root.style.setProperty.mock.calls.length
    h.scroll(0); h.flush()
    expect(h.root.style.setProperty).toHaveBeenCalledTimes(writes)
  })
  it('keeps all destinations reachable in reduced motion without parallax', () => {
    const h = harness(true)
    expect(h.root.dataset.motion).toBe('still')
    h.scroll(0); h.flush()
    expect(h.onProgress).toHaveBeenLastCalledWith(1)
    expect(h.root.style.setProperty).not.toHaveBeenCalled()
    h.reduce(false); h.flush()
    expect(h.root.dataset.motion).toBe('scroll')
    h.cleanup()
  })
  it('clamps invalid saved positions and native overscroll without changing artwork styles', () => {
    const h = harness(false, NaN)
    expect(h.root.scrollTop).toBe(3200)
    h.scroll(-50); h.flush()
    expect(h.onProgress).toHaveBeenLastCalledWith(1)
    h.scroll(4000); h.flush()
    expect(h.onProgress).toHaveBeenLastCalledWith(0)
    expect(h.root.style.setProperty).not.toHaveBeenCalled()
    h.cleanup()
  })
})
