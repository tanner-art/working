import { describe, expect, it } from 'vitest'
import { digestIsDue, readDelivery, setDeliveryEnabled } from './digestDelivery'
import { localDateKey } from './morningDigest'

const now = new Date(2026, 8, 14, 7)
const enabled = setDeliveryEnabled({ enabled: false }, true, now)
describe('7 AM in-app delivery', () => {
  it('requires explicit schedule consent and records the gesture time', () => {
    expect(readDelivery({ getItem: () => null })).toEqual({ enabled: false })
    expect(digestIsDue({ enabled: false }, now, true)).toBe(false)
    expect(enabled.confirmedAt).toBe(now.toISOString())
    expect(digestIsDue(setDeliveryEnabled(enabled, false, now), now, true)).toBe(false)
  })
  it('waits until 7 local and catches up only when visible', () => {
    expect(digestIsDue(enabled, new Date(2026, 8, 14, 6, 59, 59), true)).toBe(false)
    expect(digestIsDue(enabled, now, false)).toBe(false)
    expect(digestIsDue(enabled, now, true)).toBe(true)
    expect(digestIsDue(enabled, new Date(2026, 8, 14, 19), true)).toBe(true)
  })
  it('deduplicates same day across reload and re-enable, and allows the next local day', () => {
    const delivered = { ...enabled, deliveredDay: localDateKey(now) }
    const loaded = readDelivery({ getItem: () => JSON.stringify(delivered) })
    expect(digestIsDue(loaded, now, true)).toBe(false)
    expect(digestIsDue(setDeliveryEnabled(loaded, true, now), now, true)).toBe(false)
    expect(digestIsDue(loaded, new Date(2026, 8, 15, 6), true)).toBe(false)
    expect(digestIsDue(loaded, new Date(2026, 8, 15, 7), true)).toBe(true)
  })
  it('fails closed on corrupt, inaccessible or unconfirmed enabled settings', () => {
    for (const raw of ['null', '{', '{"enabled":true}', '{"enabled":false,"deliveredDay":"2026-02-30"}']) {
      expect(() => readDelivery({ getItem: () => raw })).toThrow()
    }
    expect(() => readDelivery({ getItem: () => { throw new Error('blocked') } })).toThrow()
  })
  it('uses wall-clock 7 AM on both sides of DST changes, without a 24-hour timer', () => {
    for (const day of [new Date(2026, 2, 8, 7), new Date(2026, 10, 1, 7)]) {
      expect(digestIsDue(enabled, day, true)).toBe(true)
      expect(digestIsDue(enabled, new Date(day.getFullYear(), day.getMonth(), day.getDate(), 6, 59), true)).toBe(false)
    }
  })
})
