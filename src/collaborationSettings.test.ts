import { describe, expect, it } from 'vitest'
import {
  collaborationFeatureStatus, emptyCollaborationSettings, prepareCalendarAttendeeDraft, prepareThreadlineInvite,
  validateCollaborationSettings,
} from './collaborationSettings'

describe('collaboration settings foundation', () => {
  it('stores normalized product invite drafts without claiming delivery', () => {
    const state = prepareThreadlineInvite(emptyCollaborationSettings(), {
      id: 'invite-1', email: ' Dario@Example.COM ', at: '2026-09-23T10:00:00.000Z',
    })
    expect(state.threadlineInviteDrafts).toEqual([{
      id: 'invite-1', recipientEmail: 'dario@example.com', createdAt: '2026-09-23T10:00:00.000Z', delivery: 'not-sent', createdBy: 'account-owner',
    }])
    expect(collaborationFeatureStatus.threadlineInvites.canSend).toBe(false)
    expect(validateCollaborationSettings(state)).toEqual(state)
  })

  it('marks calendar attendee intent as under construction and never creates an invitation', () => {
    const state = prepareCalendarAttendeeDraft(emptyCollaborationSettings(), {
      id: 'attendee-1', email: 'dario@example.com', at: '2026-09-23T10:00:00.000Z',
    })
    expect(state.calendarAttendeeDrafts[0]).toMatchObject({ featureStatus: 'under-construction', invitation: 'not-created' })
    expect(collaborationFeatureStatus.calendarAttendees).toMatchObject({ status: 'under-construction', canSend: false })
  })

  it('rejects invalid emails, duplicate identities and states that imply delivery', () => {
    expect(() => prepareThreadlineInvite(emptyCollaborationSettings(), { id: 'x', email: 'not-an-email', at: '2026-09-23T10:00:00.000Z' })).toThrow('valid email')
    const state = prepareThreadlineInvite(emptyCollaborationSettings(), { id: 'x', email: 'a@example.com', at: '2026-09-23T10:00:00.000Z' })
    expect(() => prepareCalendarAttendeeDraft(state, { id: 'x', email: 'b@example.com', at: '2026-09-23T10:00:00.000Z' })).toThrow('identity')
    expect(() => validateCollaborationSettings({ ...state, threadlineInviteDrafts: [{ ...state.threadlineInviteDrafts[0], delivery: 'sent' }] })).toThrow('invalid')
    expect(() => validateCollaborationSettings({ ...state, threadlineInviteDrafts: [{ ...state.threadlineInviteDrafts[0], sentAt: '2026-09-23T10:01:00.000Z' }] })).toThrow('invalid')
  })
})
