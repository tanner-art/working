import { describe, expect, it } from 'vitest'
import { interpret } from './interpreter'
import { isAppState } from './store'

describe('interpret', () => {
  it('recognizes an explicit action with high confidence', () => {
    const result = interpret('Give marketing guys access')
    expect(result.kind).toBe('action')
    expect(result.confidence).toBeGreaterThanOrEqual(.8)
  })

  it('routes ambiguous topic captures through review confidence', () => {
    const result = interpret('AI sales training')
    expect(result.kind).toBe('idea')
    expect(result.confidence).toBeLessThan(.8)
  })
})

describe('persisted state validation', () => {
  it('accepts an object and canvas collection with required identifiers', () => {
    expect(isAppState({ objects: [{ id: 'a', originalContent: 'A thought', kind: 'idea', status: 'review' }], canvas: [{ id: 'b', type: 'text' }] })).toBe(true)
  })

  it('rejects malformed saved state instead of loading it', () => {
    expect(isAppState({ objects: [{ originalContent: 'Missing id' }], canvas: null })).toBe(false)
  })
})
