import { describe, expect, it } from 'vitest'
import { betaLandingVisibility, readBetaLandingInput, shouldShowBetaLanding, BETA_LANDING_DISMISSED_KEY } from './betaLanding'

const signedOut = { status: 'signed-out' as const }
describe('beta landing visibility', () => {
  it('shows a new configured visitor the landing', () => expect(betaLandingVisibility({ auth: signedOut, hasLocalWork: false, dismissed: false })).toBe('landing'))
  it('keeps returning local users in the app', () => expect(shouldShowBetaLanding({ auth: signedOut, hasLocalWork: true, dismissed: false })).toBe(false))
  it('never shows for signed-in users', () => expect(betaLandingVisibility({ auth: { status: 'signed-in' }, hasLocalWork: false, dismissed: false })).toBe('app'))
  it('keeps auth-unconfigured deployments usable', () => expect(betaLandingVisibility({ auth: { status: 'unconfigured' }, hasLocalWork: false, dismissed: false })).toBe('app'))
  it('honors a recorded dismissal', () => expect(betaLandingVisibility({ auth: signedOut, hasLocalWork: false, dismissed: true })).toBe('app'))
  it('waits while the session is loading', () => expect(betaLandingVisibility({ auth: { status: 'loading' }, hasLocalWork: false, dismissed: false })).toBe('loading'))
  it('keeps an auth error visible for accessible failure copy', () => expect(betaLandingVisibility({ auth: { status: 'error' }, hasLocalWork: false, dismissed: false })).toBe('landing'))
  it('reads only the presence of saved work and dismissal', () => {
    const storage = new Map([[BETA_LANDING_DISMISSED_KEY, 'dismissed'], ['thoughtflow-state-v1', JSON.stringify({ objects: [], canvas: [{ id: 'canvas' }] })]])
    expect(readBetaLandingInput({ getItem: key => storage.get(key) ?? null }, signedOut)).toEqual({ auth: signedOut, hasLocalWork: true, dismissed: true })
  })
  it('does not route unreadable existing state through onboarding', () => {
    expect(readBetaLandingInput({ getItem: key => key === 'thoughtflow-state-v1' ? '{not-json' : null }, signedOut).hasLocalWork).toBe(true)
  })
})
