export type BetaAuthenticationState = 'signed-in' | 'signed-out'
export type BetaEntryDestination = 'landing' | 'tutorial' | 'home'

export interface BetaEntryInput {
  authenticationState: BetaAuthenticationState
  hasLocalCaptures: boolean
  completedOnboardingVersion: number | null
  currentOnboardingVersion: number
  explicitlyChoseContinueLocally: boolean
}

export interface BetaEntryDecision {
  destination: BetaEntryDestination
  reason: string
  preserveLocalData: boolean
}

const isVersion = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value > 0

/**
 * Pure beta entry routing. It only describes the next screen; it does not
 * inspect, write, migrate, or otherwise mutate local or account data.
 */
export function coordinateBetaEntry(input: BetaEntryInput): BetaEntryDecision {
  const preserveLocalData = input.authenticationState === 'signed-in' ||
    input.hasLocalCaptures || input.explicitlyChoseContinueLocally

  // A signed-out user must make an explicit choice before leaving captures
  // behind. This branch intentionally precedes onboarding evaluation.
  if (input.authenticationState === 'signed-out' && input.hasLocalCaptures && !input.explicitlyChoseContinueLocally) {
    return {
      destination: 'landing',
      reason: 'Local captures need a safe sign-in or explicit local continuation choice.',
      preserveLocalData: true,
    }
  }

  // Landing is also the neutral first-visit entry point. A signed-out user
  // reaches the local tutorial only after explicitly choosing local use.
  if (input.authenticationState === 'signed-out' && !input.explicitlyChoseContinueLocally) {
    return {
      destination: 'landing',
      reason: 'Choose sign-in or explicitly continue locally before entering the beta.',
      preserveLocalData,
    }
  }

  if (!isVersion(input.currentOnboardingVersion) ||
      (input.completedOnboardingVersion !== null && !isVersion(input.completedOnboardingVersion))) {
    return {
      destination: 'tutorial',
      reason: 'The onboarding version is unavailable or malformed; show the tutorial safely.',
      preserveLocalData,
    }
  }

  if (input.completedOnboardingVersion !== null && input.completedOnboardingVersion >= input.currentOnboardingVersion) {
    return {
      destination: 'home',
      reason: 'The current onboarding version is already complete.',
      preserveLocalData,
    }
  }

  return {
    destination: 'tutorial',
    reason: input.authenticationState === 'signed-in'
      ? 'This signed-in user has not completed the current onboarding version.'
      : 'A new local user should see the current onboarding tutorial.',
    preserveLocalData,
  }
}

// Descriptive alias for callers that prefer a decision-oriented name.
export const decideBetaEntry = coordinateBetaEntry
