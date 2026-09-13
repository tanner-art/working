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

## READY

### TASK-002 - Split ThoughtObject into CaptureRecord / Interpretation / Semantic Object

Status: READY
Owner: Unassigned
Reviewer: Unassigned
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
Commit: pending
Review: pending

---

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

### TASK-014 - Update QA_CHECKLIST.md Git Policy Section

Status: READY
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

Result:
Commit: pending
Review: pending

---

## BACKLOG

Tasks below are generated from TASK-001 / docs/ARCHIVE_SALVAGE_AUDIT.md. They are blocked on the dependencies listed and are not to be newly assigned until promoted to READY.

### TASK-003 - Introduce ProposedAction and Explicit Confirmation

Status: BACKLOG
Owner: Unassigned
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
Commit: pending
Review: pending

---

### TASK-004 - Port Interpreter Heuristics Behind an Interpretation-Service Interface

Status: BACKLOG
Owner: Unassigned
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
Commit: pending
Review: pending

---

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

None.

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
Commit: pending
Review: pending
