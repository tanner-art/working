# Reviewed Beta PR Stack Integration Plan

This plan covers the reviewed beta stack for GitHub issue #136. It is an integration
plan only: it does not claim that any listed PR is merged, deployed, or live. The
runner owns branch operations, commits, CI, and draft-PR mechanics. A human must
explicitly approve every merge to `main` and the final primary-URL promotion.

## Integration rules

1. Start from the current reviewed base and record the exact head SHA of every PR.
   Do not merge a PR whose review head changed without re-reviewing its diff.
2. Land one PR at a time in the order below. After each merge, rebase every
   remaining branch onto the new `main`, resolve conflicts on that branch, and run
   that branch's focused validation before considering it ready again.
3. Preserve the existing local-first/account boundaries: no step may clear local
   captures, silently copy data into an account, weaken RLS/account ownership, or
   convert provider-backed AI from Preview to Production.
4. Treat a conflict as a design decision, not a textual merge exercise. Keep the
   current behavior unless the reviewed PR explicitly owns the change, and record
   any unresolved product question as follow-up work rather than broadening this
   stack.
5. Do not put credentials, provider keys, account identifiers, magic-link codes,
   or private URLs in source, this plan, screenshots, or smoke results.

## Safe landing order

| Order | PR | Slice | Integration dependency and conflict rule | Focused validation before the next landing |
| --- | --- | --- | --- | --- |
| 1 | #112 | Landing/sign-in baseline | Establish the beta entry and authentication contract first. Preserve both browser-link sign-in and installed-phone code sign-in, plus local-data preservation. Resolve `App.tsx` auth/settings changes against the existing `useAuthState`, account open/load/copy/merge controls, and session-change guard. | Typecheck/build; auth unit tests; browser checks for signed-out, code-entry-visible, signed-in, sign-out, and unconfigured states; verify no local capture is lost on auth transitions. |
| 2 | #111 | Tutorial | Rebase onto #112. Tutorial may explain the already-landed entry/sign-in path, but must not own auth state or duplicate routing. Keep it dismissible/reopenable without overwriting settings or captures. | Typecheck/build; tutorial tests if present; desktop and 390px browser smoke for first visit, dismiss, reopen, refresh, and sign-in entry. |
| 3 | #128 | Entry-flow coordinator | Rebase onto #112+#111 and make this the single coordinator for initial entry, tutorial, sign-in, and beta routing. Remove competing entry decisions only when the PR owns them; retain the existing app's recovery/account guards. `App.tsx` is the highest-risk conflict here. | Typecheck/build; route/entry tests; fresh local storage and returning-user browser smoke; sign-in handoff smoke; verify tutorial does not block recovery or account settings. |
| 4 | #134 | Beta-home model | Rebase onto the coordinator. Adopt the model as the source for beta-home state, but keep pure data/model logic separate from `App.tsx`; do not duplicate navigation or persistence side effects. Resolve home composition and shared layout styles deliberately. | Model unit tests; typecheck/build; browser smoke for beta home, Today, Capture, Organize, Calendar, Bank, Settings, and return navigation; verify existing local and account data remains addressable. |
| 5 | #119 | Diagnostics | Rebase onto the beta-home model. Diagnostics should be additive and read-only at the UI boundary; prefer a pure module for status/normalization/summary calculations. It must not log secrets or change provider/account behavior. | Diagnostics unit tests with configured, missing, failing, and offline inputs; typecheck/build; browser check that diagnostics render without blocking normal entry and do not expose sensitive values. |
| 6 | #120 | PWA update lifecycle | Rebase after diagnostics. Keep lifecycle code at `src/main.tsx`/`public/sw.js` boundaries and avoid putting service-worker registration or update state into the home model. Preserve network-first HTML, hashed-asset caching, API bypass, and local data. | Typecheck/build; service-worker/static inspection; production-mode browser smoke for registration, reload/update notice if applicable, offline shell fallback, API non-caching, and preservation of local storage across an update. |
| 7 | #121 | Feedback | Rebase after the PWA lifecycle. Keep feedback capture isolated from core object/account writes; if it is a form, it must have explicit submit/failure states and must not include secrets by default. Treat its calculation/serialization/validation as a pure module where possible. | Feedback validation/unit tests; typecheck/build; browser smoke for open, cancel, validation error, successful submit path, retry/failure path, and navigation back to the beta home. |
| 8 | #132 | Smoke manifest | Rebase after feedback. This is a validation artifact, not a product-route owner. Keep the manifest executable against the final beta surfaces and make each check safe for existing data. Do not turn smoke checks into destructive setup. | Manifest/schema or script validation; typecheck/build if code is touched; run the focused smoke paths on desktop and an installed phone without clearing storage or uninstalling the existing app. |
| 9 | #127 | Beta-week runbook | Rebase after the smoke manifest so the runbook names the final checks and current gates. Documentation-only changes should remain pure and must not introduce operational claims that were not observed. | Markdown/link/spelling check as configured; compare every runbook check with the smoke manifest; confirm no secrets, “merged,” “live,” or unverified deployment claims are present. |
| 10 | #123 | AI Gateway | Land last, after the beta shell and its evidence are stable. Keep the gateway/server boundary separate from client code: server-only key, explicit success/failure behavior, deterministic fallback, and Preview-only activation. No Production flag or primary-URL promotion is implied by merging this PR. | API/typecheck/build; direct Preview endpoint checks for success, missing-key `503`, induced provider failure, and deterministic fallback; inspect the client bundle for absence of the server key; run beta smoke with AI disabled and Preview-enabled separately. |

