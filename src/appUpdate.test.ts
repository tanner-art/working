import { describe, expect, it } from 'vitest'
import {
  appUpdateReducer,
  createAppUpdateState,
  getAppUpdateView,
  type AppUpdateEvent,
} from './appUpdate'

const start = (checkId = 'check-1') =>
  appUpdateReducer(createAppUpdateState(), { type: 'check-started', checkId })

describe('app update lifecycle', () => {
  it('models the normal check, apply, and user-offered reload flow', () => {
    const checking = start()
    const available = appUpdateReducer(checking, {
      type: 'check-succeeded',
      checkId: 'check-1',
      updateAvailable: true,
      version: '2.0.0',
    })
    expect(available.status).toBe('update-available')
    expect(getAppUpdateView(available).canOfferReload).toBe(false)

    const applying = appUpdateReducer(available, { type: 'apply-requested' })
    const applied = appUpdateReducer(applying, { type: 'apply-succeeded' })
    expect(applied.status).toBe('applied')
    expect(getAppUpdateView(applied)).toEqual({
      canOfferReload: true,
      guidance: 'The update is ready. Reload when convenient.',
    })
  })

  it('represents offline launch and recovery explicitly', () => {
    const offline = appUpdateReducer(createAppUpdateState(), { type: 'offline' })
    expect(offline.status).toBe('offline')
    expect(getAppUpdateView(offline).guidance).toContain('offline')
    expect(appUpdateReducer(offline, { type: 'online' }).status).toBe('current')
  })

  it('represents a failed check and keeps its concise error guidance', () => {
    const failed = appUpdateReducer(start(), {
      type: 'check-failed',
      checkId: 'check-1',
      error: 'Network unavailable.',
    })
    expect(failed.status).toBe('failed')
    expect(getAppUpdateView(failed)).toEqual({ canOfferReload: false, guidance: 'Network unavailable.' })
  })

  it('handles repeated events deterministically and rejects stale results', () => {
    const checking = start()
    const available = appUpdateReducer(checking, {
      type: 'check-succeeded',
      checkId: 'check-1',
      updateAvailable: true,
    })
    expect(appUpdateReducer(available, { type: 'check-succeeded', checkId: 'check-1', updateAvailable: true })).toBe(
      available,
    )
    expect(appUpdateReducer(available, { type: 'apply-succeeded' })).toBe(available)

    const newerCheck = appUpdateReducer(available, { type: 'check-started', checkId: 'check-2' })
    expect(
      appUpdateReducer(newerCheck, { type: 'check-succeeded', checkId: 'check-1', updateAvailable: false }),
    ).toBe(newerCheck)
    expect(
      appUpdateReducer(newerCheck, { type: 'check-failed', checkId: 'check-1', error: 'stale' }),
    ).toBe(newerCheck)
  })

  it('requires an explicit apply flow and never reloads automatically', () => {
    const available = appUpdateReducer(start(), {
      type: 'check-succeeded',
      checkId: 'check-1',
      updateAvailable: true,
    })
    expect(available.status).toBe('update-available')
    expect(getAppUpdateView(available).canOfferReload).toBe(false)
    expect(appUpdateReducer(available, { type: 'apply-requested' }).status).toBe('applying')
    expect(appUpdateReducer(available, { type: 'apply-succeeded' })).toBe(available)
  })

  it('does not mutate input state or events', () => {
    const state = start()
    const event: AppUpdateEvent = {
      type: 'check-succeeded',
      checkId: 'check-1',
      updateAvailable: true,
      version: '2.0.0',
    }
    const stateSnapshot = structuredClone(state)
    const eventSnapshot = structuredClone(event)
    const next = appUpdateReducer(state, event)
    expect(state).toEqual(stateSnapshot)
    expect(event).toEqual(eventSnapshot)
    expect(next).not.toBe(state)
  })
})
