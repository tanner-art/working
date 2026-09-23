import type { AuthState } from './auth'

export const BETA_LANDING_DISMISSED_KEY = 'threadline-beta-landing-dismissed-v1'
const LOCAL_STATE_KEY = 'thoughtflow-state-v1'

export type BetaLandingVisibility = 'landing' | 'app' | 'loading'

export interface BetaLandingInput {
  auth: Pick<AuthState, 'status'>
  hasLocalWork: boolean
  dismissed: boolean
}

/** Pure routing decision for the friends-and-family entry experience. */
export function betaLandingVisibility(input: BetaLandingInput): BetaLandingVisibility {
  if (input.auth.status === 'loading') return 'loading'
  if (input.auth.status === 'signed-in' || input.auth.status === 'unconfigured') return 'app'
  if (input.hasLocalWork || input.dismissed) return 'app'
  return 'landing'
}

export const shouldShowBetaLanding = (input: BetaLandingInput) => betaLandingVisibility(input) === 'landing'

/** Read-only browser snapshot used by the app gate; it never creates or changes app data. */
export function readBetaLandingInput(storage: Pick<Storage, 'getItem'>, auth: Pick<AuthState, 'status'>): BetaLandingInput {
  let hasLocalWork = false
  let dismissed = false
  try {
    const raw = storage.getItem(LOCAL_STATE_KEY)
    // Any existing state record belongs to a returning local user. If it is
    // malformed, the app's own recovery screen must remain reachable.
    hasLocalWork = raw !== null
    if (raw) {
      const saved = JSON.parse(raw) as { objects?: unknown[]; canvas?: unknown[] }
      hasLocalWork = (Array.isArray(saved.objects) && saved.objects.length > 0) ||
        (Array.isArray(saved.canvas) && saved.canvas.length > 0) || raw.length > 0 && !Array.isArray(saved.objects) && !Array.isArray(saved.canvas)
    }
    dismissed = storage.getItem(BETA_LANDING_DISMISSED_KEY) === 'dismissed'
  } catch {
    // A blocked or unreadable browser store must not prevent local-first use or
    // route a returning user through onboarding.
    hasLocalWork = true
  }
  return { auth, hasLocalWork, dismissed }
}
