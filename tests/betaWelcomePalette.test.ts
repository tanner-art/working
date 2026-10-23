import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/betaWelcome.css', import.meta.url), 'utf8')

const token = (name: string) => {
  const value = css.match(new RegExp(`--beta-${name}: (#[0-9a-f]{6});`))?.[1]
  if (!value) throw new Error(`Missing beta palette token: ${name}`)
  return value
}
const luminance = (hex: string) => {
  const channels = hex.slice(1).match(/../g)!.map(value => {
    const channel = parseInt(value, 16) / 255
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
  })
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722
}
const contrast = (a: string, b: string) => {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (values[0] + .05) / (values[1] + .05)
}

describe('nature-inspired beta palette', () => {
  it('keeps text readable even against a conservative dark bound of the decorative washes', () => {
    // Minimum channel values across the backdrop stops also bound their interpolations.
    const surfaces = [token('snow'), token('leaf'), '#cee5c8', '#d5edd5']
    for (const background of surfaces) {
      for (const foreground of ['ink', 'muted', 'sky']) {
        expect(contrast(token(foreground), background)).toBeGreaterThanOrEqual(4.5)
      }
    }
  })
  it('keeps primary button labels and focus rings distinct', () => {
    expect(contrast(token('snow'), token('pine'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('snow'), '#285441')).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('sky'), token('snow'))).toBeGreaterThanOrEqual(3)
    expect(css).toContain('outline: 3px solid var(--beta-sky)')
  })
})
