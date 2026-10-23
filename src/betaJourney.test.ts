import { describe, expect, it, vi } from 'vitest'
import { journeyFrame, observeJourney, moveJourney } from './betaJourney'

describe('ground-to-stars progression', () => {
  it('opens on the ground and ends with stars and the wordmark', () => {
    expect(journeyFrame(0)['--ascent-ground-opacity']).toBe('1')
    expect(journeyFrame(0)['--ascent-stars-opacity']).toBe('0')
    expect(journeyFrame(1)['--ascent-ground-opacity']).toBe('0')
    expect(journeyFrame(1)['--ascent-stars-opacity']).toBe('1')
    expect(journeyFrame(1)['--ascent-prize-opacity']).toBe('1')
  })
  it('passes mountains, sky and clouds in order', () => {
    expect(Number(journeyFrame(.3)['--ascent-mountain-opacity'])).toBe(1)
    expect(Number(journeyFrame(.6)['--ascent-cloud-opacity'])).toBe(1)
    expect(Number(journeyFrame(.6)['--ascent-sky-opacity'])).toBe(1)
    expect(Number(journeyFrame(.8)['--ascent-stars-opacity'])).toBeGreaterThan(0)
    expect(journeyFrame(.8)['--ascent-prize-opacity']).toBe('0')
  })
  it('clamps overscroll and invalid positions and reverses deterministically', () => {
    expect(journeyFrame(-2)).toEqual(journeyFrame(0))
    expect(journeyFrame(2)).toEqual(journeyFrame(1))
    expect(journeyFrame(NaN)).toEqual(journeyFrame(0))
    const midpoint = journeyFrame(.5)
    journeyFrame(1)
    expect(journeyFrame(.5)).toEqual(midpoint)
  })
})

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
    expect(h.properties.get('--ascent-ground-opacity')).toBe('1')
    expect(h.root.addEventListener).toHaveBeenCalledWith('scroll', expect.any(Function), { passive: true })
    h.scroll(2800); h.scroll(1600); h.scroll(0)
    expect(h.callbacks.size).toBe(1)
    h.flush()
    expect(h.properties.get('--ascent-stars-opacity')).toBe('1')
    expect(h.root.dataset.summit).toBe('true')
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
    expect(h.root.dataset.summit).toBe('true')
    expect(h.properties.get('--ascent-cloud-y')).toBe('0svh')
    expect(h.properties.get('--ascent-mountain-y')).toBe('0svh')
    h.reduce(false); h.flush()
    expect(h.root.dataset.motion).toBe('scroll')
    h.cleanup()
  })
  it('makes arrow controls native smooth scroll, or instant under reduced motion', () => {
    const h = harness()
    moveJourney(h.root as unknown as HTMLElement, 'up', h.view as unknown as Window)
    expect(h.root.scrollTo).toHaveBeenLastCalledWith({ top: 2400, behavior: 'smooth' })
    h.reduce(true)
    moveJourney(h.root as unknown as HTMLElement, 'ground', h.view as unknown as Window)
    expect(h.root.scrollTo).toHaveBeenLastCalledWith({ top: 3200, behavior: 'instant' })
    h.cleanup()
  })
})
