# Threadline Task Board

## Task Lifecycle

BACKLOG -> READY -> IN_PROGRESS -> REVIEW -> MERGE_READY -> DONE

A task may move from REVIEW to CHANGES_REQUESTED and then back to IN_PROGRESS.

Only READY tasks may be newly assigned.

## Rules

- One implementation owner per task.
- One task has explicit scope.
- Agents cannot expand their own scope.
- Newly discovered work becomes a proposed new task.
- Dependencies must be satisfied before READY.
- Product decisions are recorded in docs/DECISIONS.md.
- Architecture changes require explicit assignment.
- Completion requires a commit SHA.
- Author and reviewer should normally be different agents.

---

## Current Product Operating Focus

Every new task should explicitly serve at least one near-term product outcome: fast capture, safe user data, confirm/organize meaning, mobile usability, or real AI interpretation. Prefer tasks that move the hosted app toward immediate daily use within 24 hours over low-priority polish. Larger ideas such as AI folder clustering, resource cost, attention load, ROI, and strategic importance should be captured as follow-ups unless they directly unblock the current capture/review/storage loop.

For the next 24-hour push, tasks should be framed around making the hosted mobile app feel usable by a real account holder: capture should be quick and rewarding, review/organize should let the user safely confirm or remove proposed meaning, account storage should keep data tied to the signed-in user, and AI interpretation should start replacing deterministic placeholders. Process/documentation work is valid only when it helps agents or the user move those outcomes faster.

Build-in-public rule: when a task changes visible behavior, its issue/PR should include one plain-language user-facing note that can be reused for a public progress update, plus the usual validation and `Exact response to move forward`. Keep the note honest: describe what users can do now, what is still limited, and the next visible improvement.

## IN_PROGRESS

### TASK-044 - Guided Cross-Device Account Merge

Status: IN_PROGRESS
Owner: Orchestrator
Reviewer: Pending independent review
Depends On: TASK-042

Scope:

- add a user-initiated merge path for combining this device's preserved local data with an existing signed-in account snapshot
- preview additions and conflicts before the user confirms any account write
- preserve distinct captures, interpretations, semantic objects, relationships, calendar events, canvas elements and temporal history from both snapshots
- deduplicate records only when their stable IDs and contents agree; conflicting reuse of an ID must stop the merge and leave both sources untouched
- keep the local browser copy and downloadable exports intact as recovery paths
- update the account through the existing revision guard so another device cannot be overwritten by a stale merge
- add focused tests for disjoint data, exact duplicates, conflicting IDs, settings/digest choices, canvas/history preservation and stale-write failure

Non-goals:

- background or realtime synchronization
- silently merging at sign-in or import
- guessing whether differently identified thoughts describe the same real-world idea
- deleting either device's local data or replacing an account without explicit confirmation

Acceptance:

- a user with different Mac and phone histories can preview and explicitly combine them into one account
- distinct thoughts from both snapshots remain available in Review and Bank after roundtrip
- exact duplicates are not doubled, ambiguous/conflicting identities fail closed, and no source snapshot is mutated
- the confirmed merge uses the latest loaded account revision and preserves the existing stale-write protections
- relevant tests, TypeScript, API typecheck, production build and diff check pass

Build-in-public note: Threadline is adding a safe way to combine ideas captured on two devices. The merge will show what it can add, stop on identity conflicts, and keep both original device copies as recovery backups.

Exact response to move forward: Independently review TASK-044's merge rules and UI, then run the two-export Mac-and-iPhone smoke flow before merge.

### TASK-045 - Pin AI Interpretation to Haiku

Status: DONE
Owner: Orchestrator
Reviewer: Independent review approved with no findings
Depends On: TASK-031

Scope: Pin every provider-backed Threadline interpretation request to Anthropic Haiku and
remove the server environment override that could silently select a larger model. Keep the
API key server-only, preserve the existing Review and failure boundaries, document the cost
control, and add a request-level regression test proving the provider payload names Haiku.

Acceptance: `/api/interpret` always requests `claude-haiku-4-5-20251001`; neither client input
nor Vercel environment variables can select Sonnet or Opus; relevant tests, TypeScript, API
typecheck, production build and diff check pass.

Build-in-public note: Threadline's routine thought interpretation is pinned to Haiku to keep
responses fast and API costs predictable. Larger Claude models cannot be selected through a
deployment setting.

Exact response to move forward: Independently review TASK-045's provider payload and verify a
fresh Vercel Preview call reports a successful structured interpretation before enabling the
browser feature flag.

Delivery: merged to main via PR #66 at commit 6e603e7 after independent approval. `pnpm check`
passed with 354 tests across 19 files, TypeScript, API typecheck and production build;
`git diff --check` passed. Live Preview validation remains pending Vercel reauthentication.

### TASK-042 - Signed-in Account Storage Backbone

Status: REVIEW
Owner: Codex A
Reviewer: Pending independent runner review
GitHub Issue: #60
Scope: user-assigned account storage slice, restricted to the supplied allowlist.

Result: Added a client-only Supabase account adapter sharing the auth client, with an
explicit non-secret table-name configuration. Settings → Data offers create-only local
import and confirmed account load. Sign-in never migrates data. Account activation leaves
local storage intact; subsequent edits save a single versioned account document containing
the unchanged persisted model, settings and digest preference. Review and Bank share that
model. Revision guards reject stale writes; failed saves pause automatic retries with
export/retry guidance. Account changes pause editing, and returning to local mode restores
the original device data. Serialization preserves intermediate evidence revisions.

Validation: `pnpm check` passed: 300 tests across 17 files, TypeScript and production
build passed. No lint script is configured. `git diff --check` passed and the final implementation/test/doc diffs were inspected. Existing nonblocking production bundle-size warning remains.

Files: src/App.tsx, src/auth.ts, src/auth.test.ts, src/store.ts, src/store.test.ts,
src/accountStorage.ts, src/accountStorage.test.ts, TASKS.md, docs/AUTH_DATA_PLAN.md.

Limitations: Hosted Supabase/RLS and browser/mobile smoke validation are pending. No
credentials or project identifiers were accessed or added. This slice uses explicit reload
and revision conflicts, not realtime merge. Import refuses nonempty accounts; unsaved cloud
edits require export before reload. There is no durable offline account cache. Account-mode
digest preference syncs and the digest opens on demand; scheduled account notices are not
wired because the existing digest component writes directly to local storage. Local digest
behavior remains unchanged. See AUTH_DATA_PLAN.md for generic table/RLS setup and details.

Newly discovered work (not implemented; does not block snapshot storage): adapt the existing
digest UI to injected account persistence, and add a guided merge for nonempty accounts.
Reconcile overlapping TASK-034–036 backlog scopes before assigning additional storage work.

Build-in-public note: Copy this device’s thoughts into your account, then explicitly load
them on your phone with Review, Bank folders and preferences intact. Local data is preserved
and competing saves produce a recoverable error. Hosted two-device validation comes next.

Exact response to move forward: Run independent review and hosted two-account/two-device
smoke checks using the generic RLS/table contract in docs/AUTH_DATA_PLAN.md. Verify explicit
import/load, Review/Bank roundtrip, denied access, offline/conflict recovery, exports and
sign-out/local preservation. The runner owns commit and PR delivery.

Delivery: changes left uncommitted for the runner; no git mutations, branch changes, push,
PR creation or merge performed.


### TASK-041 - Compact Digest, Review Accordion and Bank Folders

Status: REVIEW
Owner: Codex A
Reviewer: Pending independent runner review
GitHub Issue: #56
Scope: user-assigned mobile cleanup in the six explicitly allowed paths.

Result: Today has a compact Morning Digest label/caret disclosure that opens the
live digest inline in one tap, without delivery controls or an intermediate button.
The separate Settings digest surface retains existing delivery controls. Capture was
verified to have no forced context field or “Interpret thought” wording, keeps a primary
Capture button, and adds an optional Details drawer for folder/date/time on the way in.
Organize opens with a collapsed Review count/caret row, followed by Bank folders in
Personal, Business, Unfiled order. Confirmed/completed thoughts are grouped only by
exact, case-insensitive context values Personal/Home or Business/Work; other contexts
remain Unfiled. The detail editor now exposes Folder, Proposed date, Time and Effort up front,
with Status/Urgency under Advanced; time edits update only the proposed timing evidence
without replacing the interpretation summary. No AI inference, persisted folder schema or semantic membership was introduced.
Review cards keep Confirm/Edit and replace Reject with a top-right accessible X.
Dismissal requires a separate confirmation and uses existing reversible rejection
semantics, retaining raw captures and history across reload.

Validation: `pnpm check` passed: 282 tests across 15 files, TypeScript and production
Vite build after the Capture Details/time/folder patch. Ten new cases cover conservative classification, lifecycle exclusions,
context edits and persistence; existing rejection/reconsideration tests remain green.
`git diff --check` passed and implementation/test diffs inspected. No lint script is
configured. Production build retains the nonblocking bundle-size warning.

Files: src/App.tsx, src/DigestPanel.tsx, src/styles.css, src/objectWorkflow.ts,
src/objectWorkflow.test.ts, TASKS.md.
Limitations: browser/mobile interaction and independent review remain pending; there
is no DOM test dependency in this worktree. Folders are context-based views, not AI
filing; arbitrary contexts are deliberately unclassified. Archived, pending and
dismissed items are excluded from Bank. Dismissal preserves evidence rather than
permanently deleting it; this slice adds no dismissed-items recovery list.
Delivery: changes left uncommitted for the runner; no git mutations, branch changes,
push, PR creation or merge.

Build-in-public note: Today’s digest now opens inline, and Organize puts a small
Review drawer above Personal and Business folders. Junk proposals can be dismissed
with confirmation while keeping the original thought. Filing uses simple context
labels for now; the next visible check is the mobile interaction review.

Newly discovered work: none requiring implementation outside this assignment.

