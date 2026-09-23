export type ExternalCalendarProvider = 'google' | 'apple'

export const externalCalendarProviders: Record<ExternalCalendarProvider, {
  label: string
  availability: 'foundation-only'
  eventImport: 'planned'
  eventExport: 'planned'
  attendeeInvitations: 'unavailable'
}> = {
  google: { label: 'Google Calendar', availability: 'foundation-only', eventImport: 'planned', eventExport: 'planned', attendeeInvitations: 'unavailable' },
  apple: { label: 'Apple Calendar', availability: 'foundation-only', eventImport: 'planned', eventExport: 'planned', attendeeInvitations: 'unavailable' },
}

export interface CalendarConnectorPlaceholder {
  provider: ExternalCalendarProvider
  connection: 'not-connected'
  setupIntent: 'none' | 'requested'
  sync: 'disabled'
  attendeeInvitations: 'disabled'
  requestedAt?: string
}

export interface CalendarConnectorState {
  schemaVersion: 1
  preferredProvider?: ExternalCalendarProvider
  connectors: Record<ExternalCalendarProvider, CalendarConnectorPlaceholder>
}

export const emptyCalendarConnectorState = (): CalendarConnectorState => ({
  schemaVersion: 1,
  connectors: {
    google: { provider: 'google', connection: 'not-connected', setupIntent: 'none', sync: 'disabled', attendeeInvitations: 'disabled' },
    apple: { provider: 'apple', connection: 'not-connected', setupIntent: 'none', sync: 'disabled', attendeeInvitations: 'disabled' },
  },
})

const exactKeys = (value: object, keys: string[]) => Object.keys(value).every(key => keys.includes(key))

export function validateCalendarConnectorState(value: unknown): CalendarConnectorState {
  if (!value || typeof value !== 'object') throw Error('Calendar connector settings are invalid.')
  const state = value as CalendarConnectorState
  const providers: ExternalCalendarProvider[] = ['google', 'apple']
  if (!exactKeys(state, ['schemaVersion', 'preferredProvider', 'connectors']) || state.schemaVersion !== 1 || !state.connectors ||
      !exactKeys(state.connectors, providers) || (state.preferredProvider !== undefined && !providers.includes(state.preferredProvider))) {
    throw Error('Calendar connector settings are invalid.')
  }
  for (const provider of providers) {
    const item = state.connectors[provider]
    if (!item || !exactKeys(item, ['provider', 'connection', 'setupIntent', 'sync', 'attendeeInvitations', 'requestedAt']) ||
        item.provider !== provider || item.connection !== 'not-connected' || !['none', 'requested'].includes(item.setupIntent) ||
        item.sync !== 'disabled' || item.attendeeInvitations !== 'disabled' ||
        (item.setupIntent === 'requested') !== (typeof item.requestedAt === 'string' && Number.isFinite(Date.parse(item.requestedAt)))) {
      throw Error('Calendar connector settings are invalid.')
    }
  }
  return structuredClone(state)
}

/** Saves a provider preference and setup intent only; it performs no OAuth, CalDAV or network work. */
export function requestCalendarProviderSetup(state: CalendarConnectorState, provider: ExternalCalendarProvider, at: string): CalendarConnectorState {
  const current = validateCalendarConnectorState(state)
  if (!Number.isFinite(Date.parse(at))) throw Error('A valid setup request timestamp is required.')
  return validateCalendarConnectorState({
    ...current,
    preferredProvider: provider,
    connectors: { ...current.connectors, [provider]: { ...current.connectors[provider], setupIntent: 'requested', requestedAt: at } },
  })
}

export function clearCalendarProviderSetupRequest(state: CalendarConnectorState, provider: ExternalCalendarProvider): CalendarConnectorState {
  const current = validateCalendarConnectorState(state)
  const { requestedAt: _requestedAt, ...connector } = current.connectors[provider]
  return validateCalendarConnectorState({
    ...current,
    preferredProvider: current.preferredProvider === provider ? undefined : current.preferredProvider,
    connectors: { ...current.connectors, [provider]: { ...connector, setupIntent: 'none' } },
  })
}
