import { describe, expect, it } from 'vitest'
import { jsonEqual, stableJson } from './jsonEquality'

describe('JSON persistence equality', () => {
  it('ignores recursively reordered object keys without changing either value', () => {
    const left = { z: [{ b: 2, a: 1 }], a: { y: true, x: null } }
    const right = { a: { x: null, y: true }, z: [{ a: 1, b: 2 }] }
    const before = JSON.stringify([left, right])
    expect(jsonEqual(left, right)).toBe(true)
    expect(JSON.stringify([left, right])).toBe(before)
  })
  it.each([
    [[1, 2], [2, 1]],
    [[1, 1], [1]],
    [{ a: 1 }, { a: '1' }],
    [{ a: null }, {}],
    [{ a: 1 }, { a: 2 }],
    [{ a: 1 }, { a: 1, extra: true }],
    [[], {}],
  ])('preserves values, types, fields, array order and multiplicity (%j vs %j)', (left, right) => {
    expect(jsonEqual(left, right)).toBe(false)
  })
  it('retains ordinary JSON transport semantics for optional undefined fields', () => {
    expect(jsonEqual({ optional: undefined, a: 1 }, { a: 1 })).toBe(true)
    expect(jsonEqual([undefined], [null])).toBe(true)
    expect(stableJson(undefined)).toBeUndefined()
  })
  it('does not drop prototype-named JSON keys', () => {
    const value: unknown = JSON.parse('{"__proto__":{"a":1},"constructor":"value"}')
    expect(jsonEqual(value, { constructor: 'value' })).toBe(false)
    expect(JSON.parse(stableJson(value)!)).toEqual(value)
  })
})