Exact response to move forward: Run independent review and mobile/desktop smoke
checks for issue #56: expand/collapse digest and Review, cancel/confirm X dismissal,
Confirm/Edit a card, verify folder counts/folder dropdown edits after reload, and check
Capture plus optional Details date/time/folder entry. Then deliver the recovered PR.


### TASK-040 - Settings as a Nontechnical Usability Control Center

Status: REVIEW
Owner: Claude
Reviewer: Pending independent runner review
Priority: P1
Milestone: M5
GitHub Issue: #53

Depends On:
- TASK-026 (settings/account shell), TASK-029 (Account login/logout shell)

Goal: Turn Settings into a place a nontechnical user can understand at a glance on mobile,
per the scope TASK-033/backlog described, without implying unbuilt features already work.

Scope: src/App.tsx, src/styles.css, src/auth.ts, src/auth.test.ts.

Result: Settings now renders explicit Account, Data, AI interpretation, Mobile install,
Digest and Recovery cards (plus the existing Local profile card), each with a status pill and
an honest next action. Account is unchanged functionally (existing Supabase login/logout
shell) but now shares one subscription with the new Data card via a `useAuthState` hook, so
retrying the account check and rendering "local-only vs signed-in" stay in sync. A new
`dataOwnershipLabel` helper in src/auth.ts states plainly that all data is local-only —
whether signed in or not — since cloud storage is not implemented (D-011/TASK-034 remain
separately scoped); it is used by both the Account and Data cards. AI interpretation shows
that only the built-in deterministic rules run today, with a disabled "Connect an AI
provider — not built yet" control (no provider wired, matching Do Not). Mobile install
detects standalone/home-screen display mode at render and shows "Installed" or, if not yet
installed, the exact Safari/Chrome add-to-home-screen steps inline — there is no separate
in-app onboarding wizard (no TASK-039/TASK-032 implementation exists in this repository; the
existing capability is the PWA manifest/service worker already shipped, documented in
docs/MOBILE_INSTALL.md) so the status reflects that honestly rather than claiming a walkthrough
exists. Digest stays out of Settings as a configurable feature (no delivery/notification
controls added, per user direction) but exposes an "Open Morning Digest" button to the
existing, already-working digest view reachable from Today — an existing safe surface, not a
new one. Recovery is the renamed former "Data controls" card (export/backup/clear-data) with
its behavior unchanged. No Supabase cloud storage, AI provider backend, notifications, or
account deletion were implemented.

Validation: Could not run `pnpm check` or `git diff --check` in this session — no shell/Bash
tool was available to this agent (the available tool set was Read/Edit/Write/Glob/Grep plus
unrelated MCP integrations). In lieu of executing the toolchain, the diff was inspected
manually: only the six allowed paths changed; `Grep` confirmed no trailing whitespace in any
edited file; the edited region was re-read in full to check JSX/TypeScript structure,
prop-drilling, and that every new identifier (`dataOwnershipLabel`, `useAuthState`,
`AuthState` type import, `DataSection`, `AiInterpretationSection`, `MobileInstallSection`,
`DigestSection`) is both defined and consumed with no leftover unused bindings. This is not a
substitute for the runner actually running `pnpm check`/`git diff --check`, which remain
required before this can move past REVIEW.

Limitations: TypeScript, the Vitest suite (including the two new `dataOwnershipLabel` cases
added to src/auth.test.ts) and the production build are unexecuted and unverified pending the
runner. No React/DOM testing library exists in this repo (documented limitation carried over
from TASK-020), and no `src/App.test.tsx` exists and it is outside this task's allowed paths,
so the new Settings cards have no automated render/interaction coverage — only the pure
`dataOwnershipLabel` helper is unit-tested. Browser/mobile smoke testing (including the
standalone-display-mode detection in the Mobile install card) was not performed. Mobile
install "Installed" detection relies on `display-mode: standalone`/`navigator.standalone`,
which only reflects the current browser tab's launch context, not whether the app has ever
been installed. TASK-034–037 (cloud storage, migration, sign-out/offline, export/delete) and
TASK-031 (real AI interpretation) remain unimplemented and unaffected by this task.
Delivery: changes left uncommitted for the runner; no git mutations, push, PR or branch change.

Build-in-public note: Settings is now a real status dashboard instead of a login box —
Account, Data, AI, Mobile install, Digest and Recovery each say plainly what's on, what's
local-only, and what to do next, with nothing claimed that isn't actually working yet.

### Exact response to move forward
Run `pnpm check` and `git diff --check`, do a mobile-width browser smoke test of the new
Settings cards (including toggling signed-in/out and installed/not-installed states), then
commit and route to independent review for issue #53.

### TASK-039 - First-Run Mobile Onboarding and Home Screen Install Help

Status: REVIEW
Owner: Codex A
Reviewer: Pending independent runner review
GitHub Issue: #52
Depends On: TASK-025, TASK-038 (existing install assets and mobile UI inspected).
Scope: explicitly assigned mobile usability slice; six allowed paths only. This
implements the onboarding/install-help slice also described in backlog TASK-032;
that older task's status and broader board priorities are left for the runner.

Result: Mobile browser launches (720px or narrower) show a lightweight inline
Capture/Organize introduction with expandable iPhone Safari home-screen steps.
Dismissal persists separately from the existing profile schema. Settings → Mobile
install reopens the guide on any device, with keyboard focus to its heading and
back to the opener on dismissal. Desktop and standalone launches skip automatic
help. Failed storage writes still allow session dismissal and display an honest
persistence warning. Export and confirmed local-data clearing include the new
preference; profile reset does not change it. Browser and standalone surfaces now
both respect safe-area insets for navigation, canvas, overlays and recovery pages.
No notification permission request, push delivery or native iOS code was added.

Validation (2026-09-15): `pnpm check` passed: 271 tests across 15 files, including
six focused onboarding preference tests, TypeScript and production Vite build.
Tests cover first visit, desktop/standalone suppression, persisted dismissal,
profile/data preservation, unknown values, blocked storage and confirmed clearing.
`git diff --check` passed; all implementation, tests and documentation diffs inspected.
No lint script is configured. Build retains the existing nonblocking bundle-size warning.

Files: src/App.tsx, src/styles.css, src/settings.ts, src/settings.test.ts,
docs/MOBILE_INSTALL.md, TASKS.md.
Limitations: no browser automation tool or installed browser test package is available
in this worktree. Real iPhone Safari/home-screen installation, portrait/landscape
camera inset checks and interactive desktop/mobile smoke checks remain for runner
review; the checklist is in docs/MOBILE_INSTALL.md. Mobile detection uses initial
viewport width rather than device identity; an installed app opened in a browser tab
may still offer help until dismissed. No cross-device preference sync or push support.
Delivery: left uncommitted for the runner; no git mutations, branch changes, push,
PR creation or merge.

Build-in-public note: Threadline now offers a small first-visit mobile guide with
iPhone home-screen instructions, a remembered dismissal and a Settings way back.
Safe-area spacing covers browser and home-screen layouts. Device verification is
still pending, and installation does not enable mobile push notifications.

Newly discovered work (not implemented; nonblocking): reconcile overlapping
TASK-032 with this assigned TASK-039 after independent review. No new product
features proposed in this slice.

Exact response to move forward: Run independent review and the mobile/desktop
smoke checklist for issue #52, then let the runner commit and prepare delivery.

---

### TASK-038 - Mobile-First Capture and Organize Cleanup

Status: DONE
Owner: Codex A
Reviewer: Independent orchestration review
Issue: #48 / PR #50
Scope: user-assigned capture/review cleanup in the explicitly allowed paths only.

Result: Capture keeps its raw-input heading, removes the lede/context field, uses a
Capture button, preserves new typing during asynchronous capture, clears submitted text,
and stays open with accessible success feedback. Account entry opens Settings;
Commitments navigation is hidden with implementation retained. Today has a compact
Morning digest entry opening the existing digest surface. Review is labeled Organize,
retains its pending-count badge, and requires a separate confirmation before rejection.
Rejected proposals leave the pending queue while preserving captures and history across
reload; type correction can return them to review. Confirm, Complete, Archive and detail
edits retain the existing explicit-confirmation rules, with a concise blocked-action reason.
Proposed date, urgency, effort and context remain editable; advanced estimate controls
are hidden without deleting saved metadata. Timing remains available in a disclosure.

Validation (2026-09-15/16): pnpm check passed: 265 tests across 15 files, TypeScript and
production build. Seven new regression cases cover rejection/reconsideration, confirmation,
completion/archive, editable-field persistence and confirmation gates across model reload.
git diff --check passed; implementation and test diffs inspected. GitHub Validate app checks
and Vercel preview passed before merge. No lint script configured. Build retains its
nonblocking bundle-size warning.

Files: src/App.tsx, src/styles.css, src/objectWorkflow.ts, src/objectWorkflow.test.ts, TASKS.md.
Limitations: rejection retains evidence; it is not permanent capture deletion. Existing
reminder proposals require reclassification before object confirmation. Digest details and
delivery logic are preserved on the separate digest surface. Full Organize folders, AI
clustering, and provider-backed interpretation remain follow-up work.
Delivery: merged to main via PR #50 at commit 25e7e146def759fd6c1e9a39edbb3d2b2126f045.

TODO / proposed follow-ups (not implemented; do not block this task): Organize folders;
future AI grouping/clustering; separately scoped resource cost, attention load, ROI and
strategic importance controls. Existing capture/provider and durable storage work remains
separately scoped.

Exact response to move forward: Continue with the next mobile usability slice: user-scoped
storage, real AI interpretation, and Organize folders.

---

### TASK-024 - Accessible Canvas Node Shape Palette

Status: REVIEW
Owner: Codex A
Reviewer: Pending independent runner review
Milestone: M4
Issue: #31
Depends On: merged TASK-021, TASK-022, TASK-023 (inspected at current main 1feb87a).

