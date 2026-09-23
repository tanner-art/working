import { describe, expect, it } from 'vitest'
import { coordinateBetaEntry, type BetaEntryInput } from './betaFlow'

const base = (overrides: Partial<BetaEntryInput> = {}): BetaEntryInput => ({
  authenticationState: 'signed-out',
  hasLocalCaptures: false,
  completedOnboardingVersion: null,
  currentOnboardingVersion: 2,
  explicitlyChoseContinueLocally: false,
  ...overrides,
})

describe('beta entry flow', () => {
  it('sends a first visit to landing without claiming local data must be preserved', () => {
    expect(coordinateBetaEntry(base())).toEqual({
      destination: 'landing',
      reason: 'Choose sign-in or explicitly continue locally before entering the beta.',
      preserveLocalData: false,
    })
  })

  it('sends a signed-in first run to tutorial and preserves local data', () => {
    expect(coordinateBetaEntry(base({ authenticationState: 'signed-in' }))).toMatchObject({
      destination: 'tutorial',
      preserveLocalData: true,
    })
  })

  it('sends a returning signed-in user with current onboarding to home', () => {
    expect(coordinateBetaEntry(base({
      authenticationState: 'signed-in', completedOnboardingVersion: 2,
    }))).toMatchObject({ destination: 'home', preserveLocalData: true })
  })

  it('lets an explicit local continuation enter the tutorial safely', () => {
    expect(coordinateBetaEntry(base({
      hasLocalCaptures: true, explicitlyChoseContinueLocally: true,
    }))).toMatchObject({ destination: 'tutorial', preserveLocalData: true })
  })

  it('keeps unsynced local captures on preservation-safe landing', () => {
    expect(coordinateBetaEntry(base({ hasLocalCaptures: true }))).toMatchObject({
      destination: 'landing', preserveLocalData: true,
    })
  })

  it('shows tutorial for a stale onboarding version', () => {
    expect(coordinateBetaEntry(base({ authenticationState: 'signed-in', completedOnboardingVersion: 1 }))).toMatchObject({
      destination: 'tutorial', preserveLocalData: true,
    })
  })

  it('fails safely to tutorial for malformed versions', () => {
    expect(coordinateBetaEntry(base({ authenticationState: 'signed-in', currentOnboardingVersion: Number.NaN }))).toMatchObject({ destination: 'tutorial' })
    expect(coordinateBetaEntry(base({ explicitlyChoseContinueLocally: true, completedOnboardingVersion: 1.5 }))).toMatchObject({ destination: 'tutorial' })
  })

  it('does not mutate its input', () => {
    const input = base({ hasLocalCaptures: true })
    const before = structuredClone(input)
    coordinateBetaEntry(input)
    expect(input).toEqual(before)
  })
})
