import { describe, expect, it } from 'vitest'
import {
  clearCalendarProviderSetupRequest, emptyCalendarConnectorState, externalCalendarProviders, requestCalendarProviderSetup,
  validateCalendarConnectorState,
} from './calendarConnectors'

describe('external calendar connector foundation', () => {
  it.each(['google', 'apple'] as const)('records %s setup intent while remaining disconnected and unable to invite', provider => {
    const state = requestCalendarProviderSetup(emptyCalendarConnectorState(), provider, '2026-09-23T10:00:00.000Z')
    expect(state.preferredProvider).toBe(provider)
    expect(state.connectors[provider]).toEqual({
      provider, connection: 'not-connected', setupIntent: 'requested', sync: 'disabled', attendeeInvitations: 'disabled', requestedAt: '2026-09-23T10:00:00.000Z',
    })
    expect(externalCalendarProviders[provider]).toMatchObject({ availability: 'foundation-only', attendeeInvitations: 'unavailable' })
    expect(validateCalendarConnectorState(state)).toEqual(state)
  })

  it('clears setup intent without leaving provider artifacts', () => {
    const requested = requestCalendarProviderSetup(emptyCalendarConnectorState(), 'google', '2026-09-23T10:00:00.000Z')
    expect(clearCalendarProviderSetupRequest(requested, 'google')).toEqual(emptyCalendarConnectorState())
  })

  it('rejects states that claim a connection, sync or attendee invitation capability', () => {
    const base = emptyCalendarConnectorState()
    for (const patch of [
      { connection: 'connected' }, { sync: 'enabled' }, { attendeeInvitations: 'enabled' }, { setupIntent: 'requested' }, { accessToken: 'secret' },
    ]) {
      expect(() => validateCalendarConnectorState({ ...base, connectors: { ...base.connectors, google: { ...base.connectors.google, ...patch } } })).toThrow('invalid')
    }
  })
})