Scope: explicit creation and conversion of rectangle, rounded rectangle, ellipse, and
diamond visual blocks; accessible native selectors, responsive toolbar, shape rendering,
 geometry, group constraints, history, and persisted validation. Semantic kinds are unchanged.

Acceptance: preserve old saved canvases, content and IDs, resizing, connection styling and
boundary ports, undo/redo, group membership constraints, and mobile usability; meaningful
regression tests, pnpm check, and diff checks.

Result: added an optional visual shape field to text blocks, keeping the existing group
membership model. Converting a group to any block shape detaches its members; converting
a member to a group removes its membership. Shape-only changes retain membership.
Ellipse and diamond outlines use the full node bounds with a centered scrollable editor;
fixed bottom/top connector ports lie on every supported shape boundary. Native labeled
creation/conversion selectors support keyboard and touch; mobile tools scroll horizontally.
Legacy blocks retain their original appearance without adding shape metadata on load.

Validation (2026-09-14): pnpm check passed: 199 tests across 12 files, TypeScript, and
production build. git diff --check passed; implementation and test diffs inspected.
No lint script is configured. Only the eight assigned paths changed.

Limitations: browser/touch smoke testing and independent review remain pending; no browser
tool is available in this session. Fixed ports preserve existing routing behavior and do
not avoid overlapping nodes. Undo history remains session-only under D-010. Durable
canvas revisions remain separately scoped work. No new follow-up implementation added.
Delivery: changes left uncommitted for the runner, per user instruction; no git mutations.

---

### TASK-023 - Sticky Canvas Group Membership

Status: MERGE_READY
Owner: Codex B
Reviewer: Independent Codex review (approved)
Priority: P1
Milestone: M4

Goal: Let users explicitly attach text blocks to a canvas group so moving the group moves its members together.

Scope: explicit attach/detach controls; bulk attach of blocks fully inside a group; atomic group movement; resize, conversion, deletion, undo/redo, and persisted-state compatibility; accessible controls and focused tests. Canvas groups do not change semantic project membership.

Acceptance: legacy canvases remain valid; invalid or nested membership fails closed; group motion preserves relative member positions; resizing retains explicit membership; converting or deleting a group safely detaches its members; pnpm check and git diff --check pass.

Result: implementation commit dee16c3; TASK-022 integration merge commit 2b9d3fe. Independent review approved. Integration preserves both connection styling and sticky groups; pnpm check passed with 187 tests, TypeScript, and production build, and git diff --check passed.

---

### TASK-022 - Rich Canvas Connection Styling

Status: REVIEW
Owner: Codex canvas-edges
Reviewer: Unassigned
Milestone: M4
Issue: https://github.com/tanner-art/working/issues/26

Scope: selectable canvas connections with straight or curved paths, solid/dashed/dotted
patterns, and light/regular/bold weights. Styling remains visual canvas expression,
persists with AppState, validates fail-loud, preserves legacy connections, and participates
in session undo/redo. No semantic relationship inference or endpoint manipulation.

Acceptance: accessible pointer/keyboard selection and controls; geometry, validation,
migration, persistence, and undo tests; pnpm check and git diff --check.

Validation (2026-09-14): pnpm check passed (181 tests across 11 files, TypeScript,
production build); git diff --check passed. Legacy connections retain implicit straight,
solid, regular defaults. Invalid and misplaced style fields fail validation without write.

Limitation: arcs use a computed cubic curve between existing automatic ports; this slice
does not add draggable path control points or endpoint ports.

---

### TASK-021 - Canvas Block Resizing and Shape Changes

Status: REVIEW
Owner: Codex A
Reviewer: Independent Codex review (approved)
Milestone: M4
Issue: https://github.com/tanner-art/working/issues/20

Lifecycle: explicitly assigned by user, READY -> IN_PROGRESS on 2026-09-14.
Dependencies: current canvas and TASK-010 session history are present in this worktree.
Scope: pointer and keyboard resizing; conversion between supported text/group forms;
bounded dimensions; stable content, IDs, connectors and semantic evidence; session undo/redo
and current-state persistence; desktop/mobile verification. No unrelated drawing tools.
Acceptance: meaningful geometry/history/persistence tests, pnpm check, git diff --check,
desktop/mobile browser checks and independent review.
Delivery: implementation prepared, uncommitted per explicit user instruction; do not merge.
Validation (2026-09-14): pnpm check passed (142 tests across 9 files, TypeScript and
production build); git diff --check passed. No lint script is configured. Dependencies
were installed offline from a copy of the local cache without changing the lockfile.
Author browser attempts were blocked, then orchestrator browser validation confirmed the
selected-block shape and numeric size controls plus labeled resize handles. Independent
review approved the implementation with no actionable findings.

Limitations: conversion covers the existing text block and group container only;
current state persists, undo history remains session-only per D-010. Legacy implicit
sizes use explicit rendering defaults. Group conversion does not create containment
relationships. Existing Capture node stores text evidence without a durable canvas
revision/semantic-node link; this task preserves existing evidence and IDs, and does
not introduce that missing provenance feature.
Follow-ups (not implemented): durable canvas revisions/linking remain the separate
follow-up required by D-010.

---

## READY

### TASK-010 - Wire Canvas Undo/Redo and Decide OD-002 Revision Persistence

Status: READY
Owner: Unassigned
Reviewer: Unassigned
Priority: P3
Milestone: M4

Depends On:
- None

Goal:
Land the session undo/redo stack from `wip/pre-orchestration` src/canvasHistory.ts, and separately decide OD-002 (canvas revision granularity) for durable, provenance-preserving canvas history.

Scope:
- port src/canvasHistory.ts and its App.tsx wiring (undo/redo buttons, keyboard shortcuts, zoom/pan-aware node placement fix) as-is; it requires no schema changes
- record an OD-002 decision in docs/DECISIONS.md covering what persists across reload vs. session-only

Do Not:
- implement persisted revision storage itself (follow-up once OD-002 is decided and TASK-002 lands)

Deliverable:
Working canvas undo/redo in the app; OD-002 resolved in docs/DECISIONS.md.

Acceptance Criteria:
- pnpm check passes
- undo/redo covers add/connect/delete/drag/text-edit per docs/ARCHIVE_SALVAGE_AUDIT.md item 1
- OD-002 moved to Accepted

Result:
Commit: pending
Review: pending

---

### TASK-012 - Consolidate Implementation Status Documentation

Status: READY
Owner: Unassigned
Reviewer: Unassigned
Priority: P3
Milestone: M0

Depends On:
- None

Goal:
Merge `wip/pre-orchestration` docs/IMPLEMENTATION_STATUS.md content and the related README.md updates with docs/ARCHIVE_SALVAGE_AUDIT.md into a single canonical status doc that references TASKS.md IDs.

Scope:
- docs/IMPLEMENTATION_STATUS.md: create/update as the canonical, ongoing status doc
- README.md: update links accordingly

Do Not:
- modify application code
- restate docs/ARCHIVE_SALVAGE_AUDIT.md's historical findings verbatim; summarize and cross-reference it instead

Deliverable:
docs/IMPLEMENTATION_STATUS.md reconciled with docs/ARCHIVE_SALVAGE_AUDIT.md, referencing TASK IDs.

Acceptance Criteria:
- no contradicting status claims between IMPLEMENTATION_STATUS.md and the audit
- every gap listed maps to a TASKS.md entry or is explicitly noted as unscoped

Result:
Commit: pending
Review: pending

---

## BACKLOG

Queued app-usability tasks below are created from the current product push toward immediate hosted usability. Promote them to READY only when their listed dependencies are satisfied.

### TASK-029 - Auth Provider Selection and Login Wiring

Status: REVIEW (authorized SDK-unavailable fallback; live login remains blocked)
Owner: Codex A
Reviewer: Pending independent runner review
Priority: P0
Milestone: M5

Depends On:
- TASK-026

Goal:
Give Threadline a real login path so the app can distinguish a local-only session from an authenticated user without breaking existing local data.

Note (TASK-027): the initial auth provider is decided — Supabase Auth + Postgres, per D-011
and [docs/AUTH_DATA_PLAN.md](docs/AUTH_DATA_PLAN.md), which also lists the required
`VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` env vars and one-time dashboard setup. This
task should implement login against that decision rather than re-evaluating providers.

Scope:
- wire Supabase email auth per docs/AUTH_DATA_PLAN.md (choose password or magic link)
- add visible login/logout/account entry points from the Settings shell
- keep existing localStorage data safe during the transition
- show clear signed-in vs local-only state in the UI
- add tests for login state rendering and guarded account actions

Do Not:
- migrate all application data to the backend in this task
- implement billing, teams, sharing, or admin roles
- claim mobile push notifications work from closed app

Deliverable:
A user can open the hosted app, find login from Settings, and see whether Threadline is local-only or signed in.

Acceptance Criteria:
- existing local-only users do not lose data
- settings/account shell reflects authenticated, unauthenticated, and loading/error states
- pnpm check passes
- hosted deployment has required auth environment variables documented

