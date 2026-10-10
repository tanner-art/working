import { describe, expect, it } from 'vitest'
import { createSearchHandoffGuards } from './searchHandoffGuards'

describe('Search handoff from mounted editors', () => {
  it('allows clean views and blocks only a mounted editor with unsaved work', () => {
    const guards = createSearchHandoffGuards()
    expect(guards.canLeave()).toBe(true)
    let dirty = false
    const unregister = guards.register('calendar', () => !dirty)
    expect(guards.canLeave()).toBe(true)
    dirty = true
    expect(guards.canLeave()).toBe(false)
    dirty = false
    expect(guards.canLeave()).toBe(true)
    unregister()
    expect(guards.canLeave()).toBe(true)
  })

  it('does not let stale unmount cleanup remove a newer editor guard', () => {
    const guards = createSearchHandoffGuards()
    const oldCleanup = guards.register('settings', () => true)
    guards.register('settings', () => false)
    oldCleanup()
    expect(guards.canLeave()).toBe(false)
  })
})
