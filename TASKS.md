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

## IN_PROGRESS

### TASK-023 - Sticky Canvas Group Membership

Status: MERGE_READY
Owner: Codex B
Reviewer: Independent Codex review (approved)
Priority: P1
Milestone: M4

Goal: Let users explicitly attach text blocks to a canvas group so moving the group moves its members together.

Scope: explicit attach/detach controls; bulk attach of blocks fully inside a group; atomic group movement; resize, conversion, deletion, undo/redo, and persisted-state compatibility; accessible controls and focused tests. Canvas groups do not change semantic project membership.

Acceptance: legacy canvases remain valid; invalid or nested membership fails closed; group motion preserves relative member positions; resizing retains explicit membership; converting or deleting a group safely detaches its members; pnpm check and git diff --check pass.

Result: implementation commit dee16c3. Independent review approved. TASK-022 integration preserves both connection styling and sticky groups; pnpm check passed with 187 tests, TypeScript, and production build, and git diff --check passed. Merge commit pending.

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