Result (issue #41): implemented Supabase client login wiring. Account UI and typed
configuration/session boundary include honest unconfigured, signed-out, loading/error and
signed-in states, guarded email magic-link/login and logout actions, subscription cleanup,
stale-response protection, and a real `@supabase/supabase-js` adapter. Existing application
storage is untouched; no backend migration or cloud-sync claim. Morning Digest settings were
hidden from Settings per user direction while the app is being made usable on mobile. See
docs/AUTH_DATA_PLAN.md for exact remaining env and hosted validation steps.

Validation: pnpm check passed (258 tests across 14 files, TypeScript and production
build); git diff --check passed. Build emits a nonblocking bundle-size warning after adding
Supabase; future code-splitting can address it. Implementation/test diffs inspected. No lint
script is configured.
Limitations: hosted email login/logout and callback handling still require choosing the
Threadline Supabase project, configuring redirect URLs, adding Vercel env vars, and browser
validation against the deployed app. Cloud persistence/RLS remains TASK-034.
Delivery: left uncommitted for the runner per explicit assignment; no git mutations.

### Exact response to move forward
`Choose the Supabase project for Threadline, set Vercel env vars, then validate hosted email login/logout and local-data preservation.`

---

### TASK-030 - User-Owned Cloud Data Boundary

Status: BACKLOG (superseded — see note)
Owner: Unassigned
Reviewer: Unassigned
Priority: P0
Milestone: M5

Depends On:
- TASK-026
- TASK-029

Note (TASK-027): this task's combined scope is superseded by the more granular TASK-034
(user-scoped storage adapter), TASK-035 (migration/import), TASK-036 (sign-out/offline
behavior), and TASK-037 (privacy/export/delete settings) defined in
[docs/AUTH_DATA_PLAN.md](docs/AUTH_DATA_PLAN.md) and D-011. Do not assign this task as
written; assign TASK-034–037 instead so scope does not overlap. Left in place for history.

Goal:
Move from one-browser local data toward data that belongs to a specific signed-in user, while preserving the existing capture/provenance model.

Scope:
- define the minimum backend schema/storage boundary for users, captures, interpretations, semantic objects, canvas state, settings, and digest delivery state
- implement a first safe sync or import/export bridge from local-only data into the signed-in user's account
- prevent cross-user reads/writes by construction
- surface sync/local-only state in Settings
- add migration and access-control tests around user ownership

Do Not:
- build collaboration or shared workspaces
- discard local data after login without explicit user action
- rewrite capture/interpretation provenance semantics

Deliverable:
Signed-in user data has an explicit ownership model and a safe first path from local data to account data.

Acceptance Criteria:
- user A cannot read or mutate user B's data in tests
- local data remains recoverable until the user explicitly completes migration
- app shows whether data is local-only, synced, or blocked by an error
- pnpm check passes

### Exact response to move forward
Assign this task after TASK-029: `Assign TASK-030 user-owned cloud data boundary to Claude or Agent A.`

---

### TASK-034 - User-Scoped Storage Adapter (Supabase)

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P0
Milestone: M5

Depends On:
- TASK-029

Goal:
Give the app a storage adapter that reads and writes a signed-in user's data in Supabase
Postgres, isolated by construction from every other user, per D-011 and
[docs/AUTH_DATA_PLAN.md](docs/AUTH_DATA_PLAN.md).

Scope:
- define the minimum Supabase table schema for the existing persisted-state shape (objects/
  captures, canvas state, settings, digest delivery state), each row carrying `user_id`
- enable RLS on every such table with a `user_id = auth.uid()` policy for all operations
- implement a storage adapter used only when a Supabase session exists; local-only mode keeps
  using the existing `src/store.ts`/`src/settings.ts` localStorage path unchanged
- add access-control tests proving one user cannot read or mutate another user's rows

Do Not:
- change the existing local-only persisted-state shape or its localStorage keys
- implement migration/import of existing local data into this storage (TASK-035)
- implement sign-out or offline-queue behavior (TASK-036)
- build collaboration or shared workspaces

Deliverable:
A working, RLS-isolated per-user storage adapter that a signed-in session can read/write
against, with local-only storage untouched.

Acceptance Criteria:
- user A cannot read or mutate user B's data in tests
- local-only usage is unaffected when no Supabase session exists
- pnpm check passes
- required Supabase env vars and table/RLS setup are documented (cross-reference
  docs/AUTH_DATA_PLAN.md rather than duplicating it)

### Exact response to move forward
Assign this task after TASK-029 lands: `Assign TASK-034 user-scoped storage adapter to Claude or Agent A.`

---

### TASK-035 - Local-to-Account Data Migration/Import

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P0
Milestone: M5

Depends On:
- TASK-034

Goal:
Let a signed-in user copy their existing local-only data into their account without any
automatic or destructive migration, per docs/AUTH_DATA_PLAN.md's data ownership model.

Scope:
- an explicit, user-initiated "Import my local data" action (D-009-style discrete
  confirmation interaction), reachable from Settings
- copies local `AppState`/settings/digest-delivery data into the signed-in user's Supabase
  rows via the TASK-034 adapter; never deletes or overwrites local data as a side effect
- shows import progress/result and handles partial-failure without data loss
- add tests for import correctness, re-import/idempotency, and failure handling

Do Not:
- delete local data automatically after a successful import
- run import automatically on sign-in without the explicit user action
- rewrite capture/interpretation provenance semantics

Deliverable:
A working, explicit, non-destructive local-to-account import path.

Acceptance Criteria:
- local data remains fully intact and usable after import, until the user separately chooses
  to clear it
- a failed or partial import does not corrupt local or remote data
- pnpm check passes

### Exact response to move forward
Assign this task after TASK-034 lands: `Assign TASK-035 local-to-account data migration/import to Claude or Agent A.`

---

### TASK-036 - Sign-Out and Offline/Local-Only Behavior

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M5

Depends On:
- TASK-029
- TASK-034

Goal:
Define and implement what happens when a signed-in user signs out or loses connectivity, so
the app never silently loses in-progress work or misrepresents sync state.

Scope:
- sign-out returns the app to local-only mode without deleting the local copy of data
- clear, honest UI state for signed-in/local-only/offline/sync-error, per
  docs/AUTH_DATA_PLAN.md
- define minimum offline behavior for a signed-in user who loses connectivity (e.g. read-only
  fallback to last-synced data, or local queuing) — document the chosen behavior; a full
  offline-write queue is out of scope if not already decided
- add tests for sign-out state transitions and offline/error state rendering

Do Not:
- delete local data on sign-out
- implement a general-purpose offline sync engine beyond the minimum defined here
- silently drop unsaved work when connectivity is lost

Deliverable:
Working sign-out and honest offline/error state handling for the signed-in path.

Acceptance Criteria:
- signing out preserves local data and returns the app to a working local-only state
- the UI never claims data is synced when it is not
- pnpm check passes

### Exact response to move forward
Assign this task after TASK-029 and TASK-034 land: `Assign TASK-036 sign-out and offline behavior to Claude or Agent A.`

---

### TASK-037 - Privacy, Export, and Delete Account Data Settings

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M5

Depends On:
- TASK-034

Goal:
Give a signed-in user a way to export and delete their account data from Settings, so account
data ownership is not a one-way door.

Scope:
- a Settings section (within the TASK-033 control center) offering export of the signed-in
  user's account data and deletion of that account data
- export produces a downloadable copy of the user's Supabase-stored data
- account data deletion requires explicit confirmation (typed confirmation or equivalent
  discrete gesture, matching the existing `clearLocalData` pattern in src/settings.ts) and
  does not touch local-only data unless the user separately clears that too
- add tests for export contents and confirmed/guarded deletion

Do Not:
- delete Supabase auth account or local data as a side effect of exporting
- implement data deletion without an explicit confirmation gesture
- implement billing, teams, or admin roles

Deliverable:
Working export and confirmed delete for a signed-in user's account data.

Acceptance Criteria:
- exported data matches what is stored for that user
- account data deletion requires explicit confirmation and does not silently cascade to local
  data
- pnpm check passes

### Exact response to move forward
Assign this task after TASK-034 lands: `Assign TASK-037 privacy/export/delete settings to Claude or Agent A.`

---


### TASK-043 - Hosted Account Sync Rollout and Two-Device Validation

Status: IN_PROGRESS
Owner: Orchestrator
Reviewer: Pending hosted validation
Priority: P0
Milestone: M5

Depends On:
- TASK-029
- TASK-042

Goal:
Make signed-in Threadline data real on the hosted app so the same account shows the same Review queue and Bank folders on desktop and phone.

Scope:
- reconcile the hosted Supabase project/table with the TASK-042 account-storage contract
- provision the owner-only RLS table named by `VITE_SUPABASE_DATA_TABLE` without committing project identifiers, anon keys or service-role keys
- configure Vercel Production and Preview environment variables for Supabase Auth and account storage
- confirm Supabase auth redirect URLs for the hosted Vercel URL and localhost development
- validate with two test accounts across desktop and phone: explicit local import, account load, Review edits, Bank folder changes, sign-out/local preservation and cross-user isolation
- document the exact non-secret operational checklist and any remaining account-level setup

Do Not:
- silently migrate local-only browser data on sign-in
- expose Supabase project refs, anon keys, service-role keys or account emails in source/docs/issues
- enable realtime merge or background sync beyond the explicit load/save behavior already delivered
- replace a nonempty account import without a user-visible export/merge path

Deliverable:
A hosted account can copy this device’s thoughts into account storage and load the same Review and Bank data on the user's phone, while a second account cannot read or overwrite it.

Acceptance Criteria:
- hosted login works from the Vercel app and returns to the app after email auth
- Settings → Data can copy local data into an empty signed-in account
- phone can load the same account data and see the same Review queue and Bank folders
- edits from one device save to account storage and can be explicitly loaded on the other
- stale revision, offline/RLS failures and sign-out do not overwrite or erase local-only data
- two-account smoke test confirms account isolation
- `pnpm check` passes after any code/docs changes


Rollout progress (2026-09-16): provisioned the TASK-042-compatible Supabase account-data table alongside the older `threadline_user_state` table instead of changing app code to the old shape. The new table has owner-only RLS, anon access revoked, authenticated select/insert/update grants, and select/insert/update policies matching the documented contract. Supabase security advisors returned no security lints. Vercel Production and Preview now have the required client-safe env names configured (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_SUPABASE_DATA_TABLE`), and production was redeployed to the `working-ten-rust.vercel.app` alias. Production returned HTTP 200 after deploy. No project refs, keys, personal emails, service-role keys or account rows were added to source/docs/issues.

Validation (2026-09-16): `pnpm check` passed locally: 347 tests across 18 files, TypeScript and production build. `git diff --check` passed. Supabase security advisors clean; performance advisor only reports informational Auth DB connection allocation guidance.

Remaining blocker: Supabase Auth Site URL / redirect URL settings and real email magic-link delivery require dashboard/test-inbox validation. The two-account desktop/phone smoke test has not been completed. Exact response to continue hosted validation: `Supabase auth redirect URLs are configured for the hosted app and localhost, and I am ready to run two-account desktop-to-phone validation.`

Blocker / user action if no connected Supabase/Vercel dashboard access is available:
Set up the documented `public.threadline_account_data` table with owner-only RLS, add `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` and `VITE_SUPABASE_DATA_TABLE=threadline_account_data` to Vercel, and configure Supabase auth redirect URLs. Then respond: `Hosted Supabase account sync env and RLS table are ready; validate desktop-to-phone Review and Bank sync.`

---
### TASK-031 - Real AI Interpretation Provider

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P0
Milestone: M5

Follow-up progress (2026-09-16): added non-secret safety hardening without enabling the provider. Settings now indicates built-in rules vs provider-attempt mode from the client feature flag, and still states proposals require Review confirmation. Added evaluator coverage for uncertain action-like captures, consequential reminder/timing captures, cancellation/change-of-intent language, provider status labels, and provider confidence bounds. Added `tsconfig.api.json` and included `tsc -p tsconfig.api.json` in `pnpm check` so `api/interpret.ts` is type-checked without calling a live provider or adding keys.

Depends On:
- TASK-028

Goal:
Replace the deterministic placeholder interpretation experience with a provider-backed AI interpretation path that still respects Review, provenance, and confirmation rules.

Scope:
- wire a server-side interpretation endpoint/provider behind the existing interpretation boundary
- send only the necessary capture/canvas context for interpretation
- receive structured proposed interpretations with rationale, confidence, and provenance references
- fail closed to Review and useful errors when the provider is unavailable
- add tests/evaluators for ambiguous, consequential, and low-confidence captures

Do Not:
- let AI directly create confirmed Actions, Commitments, notifications, or calendar events
- expose provider keys to the browser
- remove the deterministic fallback/evaluator fixtures before replacement is validated

Deliverable:
A user can capture real text/canvas input and receive AI-generated proposed meaning that is reviewable, reversible, and provenance-linked.

Acceptance Criteria:
- consequential suggestions require explicit confirmation under D-009
- provider failures do not corrupt or overwrite captures
- structured response validation rejects malformed provider output
- pnpm check passes

### Exact response to move forward
After TASK-028 succeeds: `Assign TASK-031 real AI interpretation provider to Claude.`

---

### TASK-032 - First-Run Mobile Onboarding and Home Screen Install Help

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M5

Depends On:
- TASK-025
- TASK-026

Goal:
Make the hosted app immediately usable on iPhone, including clear Add-to-Home-Screen guidance and controls that avoid the camera/dynamic-island safe area.

Scope:
- add a lightweight first-run/onboarding surface for mobile users
- explain Add to Home Screen steps inside the app
- ensure top-right menus and overflow controls sit below unsafe iPhone top insets
- keep guidance dismissible and recoverable from Settings
- add responsive/mobile tests where practical

Do Not:
- implement native iOS app code
- request notification permission as part of onboarding
- block desktop users with mobile-only instructions

Deliverable:
A new iPhone user can install/use the hosted app from the home screen without controls being hidden under the top camera area.

Acceptance Criteria:
- mobile controls are reachable in browser and home-screen display modes
- onboarding can be dismissed and reopened from Settings
- existing desktop layout remains usable
- pnpm check passes

### Exact response to move forward
Assign this task to Agent A or Claude: `Assign TASK-032 mobile onboarding and home-screen install help.`

---

### TASK-033 - Settings as Usability Control Center

Status: BACKLOG (superseded — see note)
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M5

Note: TASK-040 (GitHub issue #53) implemented this task's scope — Account, Data, AI
interpretation, Mobile install, Digest, and Recovery cards in Settings — under a new task ID
assigned directly by the user. Left in place for history; do not assign this task as written.

Depends On:
- TASK-026

Goal:
Turn Settings into the place where a nontechnical user can understand and control account state, data storage, AI interpretation, mobile install status, digest delivery, and recovery/export.

Scope:
- add sections/cards for Account, Data, AI interpretation, Mobile install, Digest, and Recovery
- show current status and next action for each section
- link to login, sync/migration, export, clear local data, and onboarding actions as those features land
- keep unavailable future features honest: say what is not configured yet without implying it works
- add rendering/tests for unavailable, local-only, and configured states

Do Not:
- implement the backend/auth/provider itself in this task
- hide risk states behind generic success copy
- remove export/backup controls

Deliverable:
Settings becomes the app's operational dashboard for making Threadline usable immediately.

Acceptance Criteria:
- user can tell what is local, signed-in, synced, AI-enabled, mobile-ready, and recoverable
- unavailable features have clear next actions
- no false claims about notifications or cloud sync
- pnpm check passes

### Exact response to move forward
Assign this task after TASK-026 merges: `Assign TASK-033 settings control center to Agent A.`

---

Tasks below are generated from TASK-001 / docs/ARCHIVE_SALVAGE_AUDIT.md. They are blocked on the dependencies listed and are not to be newly assigned until promoted to READY.

### TASK-005 - Port Dependency Graph Logic onto Upgraded Relationship Model

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M2

Depends On:
- TASK-002
- TASK-003 (Relationship type upgrade with scope/provenance is bundled with the entity work)

Goal:
Port `wip/pre-orchestration` src/dependencies.ts (unresolvedDependencies, cycle-safe dependencyCandidates) onto the upgraded Relationship type (explicit endpoints, scope, provenance per docs/ARCHITECTURE.md).

Scope:
- src/dependencies.ts: adapt to the new Relationship shape
- src/objectWorkflow.ts: dependency-aware confirmedActions filtering
- port corresponding tests

Do Not:
- change dependency semantics beyond what the Relationship upgrade requires

Deliverable:
Working dependency graph (cycle-safe, completion-aware) on the new Relationship model.

Acceptance Criteria:
- pnpm check passes
- cycle detection and completion-based eligibility behave the same as in docs/ARCHIVE_SALVAGE_AUDIT.md item 2

Result:
Commit: pending
Review: pending

---

### TASK-006 - Port Parent/Child Project Linking onto Upgraded Relationship Model

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M2

Depends On:
- TASK-002
- TASK-003 (Relationship type upgrade)
- OD-007 (must be ratified before implementing containment cardinality)

Goal:
Port `wip/pre-orchestration` src/objectWorkflow.ts parent/child helpers (setBelongsTo, cycle-safe parentCandidates, parentObject, projectChildren) onto the upgraded Relationship model, per whatever cardinality OD-007 decides (single-parent vs. multi-membership).

Scope:
- src/objectWorkflow.ts: parent/child helpers per OD-007's ratified cardinality
- src/App.tsx: parent picker, child list, parent breadcrumb (if still single-parent) or equivalent multi-membership UI
- port corresponding tests

Do Not:
- implement this before OD-007 is ratified

Deliverable:
Working project/objective containment matching the ratified OD-007 cardinality.

Acceptance Criteria:
- pnpm check passes
- cycle-safe candidate selection preserved per docs/ARCHIVE_SALVAGE_AUDIT.md item 4/5

Result:
Commit: pending
Review: pending

---

### TASK-007 - Rebuild Morning Digest on Commitment/CalendarEvent Split

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M3

Depends On:
- TASK-002

Goal:
Port `wip/pre-orchestration` src/morningDigest.ts (fixed-today/upcoming/recommended/needs-review/project-signals buckets, local-calendar-day date matching) onto the split Commitment/CalendarEvent/Reminder-instruction model, and add the M3 delivery mechanism (7 AM digest).

Scope:
- src/morningDigest.ts: rebuild fixedCommitments-equivalent source without conflating Commitment and Reminder
- delivery mechanism for the 7 AM digest (per NORTH_STAR.md)
- port corresponding tests

Do Not:
- implement Adaptive Plan recalculation (M5)

Deliverable:
Morning Digest built on the correct entity split, with a delivery mechanism.

Acceptance Criteria:
- pnpm check passes
- digest buckets no longer conflate Commitment and Reminder kinds
- date-matching bug fix (local calendar day) preserved

Result:
Commit: pending
Review: pending

---

### TASK-008 - Reintegrate Salvaged UI onto New Entity Model

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M3

Depends On:
- TASK-002
- TASK-003
- TASK-005
- TASK-006
- TASK-007

Goal:
Reintegrate the `wip/pre-orchestration` App.tsx UI surfaces (Objects workbench with search/filter, Today digest strip and detail sections, blocked-vs-ready action distinction, dependency editor, parent/child linking UI, object History panel) onto the fully migrated entity model.

Scope:
- src/App.tsx: port the UI listed above, wired to the new domain types
- src/styles.css: port supporting styles (already architecture-neutral, per docs/ARCHIVE_SALVAGE_AUDIT.md item 9)

Do Not:
- introduce new product surfaces beyond what docs/ARCHIVE_SALVAGE_AUDIT.md item 4 describes

Deliverable:
Working UI parity with the `wip/pre-orchestration` feature set, on the current architecture.

Acceptance Criteria:
- pnpm check passes
- every surface listed in docs/ARCHIVE_SALVAGE_AUDIT.md item 4 is reachable and functioning
- no regression in accessibility labels noted in docs/IMPLEMENTATION_STATUS.md

Result:
Commit: pending
Review: pending

---

## Current Product Operating Focus

Every new task should explicitly serve at least one near-term product outcome: fast capture, safe user data, confirm/organize meaning, mobile usability, or real AI interpretation. Prefer tasks that move the hosted app toward immediate daily use within 24 hours over low-priority polish. Larger ideas such as AI folder clustering, resource cost, attention load, ROI, and strategic importance should be captured as follow-ups unless they directly unblock the current capture/review/storage loop.

For the next 24-hour push, tasks should be framed around making the hosted mobile app feel usable by a real account holder: capture should be quick and rewarding, review/organize should let the user safely confirm or remove proposed meaning, account storage should keep data tied to the signed-in user, and AI interpretation should start replacing deterministic placeholders. Process/documentation work is valid only when it helps agents or the user move those outcomes faster.

Build-in-public rule: when a task changes visible behavior, its issue/PR should include one plain-language user-facing note that can be reused for a public progress update, plus the usual validation and `Exact response to move forward`. Keep the note honest: describe what users can do now, what is still limited, and the next visible improvement.

## IN_PROGRESS



None.

## REVIEW

### TASK-020 - Full Calendar Month View (CalendarEvents, Commitments, Proposed Dates)

Status: REVIEW
Owner: Claude
Reviewer: Unassigned
Priority: P1
Milestone: M3
GitHub Issue: #21

Depends On:
- None. Built directly against the CalendarEvent/Commitment/Interpretation model already on this branch (`src/domain.ts`, `src/migration.ts`, `src/morningDigest.ts`); no schema change.

Goal:
Give the user a real navigable month calendar (NORTH_STAR.md "Calendar" section, ROADMAP.md M3), not just the existing Commitments list, while keeping the app's existing D-009 discipline: never plot an unconfirmed date as if it were a scheduled time.

Scope:
- `src/calendar.ts` (new): pure month-grid math (Sunday-start weeks, local-calendar-day bucketing, no UTC-parse shifting) plus three explicitly separated buckets per day: display-ready `CalendarEvent`s (with resolved linked semantic objects), confirmed Commitments with no linked event (`unscheduledCommitments`, not pinned to a day), and `ProposedDateMarker`s sourced only from `Interpretation.legacy.metadata.deadline` (the user-authored "Proposed date (not fixed)" field), never from AI's `suggestedDate` placeholder text or from a `SemanticObject`'s metadata (deadline is stripped there on confirm — see migration.ts's `delete metadata.deadline`).
- A small pluggable `TemporalProvenanceCheck` seam (`defaultTemporalProvenanceCheck`) gating which CalendarEvents are display-ready, documented as the reconciliation point for TASK-019 (Agent B, parallel D-009 temporal-confirmation work) — swap that one predicate, not the grid/rendering code, once TASK-019 defines real event-scheduling provenance.
- `src/CalendarView.tsx` (new): month grid, prev/next/today controls, today/selected-day states, a day-detail panel (Events / Proposed dates, clearly separated and labeled), and an always-visible Unscheduled Commitments list. Clicking a linked object, a proposed-date marker, or an unscheduled commitment opens the existing `ObjectPanel` via the same `onOpen`/`selectedObjectId` mechanism `Today`/`Review`/`Commitments` already use.
- `src/App.tsx`: new `calendar` nav entry wired to `CalendarView`.
- `src/styles.css`: calendar grid/detail/chip styles plus a mobile breakpoint (existing `@media (max-width: 720px)` pattern).
- `src/morningDigest.ts`: extracted `confirmedSemanticObjects`/`currentInterpretations` (previously inlined in `buildMorningDigest`) so the calendar's Commitment/proposed-date filtering uses the exact same "confirmed obligation" and "current (non-superseded) interpretation" definitions as the Morning Digest — behavior-preserving refactor, `morningDigest.test.ts` unchanged and still passing.
- `src/calendar.test.ts` (new): date-grid invariants (full Sunday-start weeks, no gaps/duplicates/DST drift, leap years, year-boundary months), local-time correctness for both event instants and date-only proposed-date strings, event provenance filtering, linked/unscheduled commitment resolution, superseded/rejected/archived exclusion, and the `dayAriaLabel` accessibility-label pure function.

Do Not:
- add external calendar sync, recurrence, or autonomous scheduling
- add a way to create/schedule a `CalendarEvent` from the UI (that is scheduling confirmation — TASK-019's territory per D-009 rule 5, not this task)
- change `CalendarEvent`'s schema or add a provenance/confirmation field to it (left to TASK-019; this task only defines the seam that will consume it)
- fix the pre-existing TASKS.md/IMPLEMENTATION_STATUS.md staleness noted below (out of scope; flagged, not fixed)

Deliverable:
A working, responsive, keyboard-accessible month calendar reachable from the sidebar, with CalendarEvents, linked/unscheduled Commitments, and unverified proposed dates always visually and textually distinct.

Acceptance Criteria:
- `pnpm check` passes
- `git diff --check` passes
- month grid is correct for leap years, year boundaries, and DST-adjacent months (tested via invariants, not hardcoded week counts)
- a `metadata.deadline` string is never plotted as, or visually confused with, a `CalendarEvent`
- prev/next/today controls and day cells are reachable and operable by keyboard alone, with visible focus and correct `aria-label`/`aria-current`/`aria-pressed`
- desktop and mobile widths both verified in a running browser

Result:
Commit: Uncommitted per user instruction.
Review: Pending independent review.
Files: `src/calendar.ts`, `src/calendar.test.ts`, `src/CalendarView.tsx` added; `src/App.tsx`, `src/styles.css`, `src/morningDigest.ts` modified.
Validation: `pnpm check` passed — 158 tests (30 new in `calendar.test.ts`, all pre-existing tests including `morningDigest.test.ts` unchanged and passing after the extraction refactor), TypeScript check, and production Vite build. No lint script is configured. `git diff --check` passed (no whitespace errors). Diff inspected; no unrelated files touched.
Browser validation: dev server driven headlessly (Playwright, installed to a scratch `/tmp` directory only — never added to this repo's `package.json`/lockfile, and removed afterward) at 1280×900 and 375×812. Verified: month navigation (prev/next/today, including year-boundary rollover), today vs. selected-day states shown simultaneously and distinctly, mobile layout collapses correctly, a seeded unconfirmed commitment's proposed date renders as a dashed/labeled "unconfirmed" chip on the correct day and never as an event, clicking it opens the real `ObjectPanel` showing `status: review` and the matching "Proposed date (not fixed)" field, keyboard Tab+Enter operates the Previous-month control with a visible focus ring, and no console/page errors were observed in any of the above.
Limitations: no `CalendarEvent` can currently be created anywhere in the app (no interpreter/UI path produces one — same gap noted for `fixedCommitments()`/`buildMorningDigest` before this task), so the Events bucket is exercised in tests but is empty in the live seeded app today; this is expected and matches the existing codebase's D-009 posture, not a defect in this task. `defaultTemporalProvenanceCheck` fails closed, while CalendarView now supplies TASK-019's active exact-fact temporal confirmation predicate. Component-level (React) tests were not added: this repo has no DOM testing library installed (`vitest` runs in the default `node` environment; no `jsdom`/`@testing-library/react` in `package.json`) and adding one was out of scope for a UI slice, so calendar logic is covered by pure unit tests in `calendar.test.ts` and by the manual/scripted browser pass above instead.
Discovered (not implemented, does not block this task): TASKS.md's own status entries for TASK-002/003/004/005/007/012 (and TASK-018, TASK-019, TASK-020 are entirely absent) are stale relative to `main`'s actual git history — `git log` shows TASK-002 through TASK-018 already merged into `main` via PRs, but this file still lists several of them as REVIEW/BACKLOG and never mentions TASK-018 at all. `docs/IMPLEMENTATION_STATUS.md` has the same drift. Recommend a small doc-sync task once the current parallel work (this task + TASK-019) lands, so the board reflects `main` accurately; not fixed here since AGENTS.md scopes each task to its own assignment.
Follow-ups (not implemented; do not block this task): a future task should add the actual "schedule this Commitment as a CalendarEvent" confirmation UI so the Events bucket has real data to show; consider surfacing Reminder instructions on the calendar once OD-004 (reminder timing semantics) is resolved — intentionally left out of this task's scope.

---

### TASK-019 - Confirm fixed deadlines and CalendarEvent scheduling

Status: REVIEW
Owner: Codex B
Reviewer: Independent Codex review (approved)
Priority: P1
Milestone: M3
Depends On: TASK-002, TASK-003, TASK-007, TASK-009 (implementation/decision prerequisites present in this worktree; board integration statuses remain unchanged).

Goal: Record distinct timestamped temporal confirmation and reversal under D-005/D-009, expose supported proposals in Review, and enable only provenance-backed digest timing.
Scope: Domain, persisted validation, focused Review controls, digest eligibility, regression tests. No notification backend, recurrence, autonomous scheduling, or missing calendar semantics.
Acceptance Criteria: separate timestamped exact-target temporal evidence; dedicated per-fact confirmation/reversal; no Action/Commitment/status/date bypass; preserved source/history and fail-loud persistence; provenance-backed digest buckets; focused integrity/persistence tests, pnpm check and browser attempt.
Lifecycle: Assigned directly by user as GitHub issue #19 after verifying prerequisite implementations in this worktree; recorded IN_PROGRESS before coding, then REVIEW. Board dependency statuses were not rewritten.
Result: Implementation approved for integration. `pnpm check` passed (148 tests, TypeScript, production build); no lint configured. `git diff --check` passed. Independent review found no actionable issues. Orchestrator browser validation confirmed separate obligation and fixed-deadline gestures plus reversal controls.
Delivery, limitations and proposed follow-ups: [docs/TASK-019_DELIVERY.md](docs/TASK-019_DELIVERY.md).

---

### TASK-004 - Port Interpreter Heuristics Behind an Interpretation-Service Interface

Status: REVIEW
Owner: Codex B
Reviewer: Unassigned
Priority: P2
Milestone: M1

Depends On:
- TASK-002 (Interpretation becomes a first-class entity this sits behind)

Goal:
Relocate the `wip/pre-orchestration` src/interpreter.ts heuristics (clustered-capture detection, uncertainty/conditional/question confidence capping, reminder-phrase routing) behind a proper Interpretation-service interface, keeping the interpreter itself deterministic for now.

Scope:
- define an Interpretation-service interface per TASK-002's entity model
- port existing heuristics from docs/ARCHIVE_SALVAGE_AUDIT.md item 5 with no behavior regression
- port corresponding src/interpreter.test.ts coverage

Do Not:
- integrate a real AI/provider-backed interpreter (future work, not this task)

Deliverable:
Interpretation-service interface with the ported deterministic heuristics behind it.

Acceptance Criteria:
- pnpm check passes
- existing interpreter regression tests pass against the new interface
- interface is swappable for a future provider-backed implementation without call-site changes

Result:
Commit: Uncommitted per user instruction.
Review: Pending independent orchestration review.
Lifecycle: Promoted BACKLOG → READY after verifying TASK-002 entities are present on this branch; assigned to Codex B and moved to IN_PROGRESS for GitHub issue #14; moved to REVIEW after implementation and validation.
Validation: `pnpm check` passed (107 tests, TypeScript check, production Vite build); no lint script configured. `git diff --check` passed and diff inspected. Dependencies installed from the existing temporary offline cache with the frozen lockfile after registry access failed; no dependency/lockfile changes.
Implementation: asynchronous CaptureRecord → InterpretationProposal service with a single implementation composition point; deterministic archive heuristics; compatibility capture adapter and awaited UI call; regression, substitution, failure, provenance, confirmation and persistence tests.
Limitations: one proposal per text capture; persistence owns interpretation identity/version/history. The existing schema-v2 compatibility writer remains authoritative for persistence; unsupported separate action summaries or rewritten reminder triggers fail explicitly. Reminder targets/timing remain unresolved in Review; no provider, scheduling, notification or canvas interpretation integration. Drafts remain in memory while interpretation is pending. Browser validation and independent orchestration review remain pending.
Follow-ups (not implemented; do not block this task): independent browser/review checks; resolve OD-004 before richer reminder semantics; broader canonical writer and durable pending-capture support before expanding the provider contract. GitHub CLI is unauthenticated, so remote issue #14 was not read or changed; the local issue description in `/private/tmp/task004-issue.md` matches this assignment.
Delivery: left entirely uncommitted per user instruction; no reset, rebase, clean, merge, branch switch, push, or access to another worktree.

---

### TASK-003 - Introduce ProposedAction and Explicit Confirmation

Status: REVIEW
Owner: Codex B
Reviewer: Unassigned
Priority: P0
Milestone: M1

Depends On:
- TASK-002
- TASK-009 (OD-001 must be ratified first)

Goal:
Implement ProposedAction (D-003): AI-suspected work stays proposed until the confirmation rule from OD-001/TASK-009 is met. Port and adapt the `wip/pre-orchestration` src/objectWorkflow.ts helpers (confirmObject and related history/provenance preservation) onto the new entity model.

Scope:
- src/domain.ts: ProposedAction shape (per TASK-002's entity split)
- src/objectWorkflow.ts: confirmation flow per the ratified OD-001 rule
- preserve recorded interpretation/confidence on confirm and reclassify, per docs/ARCHIVE_SALVAGE_AUDIT.md item 5

Do Not:
- implement dependency graph or parent/child linking (separate tasks)

Deliverable:
Working confirm flow producing real Actions only per the ratified rule.

Acceptance Criteria:
- pnpm check passes
- no AI-suspected work becomes an Action without the confirmed interaction
- confirming/reclassifying does not overwrite the original recorded interpretation

Result:
Commit: Uncommitted per user instruction.
Review: Pending independent review.
Validation: `pnpm check` passed (74 tests, TypeScript check, production Vite build); no lint script configured. `git diff --check` passed. Diff inspected; browser smoke testing remains for independent review.
Implementation: named ProposedAction; exact item/summary/type confirmation gestures with timestamp, history index and interpretation provenance; protected generic editor and eligibility selector; explicit rejection/reversal and preserved history. Free-form capture remains proposed. Existing schema-v2 confirmations remain readable without fabricating new provenance. Tests cover lifecycle/editor bypasses, malformed provenance, reclassification, preserved capture/rationale/confidence, rejection/reversal with unrelated meaning and linked events, and save/reload including delayed first save and retry.
Limitations: compatibility adapter remains the schema-v2 writer; withdrawal retains previously accepted semantic identities in Review to preserve event references. No external effects are reversed. OD-003 downstream conflict/partial acceptance policy remains open. No direct-create-Action interaction, fixed deadline confirmation, scheduling, notification delivery, dependencies, containment, heuristics, or PWA work added.
Follow-ups (not implemented, do not block this slice): independent browser/review validation; resolve OD-003 before downstream conflict automation. Canonical status/migration documents contain earlier implementation claims and need a separately assigned documentation refresh outside this allowlist.
P1 review fix: removed plain-history confirmation eligibility; schema-v1 text stays unconfirmed. Older schema-v2 structured confirmations are validated before projection and carried as item-bound in-memory provenance. Regression coverage includes malicious legacy strings, direct selector bypass, invalid schema-v2 projection, and preserved explicit confirmation. Left uncommitted for orchestration review.
Lifecycle: assigned IN_PROGRESS after integrated TASK-002 and TASK-009/D-009; moved to REVIEW with owner Codex B. No commit, push, merge, branch change, runner or credential edits.

---

### TASK-002 - Split ThoughtObject into CaptureRecord / Interpretation / Semantic Object

Status: REVIEW
Owner: Codex B
Reviewer: Independent Codex review (`review_task002`)
Priority: P0
Milestone: M1

Depends On:
- None

Goal:
Implement the entity boundaries in docs/ARCHITECTURE.md: separate immutable CaptureRecord, versioned Interpretation, and Semantic Object; replace Reminder as a first-class ObjectKind with an attached reminder instruction (D-004); split Commitment from CalendarEvent (D-005).

Scope:
- redesign src/domain.ts around CaptureRecord, Interpretation, Semantic Object, Commitment, CalendarEvent, Reminder instruction
- define a migration/compat path for existing localStorage ThoughtObject data
- update src/store.ts validation for the new shapes only as required by the schema change

Do Not:
- change persistence backend (localStorage stays)
- implement Adaptive Plan, ProposedAction confirmation flow, or UI (separate tasks)
- resolve OD-001, OD-003, OD-007 (raise them, do not silently decide them)

Deliverable:
Updated src/domain.ts and a documented migration note for existing saved state.

Acceptance Criteria:
- pnpm check passes
- no data loss path for existing localStorage state (migrate or clearly fail loud, per D-001)
- docs/ARCHIVE_SALVAGE_AUDIT.md item 5 concerns addressed (Reminder-as-kind, ThoughtObject fusion)

Result:
Commit: pending orchestrator
Review: Approved after changes requested; no remaining blocking findings.
Validation: `pnpm check` passed (39 tests, TypeScript, Vite build); no lint script configured. `git diff --check` passed. Browser checks not performed.
Implementation: persisted schema v2, conservative legacy migration, versioned evidence, reminder attachment and separate CalendarEvents; unchanged App.tsx/canvas contract. See docs/MIGRATION.md for migration rules and limitations.
Lifecycle: Codex B recorded IN_PROGRESS before implementation, then REVIEW with commit pending orchestrator.
Requested changes: closed Complete/Archive/generic-status compatibility bypasses for unresolved items, preserved terminal proposal evidence in Review, added actual helper-chain regression coverage, and removed the TASK-004 reminder heuristic. See docs/MIGRATION.md for retained scope and deferred behavior. Left uncommitted for independent rereview.

---

## CHANGES_REQUESTED

None.

## MERGE_READY

### TASK-011 - Land store.ts Load/Save Failure Handling

Status: MERGE_READY
Owner: Codex B
Reviewer: Codex independent review (`task011_review`)
Priority: P2
Milestone: M1

Depends On:
- None

Goal:
Port the `wip/pre-orchestration` src/store.ts changes: `loadStateResult`/`saveState` surface load/save failures (bad JSON, quota errors) instead of silently substituting seed data or swallowing exceptions, plus the App.tsx retry/backup-download UI.

Scope:
- src/store.ts: loadStateResult, saveState error returns
- src/App.tsx: load-failure screen, save-error banner with retry and JSON backup download

Do Not:
- change the persistence backend or schema (this is orthogonal to TASK-002)

Deliverable:
Working failure-surfacing load/save path with backup download.

Acceptance Criteria:
- pnpm check passes
- a corrupted localStorage value pauses editing instead of overwriting saved data
- a failed save offers retry and backup download without losing in-memory work

Result:
Commit: 0795769
Review: Approved by independent reviewer; no blocking findings.
Source: `wip/pre-orchestration` commit `7c0ee6b`; store.ts ported unchanged, only persistence UI and its three alert styles selected from App.tsx/styles.css.
Validation:
- `pnpm check` passed: 18 tests (including 4 persistence tests), TypeScript check, and production build. No lint script is configured.
- Browser: corrupted JSON pauses editing and remains byte-for-byte unchanged through repeated load retry; valid recovered data loads on retry.
- Browser: injected quota failure preserves new captured work in memory and leaves prior stored data intact; failed retry retains the warning.
- Browser: downloaded JSON contains the unsaved thought, existing objects, and all four original canvas elements including the connector.
- Browser: successful save retry clears the warning, saves the current state, and the recovered work survives reload. No browser page errors reported.
- Git diff inspected; `git diff --check` passed; no schema, backend, interpretation, or unrelated UI changes.
Proposed follow-up (not implemented; does not block TASK-011): guided backup import/restoration and corrupted-data recovery. The archived load-error screen deliberately pauses editing and offers retry; it does not provide a recovery/import wizard.
Integration: implementation complete on `agent/codex-b`; not merged or pushed to main.

---

## DONE

### TASK-001 - Audit Current Implementation Against Architecture

Status: DONE
Owner: Unassigned
Reviewer: Unassigned
Priority: P0
Milestone: M0

Depends On:
- None

Goal:
Determine what currently exists in the application and how it maps to the new North Star and architecture.

Scope:
- inspect existing repository
- inspect preserved pre-orchestration branch where useful
- identify implemented features
- identify architectural mismatches
- identify reusable work
- identify abandoned or experimental work

Do Not:
- modify application code
- refactor
- implement missing functionality

Deliverable:
Create or update docs/IMPLEMENTATION_STATUS.md with:
- current stack
- implemented features
- incomplete features
- architecture mismatches
- reusable components
- technical debt
- proposed follow-up tasks

Acceptance Criteria:
- no application code changed
- every major existing subsystem is accounted for
- proposed work is separated from observed current state
- newly proposed tasks include dependencies

Result:
Commit: 17f3d29
Review: pending

---

### TASK-009 - Decision: Ratify OD-001 Confirmation Rules

Status: DONE
Owner: Unassigned
Reviewer: Unassigned
Priority: P0
Milestone: M1

Depends On:
- None

Goal:
Resolve OD-001: exactly which explicit interaction(s) confirm an AI-proposed interpretation as an Action, and which non-consequential interpretations may be accepted automatically (per D-003).

Scope:
- evaluate the `wip/pre-orchestration` Review "Confirm interpretation" button as a candidate answer (docs/ARCHIVE_SALVAGE_AUDIT.md item 4)
- record the decision in docs/DECISIONS.md, moving OD-001 to Accepted with a new D-number

Do Not:
- write or modify application code
- resolve OD-003 or OD-007 in the same pass

Deliverable:
docs/DECISIONS.md updated with the ratified confirmation rule.

Acceptance Criteria:
- OD-001 moved from Open Decisions to Accepted with a clear, testable rule
- TASK-003 can proceed without further clarification

Result:
Commit: 22580a0
Review: pending

---

### TASK-012 - Consolidate Implementation Status Documentation

Status: DONE
Owner: Unassigned
Reviewer: Unassigned
Priority: P3
Milestone: M0

Depends On:
- None

Goal:
Merge `wip/pre-orchestration` docs/IMPLEMENTATION_STATUS.md content and the related README.md updates with docs/ARCHIVE_SALVAGE_AUDIT.md into a single canonical status doc that references TASKS.md IDs.

Scope:
- docs/IMPLEMENTATION_STATUS.md: create/update as the canonical, ongoing status doc
- README.md: update links accordingly

Do Not:
- modify application code
- restate docs/ARCHIVE_SALVAGE_AUDIT.md's historical findings verbatim; summarize and cross-reference it instead

Deliverable:
docs/IMPLEMENTATION_STATUS.md reconciled with docs/ARCHIVE_SALVAGE_AUDIT.md, referencing TASK IDs.

Acceptance Criteria:
- no contradicting status claims between IMPLEMENTATION_STATUS.md and the audit
- every gap listed maps to a TASKS.md entry or is explicitly noted as unscoped

Note:
docs/QA_CHECKLIST.md was not linked from README.md here because it does not yet exist on this branch (only on the archived wip/pre-orchestration branch) — that link is added in TASK-014, which ports the file.

Result:
Commit: 0af355e
Review: pending

---

### TASK-013 - Retire OVERNIGHT_LOG.md

Status: DONE
Owner: Unassigned
Reviewer: Unassigned
Priority: P3
Milestone: M0

Depends On:
- None

Goal:
The single-agent overnight-checkpoint process docs/OVERNIGHT_LOG.md documents is superseded by the AGENTS.md/TASKS.md multi-agent lifecycle. Extract any still-relevant design rationale into docs/DECISIONS.md, then retire the file.

Scope:
- review docs/OVERNIGHT_LOG.md for rationale not captured elsewhere
- add any load-bearing rationale to docs/DECISIONS.md
- remove docs/OVERNIGHT_LOG.md and its README.md reference, if any

Do Not:
- modify application code

Deliverable:
docs/OVERNIGHT_LOG.md removed; any load-bearing rationale preserved in docs/DECISIONS.md.

Acceptance Criteria:
- no unique design rationale is lost
- no dangling references to the removed file

Finding:
docs/OVERNIGHT_LOG.md was never added to `main` — it exists only on the archived `wip/pre-orchestration` branch, so there was nothing to delete here. Reviewed the archived file's full contents (`git show wip/pre-orchestration:docs/OVERNIGHT_LOG.md`): it is almost entirely a mechanical changelog (feature added, test count, build pass) rather than design rationale. Its few rationale-bearing lines are already captured elsewhere: preserving recorded interpretation/confidence on confirm (docs/ARCHIVE_SALVAGE_AUDIT.md item 5, TASK-003 scope), fail-loud storage over silent seed fallback (docs/ARCHIVE_SALVAGE_AUDIT.md item 5, TASK-011), and not displaying invented values for unconfigured data (already an ARCHITECTURE.md principle: "Unknown values remain unknown rather than implying zero cost or importance"). Its operational notes (overnight checkpoint cadence, commit-only-when-told) are fully superseded by AGENTS.md and add nothing further. No new docs/DECISIONS.md entry was added as a result. Confirmed no reference to the file exists in README.md; the mentions in docs/ARCHIVE_SALVAGE_AUDIT.md and docs/IMPLEMENTATION_STATUS.md are intentional historical/tracking references, not dangling links.

Result:
Commit: 1cb1e3c
Review: pending

---

### TASK-014 - Update QA_CHECKLIST.md Git Policy Section

Status: DONE
Owner: Unassigned
Reviewer: Unassigned
Priority: P3
Milestone: M0

Depends On:
- None

Goal:
docs/QA_CHECKLIST.md's Git Policy section still reflects the single-agent overnight process ("do not commit/push until told", "keep progress in OVERNIGHT_LOG.md"), which is obsolete under AGENTS.md's git rules.

Scope:
- replace the Git Policy section in docs/QA_CHECKLIST.md with a reference to AGENTS.md
- keep the North Star Fit, Product Behavior, and Data Safety sections as-is

Do Not:
- modify application code
- change the substantive checklist content outside the Git Policy section

Deliverable:
Updated docs/QA_CHECKLIST.md.

Acceptance Criteria:
- Git Policy section matches current AGENTS.md rules
- rest of the checklist unchanged

Finding:
docs/QA_CHECKLIST.md did not exist on `main` (only on the archived `wip/pre-orchestration` branch). Ported it here with the North Star Fit, Product Behavior, and Data Safety sections byte-for-byte unchanged from the archived version, and rewrote only the Git Policy section to reference AGENTS.md (work only on assigned branch/worktree, commit completed work, never merge into main, report the commit SHA, verify acceptance criteria/tests/typecheck/lint/build before completion) in place of the obsolete overnight-checkpoint instructions. Linked the file from README.md, completing the cross-reference TASK-012 deferred.

Result:
Commit: 2c42fa1
Review: pending

---

### TASK-027 - Define Auth and Per-User Data Plan

Status: DONE
Owner: Claude
Reviewer: Unassigned
Priority: P0
Milestone: M5
GitHub Issue: #37

Depends On:
- None

Goal:
Define the concrete login and per-user data path for Threadline so implementation can start
without ambiguity, comparing Supabase Auth + Postgres, Clerk + hosted database, and a minimal
custom auth/database path for the Vite/Vercel app.

Scope:
- docs/AUTH_DATA_PLAN.md: option comparison, recommended default, required environment
  variables/account-level setup, and the data ownership model
- docs/DECISIONS.md: record the provider decision as D-011
- TASKS.md: concrete, non-overlapping READY-quality follow-up task stubs for login UI,
  user-scoped storage adapter, migration/import of local data, sign-out/offline behavior,
  and privacy/export/delete settings

Do Not:
- implement backend code
- require destructive migration of existing local data
- implement application code changes

Deliverable:
docs/AUTH_DATA_PLAN.md, D-011 in docs/DECISIONS.md, and decomposed follow-up task stubs in
TASKS.md.

Acceptance Criteria:
- a default provider is recommended with rationale and required env vars/setup listed
- the data ownership model defines local-only vs. signed-in vs. synced state without
  requiring destructive migration
- follow-up tasks are concrete and do not overlap with each other

Result:
[docs/AUTH_DATA_PLAN.md](docs/AUTH_DATA_PLAN.md) recommends Supabase Auth + Postgres (RLS)
over Clerk + hosted database and a minimal custom auth/database path, with required env vars
(`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, server-only `SUPABASE_SERVICE_ROLE_KEY`),
one-time Supabase dashboard setup, and a data ownership model requiring an explicit,
non-destructive opt-in to migrate local data (local-only usage is unaffected and remains the
default). Recorded as D-011 in docs/DECISIONS.md. TASK-029 (login UI) is annotated with the
ratified provider rather than duplicated. TASK-030 (User-Owned Cloud Data Boundary) is marked
superseded — its combined scope is decomposed into new BACKLOG stubs TASK-034 (user-scoped
storage adapter), TASK-035 (local-to-account migration/import), TASK-036 (sign-out/offline
behavior), and TASK-037 (privacy/export/delete settings), each with its own Depends On, Scope,
Do Not, and Acceptance Criteria.
Validation: runner validation passed with `pnpm check` and `git diff --check`. The change is
docs-only: docs/AUTH_DATA_PLAN.md, docs/DECISIONS.md, and TASKS.md.
Limitations: none of TASK-034–037 are marked READY. Each depends on TASK-029, which is not yet
DONE, and TASKS.md's Task Lifecycle rule requires dependencies to be satisfied before READY.
They are recorded as concrete BACKLOG stubs, ready for assignment once TASK-029 lands.
TASK-026 has now merged to `main` via PR #39, so TASK-029 is unblocked for promotion/assignment.

Commit: b61a39d plus review correction pending
Review: pending independent review
