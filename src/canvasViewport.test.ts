import { describe, expect, it } from 'vitest'
import type { CanvasElement, CanvasViewport } from './domain'
import { fitCanvasViewport, panCanvasViewport, screenPointAtWorld, worldPointAtScreen, zoomCanvasViewport } from './canvasViewport'

const nodes: CanvasElement[] = [
  { id: 'a', type: 'text', x: -100, y: 30, width: 200, height: 120, text: 'A' },
  { id: 'b', type: 'container', x: 400, y: 220, width: 300, height: 200, text: 'B' },
  { id: 'edge', type: 'arrow', x: 0, y: 0, fromId: 'a', toId: 'b' },
]

describe('canvasViewport', () => {
  it.each([0.55, 1, 1.6])('round-trips points at scale %s', scale => {
    const viewport: CanvasViewport = { x: -40, y: 125, scale }
    const world = { x: -12.5, y: 80.25 }
    const roundTrip = worldPointAtScreen(viewport, screenPointAtWorld(viewport, world))
    expect(roundTrip.x).toBeCloseTo(world.x)
    expect(roundTrip.y).toBeCloseTo(world.y)
  })

  it('zooms around a focal point without moving its world point', () => {
    const viewport = { x: -80, y: 40, scale: 1 }
    const focal = { x: 250, y: 180 }
    const world = worldPointAtScreen(viewport, focal)
    const zoomed = zoomCanvasViewport(viewport, focal, 1.6)
    expect(screenPointAtWorld(zoomed, world)).toEqual(focal)
    expect(zoomCanvasViewport(viewport, focal, 99).scale).toBe(1.6)
    expect(zoomCanvasViewport(viewport, focal, 0).scale).toBe(0.55)
  })

  it('pans by screen delta and normalizes invalid values', () => {
    expect(panCanvasViewport({ x: 2, y: 3, scale: 1 }, { x: 10, y: -5 })).toEqual({ x: 12, y: -2, scale: 1 })
    expect(panCanvasViewport({ x: NaN, y: Infinity, scale: NaN }, { x: Infinity, y: NaN })).toEqual({ x: 0, y: 0, scale: 1 })
  })

  it('fits all non-arrow bounds and ignores arrows', () => {
    const fit = fitCanvasViewport(nodes, { width: 800, height: 600 }, 40)
    expect(fit.scale).toBeCloseTo(.9)
    expect(screenPointAtWorld(fit, { x: -100, y: 30 }).x).toBeGreaterThanOrEqual(40)
    expect(screenPointAtWorld(fit, { x: 700, y: 420 }).x).toBeLessThanOrEqual(760)
    expect(screenPointAtWorld(fit, { x: -100, y: 30 }).y).toBeGreaterThanOrEqual(40)
    expect(screenPointAtWorld(fit, { x: 700, y: 420 }).y).toBeLessThanOrEqual(560)
  })

  it('fits only selected nodes and returns a stable default for no nodes', () => {
    const fit = fitCanvasViewport(nodes, { width: 400, height: 300 }, 20, new Set(['a']))
    expect(fit.scale).toBe(1.6)
    expect(fit).toEqual(fitCanvasViewport(nodes.filter(item => item.id === 'a'), { width: 400, height: 300 }, 20))
    expect(fitCanvasViewport([{ ...nodes[2] }], { width: 400, height: 300 })).toEqual({ x: 0, y: 0, scale: 1 })
    expect(fitCanvasViewport(nodes, { width: Infinity, height: NaN }, NaN).scale).toBeGreaterThanOrEqual(.55)
  })
})
