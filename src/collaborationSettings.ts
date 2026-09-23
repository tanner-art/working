export const collaborationFeatureStatus = {
  threadlineInvites: {
    status: 'draft-only',
    canSend: false,
    description: 'Prepare an invite for another Threadline user. Delivery is not connected yet.',
  },
  calendarAttendees: {
    status: 'under-construction',
    canSend: false,
    description: 'Adding Threadline users to calendar events is under construction.',
  },
} as const

export interface ThreadlineInviteDraft {
  id: string
  recipientEmail: string
  createdAt: string
  delivery: 'not-sent'
  createdBy: 'account-owner'
}

export interface CalendarAttendeeDraft {
  id: string
  recipientEmail: string
  createdAt: string
  featureStatus: 'under-construction'
  invitation: 'not-created'
  createdBy: 'account-owner'
}

export interface CollaborationSettingsState {
  schemaVersion: 1
  threadlineInviteDrafts: ThreadlineInviteDraft[]
  calendarAttendeeDrafts: CalendarAttendeeDraft[]
}

export const emptyCollaborationSettings = (): CollaborationSettingsState => ({
  schemaVersion: 1,
  threadlineInviteDrafts: [],
  calendarAttendeeDrafts: [],
})

function normalizedEmail(value: string): string {
  const email = value.trim().toLocaleLowerCase()
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw Error('Enter a valid email address.')
  return email
}

function validDate(value: string) { return Number.isFinite(Date.parse(value)) }
const exactKeys = (value: object, keys: string[]) => Object.keys(value).every(key => keys.includes(key))

export function validateCollaborationSettings(value: unknown): CollaborationSettingsState {
  if (!value || typeof value !== 'object') throw Error('Collaboration settings are invalid.')
  const state = value as CollaborationSettingsState
  if (!exactKeys(state, ['schemaVersion', 'threadlineInviteDrafts', 'calendarAttendeeDrafts']) ||
      state.schemaVersion !== 1 || !Array.isArray(state.threadlineInviteDrafts) || !Array.isArray(state.calendarAttendeeDrafts)) throw Error('Collaboration settings are invalid.')
  const allIds = [...state.threadlineInviteDrafts, ...state.calendarAttendeeDrafts].map(item => item.id)
  if (allIds.some(id => !id) || new Set(allIds).size !== allIds.length) throw Error('Collaboration settings are invalid.')
  for (const draft of state.threadlineInviteDrafts) {
    if (!exactKeys(draft, ['id', 'recipientEmail', 'createdAt', 'delivery', 'createdBy']) ||
        normalizedEmail(draft.recipientEmail) !== draft.recipientEmail || !validDate(draft.createdAt) ||
        draft.delivery !== 'not-sent' || draft.createdBy !== 'account-owner') throw Error('Collaboration settings are invalid.')
  }
  for (const draft of state.calendarAttendeeDrafts) {
    if (!exactKeys(draft, ['id', 'recipientEmail', 'createdAt', 'featureStatus', 'invitation', 'createdBy']) ||
        normalizedEmail(draft.recipientEmail) !== draft.recipientEmail || !validDate(draft.createdAt) ||
        draft.featureStatus !== 'under-construction' || draft.invitation !== 'not-created' || draft.createdBy !== 'account-owner') {
      throw Error('Collaboration settings are invalid.')
    }
  }
  return structuredClone(state)
}

export function prepareThreadlineInvite(state: CollaborationSettingsState, input: { id: string; email: string; at: string }): CollaborationSettingsState {
  const current = validateCollaborationSettings(state)
  if (!input.id || [...current.threadlineInviteDrafts, ...current.calendarAttendeeDrafts].some(item => item.id === input.id) || !validDate(input.at)) throw Error('Invite draft identity and timestamp are required.')
  const draft: ThreadlineInviteDraft = { id: input.id, recipientEmail: normalizedEmail(input.email), createdAt: input.at, delivery: 'not-sent', createdBy: 'account-owner' }
  return validateCollaborationSettings({ ...current, threadlineInviteDrafts: [...current.threadlineInviteDrafts, draft] })
}

/** Records intent for UI continuity only. It cannot create or send a calendar invitation. */
export function prepareCalendarAttendeeDraft(state: CollaborationSettingsState, input: { id: string; email: string; at: string }): CollaborationSettingsState {
  const current = validateCollaborationSettings(state)
  if (!input.id || [...current.threadlineInviteDrafts, ...current.calendarAttendeeDrafts].some(item => item.id === input.id) || !validDate(input.at)) throw Error('Attendee draft identity and timestamp are required.')
  const draft: CalendarAttendeeDraft = { id: input.id, recipientEmail: normalizedEmail(input.email), createdAt: input.at,
    featureStatus: 'under-construction', invitation: 'not-created', createdBy: 'account-owner' }
  return validateCollaborationSettings({ ...current, calendarAttendeeDrafts: [...current.calendarAttendeeDrafts, draft] })
}
