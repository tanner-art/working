/**
 * UI-free, deterministic acceptance manifest for the friends-and-family week.
 *
 * This is a checklist description, not a browser runner. Placeholders are
 * deliberately content-free so the manifest can be shared without account
 * credentials, private captures, or claims about live service state.
 */

export const SMOKE_PLACEHOLDERS = {
  email: '<TEST_EMAIL>',
  code: '<TEST_NUMERIC_CODE>',
  capture: '<CAPTURE_PLACEHOLDER>',
  canvasTitle: '<CANVAS_TITLE_PLACEHOLDER>',
} as const

export type BetaSmokeArea =
  | 'auth'
  | 'local'
  | 'capture'
  | 'review'
  | 'calendar'
  | 'canvas'
  | 'install'
  | 'resilience'
  | 'ai'

export interface BetaSmokeScenario {
  readonly id: string
  readonly area: BetaSmokeArea
  readonly daily: boolean
  readonly preconditions: readonly string[]
  readonly steps: readonly string[]
  readonly expectedOutcomes: readonly string[]
}

const scenario = (
  id: string,
  area: BetaSmokeArea,
  daily: boolean,
  preconditions: readonly string[],
  steps: readonly string[],
  expectedOutcomes: readonly string[],
): BetaSmokeScenario => ({ id, area, daily, preconditions, steps, expectedOutcomes })

/** Stable order is intentional: it is the order used for a daily walkthrough. */
export const BETA_SMOKE_MANIFEST: readonly BetaSmokeScenario[] = [
  scenario('auth-landing-sign-in-link', 'auth', true,
    ['Start signed out on the landing surface.', 'Use only the reserved <TEST_EMAIL> placeholder.'],
    ['Request an email sign-in link for <TEST_EMAIL>.', 'Follow the link from the test mailbox.'],
    ['The session is signed in.', 'The flow does not expose or store a credential in this manifest.']),
  scenario('auth-sign-in-numeric-code', 'auth', true,
    ['A sign-in email has been requested for <TEST_EMAIL>.'],
    ['Enter <TEST_NUMERIC_CODE> in the numeric-code field.', 'Submit the code.'],
    ['A valid test code signs in; an invalid or expired code remains recoverable.', 'The code is never hardcoded as an actual value here.']),
  scenario('local-continue-without-account', 'local', true,
    ['Start signed out with a local capture available.'],
    ['Choose Continue locally.', 'Reload the local workspace.'],
    ['The local workspace opens and the capture remains available.', 'No account sync is implied.']),
  scenario('capture-tutorial-skip-or-complete', 'capture', true,
    ['Open the first-run capture tutorial.'],
    ['Choose either Skip or complete every tutorial step.', 'Create one capture using <CAPTURE_PLACEHOLDER>.'],
    ['Both paths reach capture successfully.', 'The original capture is retained for later review.']),
  scenario('capture-persistence-after-refresh', 'capture', true,
    ['Create a local capture with <CAPTURE_PLACEHOLDER>.'],
    ['Refresh the workspace.', 'Reopen the capture.'],
    ['The same capture is present after refresh.', 'The test does not require private capture text.']),
  scenario('review-confirmation-preserves-capture', 'review', true,
    ['Have an interpretation in Review for <CAPTURE_PLACEHOLDER>.'],
    ['Inspect the proposed meaning.', 'Explicitly confirm the intended consequential interpretation.', 'Reopen its source capture.'],
    ['Confirmation is a discrete user action.', 'The original capture and interpretation history remain available.']),
  scenario('calendar-day-week-commitment-entry', 'calendar', true,
    ['Open Calendar with no assumed external events.'],
    ['Switch to Day, then Week.', 'Enter a commitment from Calendar.', 'Leave it unscheduled unless a separate scheduling confirmation is made.'],
    ['Day and Week views show their respective time grids.', 'The commitment is distinct from a CalendarEvent and is not assigned an invented time.']),
  scenario('canvas-create-edit-exit', 'canvas', true,
    ['Open the Canvas Bank.'],
    ['Create a canvas named <CANVAS_TITLE_PLACEHOLDER>.', 'Edit its content.', 'Exit to the Bank and reopen it.'],
    ['The named canvas and edit persist.', 'Leaving the canvas does not discard the current saved state.']),
  scenario('install-refresh-update-boundary', 'install', false,
    ['Use the installed-app test device and a known test build.'],
    ['Refresh the installed app.', 'Open the available update path when the platform offers one.', 'Return to the workspace.'],
    ['The app returns to a usable workspace.', 'The checklist records observed build behavior only; it asserts no unfinished deployment or release status.']),
  scenario('offline-recovery', 'resilience', true,
    ['Have a locally persisted workspace and a deterministic test network toggle.'],
    ['Make the network unavailable.', 'Open or edit the local workspace.', 'Restore the network and retry the deferred operation.'],
    ['Local work remains readable offline.', 'The failure is explicit and recoverable.', 'Recovery does not fabricate a successful remote write.']),
  scenario('ai-deterministic-fallback', 'ai', true,
    ['Provider-backed interpretation is disabled or unavailable.', 'Use <CAPTURE_PLACEHOLDER>.'],
    ['Request interpretation.', 'Observe the built-in deterministic result.'],
    ['A deterministic interpretation is returned.', 'Provider outage or disabled configuration does not block capture.', 'Consequential meaning remains subject to Review confirmation.']),
  scenario('ai-provider-interpretation-when-enabled', 'ai', false,
    ['The provider feature flag is explicitly enabled.', 'Use a non-sensitive <CAPTURE_PLACEHOLDER>.'],
    ['Request interpretation.', 'Validate the provider result.', 'Review and explicitly confirm any consequential meaning.'],
    ['A valid provider proposal is observable only when the flag is enabled.', 'Malformed, failed, or unavailable provider responses fall back deterministically.', 'No provider credential or fabricated live status is asserted.']),
] as const

export const betaSmokeManifest = BETA_SMOKE_MANIFEST

export function filterBetaSmokeByArea(
  manifest: readonly BetaSmokeScenario[],
  area: BetaSmokeArea,
): BetaSmokeScenario[] {
  return manifest.filter(item => item.area === area)
}

/** Returns a new array in manifest order; neither the manifest nor scenarios mutate. */
export function dailyBetaSmokeSubset(
  manifest: readonly BetaSmokeScenario[] = BETA_SMOKE_MANIFEST,
): BetaSmokeScenario[] {
  return manifest.filter(item => item.daily)
}