## Pure-module slices and boundaries

The following should remain pure or as close to pure as their reviewed diffs allow:

- #134's beta-home model: state derivation and view-model construction should be
  testable without browser globals, storage, auth, or network calls.
- #119 diagnostics: normalize and classify inputs without logging secrets or
  mutating account/local state.
- #121 feedback validation/serialization: validate and construct the payload in a
  pure module; keep transport and UI submission state at the boundary.
- #132 smoke manifest: declarative checks and selectors; no destructive data setup.
- #127 runbook: documentation only.
- #123 gateway request/response normalization where applicable: server transport
  may be effectful, but provider selection and safe fallback decisions should be
  independently testable.

#111 and #128 necessarily touch entry composition. #112, #120, and any PR that
changes settings or lifecycle behavior may cross `App.tsx`; isolate new logic in
modules/hooks/components so the coordinator does not become a second persistence
or auth implementation.

## `App.tsx` and `styles.css` conflict map

### `src/App.tsx`

The file currently combines the root `App`, account subscription, local/cloud
loading and saving, merge-preview safeguards, install help, navigation, page
composition, settings, AI status, and object workflows. Expect conflicts in:

- imports and root-level configuration;
- `View`/navigation definitions and the `ThreadlineApp` props;
- `useAuthState`, account session guards, and initial loading/error branches;
- install-help state and Settings sections;
- the main page switch and route-level action handlers;
- AI/provider status and any new entry coordinator.

Resolve by retaining one owner for each concern. The entry coordinator owns entry
decisions; auth owns auth state; account storage owns account reads/writes; the
PWA lifecycle owns registration/update behavior; AI gateway code owns server
transport. Keep local capture/export/recovery and explicit account copy/load/merge
behavior intact.

### `src/styles.css`

This is a shared global surface. Conflicts are likely around app shell/sidebar,
page headers, settings cards, install help, mobile media queries, modal/panel
layers, status/feedback states, and any beta-home additions. Preserve existing
focus-visible, responsive, dialog, and destructive-action styles. Prefer scoped
class names for new surfaces, do not silently change global selectors, and check
both desktop and 390px layouts after every style-bearing rebase.

## Rebase and validation protocol

After each approved merge, stop the stack, update the base, and rebase the next
branch before more integration work. For each rebased branch:

1. Inspect the diff and confirm that conflict resolution did not remove a tested
   behavior or add unrelated scope.
2. Run the smallest relevant unit tests plus TypeScript/build checks for the
   changed surface. Run lint only if the repository adds/configures it; there is
   currently no lint script in `package.json`.
3. Run the focused browser/device checks in the order table.
4. Record the base SHA, branch SHA, validation result, known limitation, and the
   next required rebase. Do not call a PR integrated merely because it compiles.

The shared full `pnpm check` is intentionally left to the runner after agent
execution. This document task requires only focused documentation validation.

## Required beta gates

### Preview-only AI activation

AI Gateway evaluation may be enabled only in a Vercel Preview environment after
the server-only key is configured outside the client bundle and the endpoint has
passed success, missing-key, and induced-failure checks. Production remains on
the deterministic/built-in path until a separate explicit promotion decision.
Never expose the provider key through a `VITE_` variable, source, logs, this
document, screenshots, or diagnostics. A Preview success is evidence for review,
not authorization to enable the primary URL.

### Installed-phone smoke

Use the existing installed iPhone PWA and preserve its data. Do not uninstall it,
clear browser storage, or share a sign-in code. On the Preview/staged URL, verify:

1. launch from the home-screen icon and complete email-code sign-in in the app;
2. confirm signed-in and sign-out states, then separately verify the browser link;
3. confirm local captures remain available and account data still requires an
   explicit copy/load action;
4. exercise entry/tutorial/home, Capture, Organize/Review, Bank, Settings,
   feedback, and the relevant diagnostics/update messaging;
5. verify an update/reload does not erase local data and that offline shell
   behavior is safe;
6. record device/browser/Preview build identifiers without recording credentials,
   email codes, or private account data.

### Final primary-URL promotion gate

Promotion to the primary URL is a separate human decision after all listed PRs
have been individually reviewed and integrated. The gate is closed unless all of
the following are true:

- the user explicitly approves merging the final reviewed stack to `main`;
- focused validations and the runner-owned shared-lock validation pass;
- the smoke manifest and beta-week runbook agree with the tested build;
- installed-phone sign-in and core beta flows pass without data loss;
- account isolation/copy-load behavior remains explicit and safe;
- AI remains disabled on Production, or a separate explicit Production AI
  promotion has been approved after the Preview evidence;
- no unresolved `App.tsx`, `styles.css`, PWA, auth, or data-ownership conflict
  remains;
- the user explicitly approves promotion of the selected build to the primary URL.

Until that approval, report the build as staged/Preview-only and do not describe
the PRs as merged or the beta as live.
