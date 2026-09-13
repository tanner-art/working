# Threadline Implementation Status

Canonical, living status doc. Updated 2026-09-13 by TASK-012. This supersedes the `wip/pre-orchestration`-era `docs/IMPLEMENTATION_STATUS.md` (never present on `main`; only ever existed on the archived branch). For the full historical audit — feature-by-feature KEEP/MODIFY/DROP/UNCLEAR findings, architectural reasoning, and the proposed salvage dependency order — see [docs/ARCHIVE_SALVAGE_AUDIT.md](ARCHIVE_SALVAGE_AUDIT.md). This document does not restate that audit; it tracks current reality and links each open gap to a `TASKS.md` entry.

## Current stack

- React + TypeScript + Vite
- Browser localStorage for the initial persisted repository
- No separate stores per screen and no UI state framework
- `pnpm check` runs `vitest run` then the production build; GitHub Actions runs the same gate

## Currently implemented (on `main`)

- Text capture with a deterministic, regex-based interpreter (`src/interpreter.ts`) classifying into Idea, Action, Reminder, or Project with confidence and rationale.
- Review screen for uncertain interpretations, with type correction and confirm-to-object.
- Today screen showing confirmed actions and fixed commitments.
- A separate Commitments view (time-bound reminders and commitments only; no flexible execution work mixed in).
- An infinite-feeling pan/zoom Canvas with text nodes, groups, arrows, drag, deletion, and persistence — no undo/redo, no freehand or arbitrary shapes, no resize.
- A single persisted `AppState` (`ThoughtObject[]` + `CanvasElement[]`) in `src/store.ts`, loaded/saved to localStorage with silent seed-data fallback on any read/parse failure.

## Architecture mismatches (tracked, not yet fixed)

The current MVP predates the entity boundaries in `docs/ARCHITECTURE.md`. Specifically:

| Gap | Architecture requirement | Tracked by |
| --- | --- | --- |
| `ThoughtObject` fuses original content, interpretation, and lifecycle state into one record | Separate CaptureRecord / Interpretation / Semantic Object (D-002) | TASK-002 |
| `reminder` is a first-class `ObjectKind` | Reminder is an attached instruction, not a core object (D-004) | TASK-002 |
| Commitment and CalendarEvent are not distinguished; `fixedCommitments()` conflates `commitment` and `reminder` kinds | Commitment and CalendarEvent are distinct (D-005) | TASK-002, TASK-007 |
| `confirmObject()` sets `status: 'confirmed'` directly from a click, and the generic object editor can also set status to `confirmed` via a plain dropdown | Consequential transitions require one explicit, traceable confirmation gesture (D-009) | TASK-003 |
| `Relationship` is a flat `{targetId, type}` pair | Relationships need explicit endpoint identity, scope, and provenance | TASK-005, TASK-006 (bundled into TASK-002/003) |
| `loadState`/`saveState` silently fall back to seed data or swallow write failures | Persistence must fail loud and preserve user work | TASK-011 |
| Canvas has no undo/redo and no revision history | Canvas edits should create preserved revisions (OD-002, open) | TASK-010 |

## Incomplete / deferred features

Intentionally deferred, not yet scheduled as tasks:

- Real speech recognition (voice capture is a placeholder affordance only).
- Provider-backed (AI) interpretation — the interpreter is deterministic and explicitly acknowledged as a stopgap (TASK-004 relocates it behind an interface but does not add a real model).
- External calendar sync, collaborative/remote persistence.
- Freehand canvas paths, general shapes, resize handles, multi-select, true nested grouping.
- Adaptive Plan (recalculating execution allocations), morning digest delivery mechanism, ROI optimization, autonomous scheduling.
- Project/objective containment UI (Objects workbench, parent/child linking, dependency graph) — implemented once on `wip/pre-orchestration` but not yet ported to the current architecture; see TASK-005, TASK-006, TASK-008.

## Reusable work not yet ported

`docs/ARCHIVE_SALVAGE_AUDIT.md` found substantial application work on the archived `wip/pre-orchestration` branch built on top of the current architecture docs but against the old flat `ThoughtObject` model. None of it has been ported to `main` yet. Per-item classification and reasoning live in the audit; current porting status:

| Item | Audit verdict | Status |
| --- | --- | --- |
| `canvasHistory.ts` undo/redo stack | MODIFY | Not ported — TASK-010 (READY) |
| `dependencies.ts` cycle-safe dependency graph | MODIFY | Not ported — TASK-005 (BACKLOG, needs TASK-002/003) |
| `morningDigest.ts` | MODIFY | Not ported — TASK-007 (BACKLOG, needs TASK-002) |
| `store.ts` load/save failure handling | KEEP | Not ported — TASK-011 (READY) |
| `objectWorkflow.ts` parent/child + dependency-aware helpers | MODIFY | Not ported — TASK-005/TASK-006 (BACKLOG) |
| `interpreter.ts` confidence/ambiguity heuristics | MODIFY | Not ported — TASK-004 (BACKLOG, needs TASK-002) |
| App.tsx UI surfaces (Objects workbench, digest strip, dependency/parent editors, history panel) | MODIFY / UNCLEAR (confirm flow) | Not ported — TASK-008 (BACKLOG) |
| `docs/QA_CHECKLIST.md` | MODIFY | Done — TASK-014: ported with Git Policy section rewritten to reference AGENTS.md; North Star Fit/Product Behavior/Data Safety unchanged |
| `docs/OVERNIGHT_LOG.md` | DROP | Done — TASK-013: file never existed on `main`, so nothing to remove; reviewed and found no rationale not already captured in this doc, `docs/ARCHIVE_SALVAGE_AUDIT.md`, or `docs/DECISIONS.md` |

## Technical debt

- No automated accessibility testing; the archived branch's fixes (labeled filters, native controls) were never ported since the UI they apply to isn't on `main` yet.
- `pnpm check` covers unit tests and build only; no browser/E2E smoke coverage exists on `main`.
- No data migration tooling exists yet for the entity split TASK-002 will require.

## Proposed follow-up tasks

None beyond what is already tracked in `TASKS.md` (TASK-002 through TASK-014, sourced from `docs/ARCHIVE_SALVAGE_AUDIT.md`). This document will be updated as those tasks land; it should not accumulate a second, divergent backlog.
