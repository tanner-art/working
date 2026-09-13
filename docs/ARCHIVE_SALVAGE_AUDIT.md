# Audit: `wip/pre-orchestration` vs `main`

Completed 2026-09-13 as TASK-001 (Audit Current Implementation Against Architecture). Read-only analysis: no application code was modified and nothing was merged during this audit.

## Branch relationship (important context)

`wip/pre-orchestration` and `main` share a common ancestor at **`cf1e98e`** ("docs: define capture provenance and reversible semantic architecture") — the commit that introduced the current `docs/ARCHITECTURE.md` and rewrote `docs/NORTH_STAR.md` into the provenance/entity-boundary model. From there:

- `main` added `50bd2f3` — the multi-agent process docs (`AGENTS.md`, `TASKS.md`, `docs/DECISIONS.md`, `docs/ROADMAP.md`).
- `wip/pre-orchestration` added `7c0ee6b` — a single large squash commit of overnight application work.

So "pre-orchestration" means *before the multi-agent task-board process existed*, not before the architecture rewrite. The wip work was done **with** `ARCHITECTURE.md`/`NORTH_STAR.md` already in place — `docs/OVERNIGHT_LOG.md` shows explicit awareness of provenance and confirmation rules. It did not, however, implement the entity split those docs call for; it kept extending the pre-existing flat `ThoughtObject` model. That's the central tension running through this whole audit.

---

## 1. `src/canvasHistory.ts`

1. **What it does**: Pure functions (`commitCanvas`, `undoCanvas`, `redoCanvas`, `sameCanvas`) implementing a past/present/future undo-redo stack over `CanvasElement[]`, capped at 25 steps, with a JSON-equality dedupe check.
2. **Architectural fit**: `ARCHITECTURE.md` requires canvas edits to "create new preserved revisions... rather than mutating historical evidence," with undo/redo distinct from the source revision an interpretation references (OD-002, still open). This implementation is a session-only, in-memory stack (lives in React state, not persisted) — it satisfies UX-level undo/redo but not the durable revision-provenance requirement.
3. **Classification: MODIFY**. The stack algorithm itself is clean, tested, and framework-agnostic — worth keeping. It needs to be re-hosted once canvas revisions are persisted per whatever OD-002 resolves to.
4. **Dependencies**: Resolution of OD-002 (canvas revision granularity); eventual `CaptureRecord`-backed canvas persistence.
5. **Task?**: Yes, but only the wiring — the module can be merged into the codebase now with no changes required.
6. **Suggested task**: *TASK-010 — Wire canvasHistory.ts into current canvas and decide OD-002 revision persistence.*

---

## 2. `src/dependencies.ts`

1. **What it does**: `unresolvedDependencies` (are a thing's `depends_on` targets incomplete?) and `dependencyCandidates` (valid, cycle-safe candidates to add as a prerequisite) over `ThoughtObject.relationships`.
2. **Architectural fit**: Matches `ARCHITECTURE.md`'s scheduling section almost exactly — "Dependencies are graph constraints governing order and readiness... cycles... should surface for resolution, not be hidden inside a score." The cycle-detection algorithm is sound and reusable. But it operates on the flat `{targetId, type}` relationship shape, while `ARCHITECTURE.md` calls for relationships with "explicit endpoint identities, scope, and provenance."
3. **Classification: MODIFY**. Logic is directly portable; the `Relationship` type it consumes needs to grow scope/provenance fields first.
4. **Dependencies**: Entity-model split (item 5 below) and `Relationship` type upgrade.
5. **Task?**: Yes.
6. **Suggested task**: *TASK-005 — Port dependency-graph logic onto the upgraded Relationship model.*

---

## 3. `src/morningDigest.ts`

1. **What it does**: `buildMorningDigest` buckets objects into fixed-today, upcoming (next 3, sorted), recommended actions, review-needed, and project/objective signals, using local-calendar-day date matching.
2. **Architectural fit**: Matches `NORTH_STAR.md`'s Morning Digest section and `ROADMAP.md` M3 well conceptually. But it draws its "commitments" from `fixedCommitments()`, which conflates `kind === 'commitment' || kind === 'reminder'` — directly violating D-004 (Reminder is not a core object) and D-005 (Commitment vs CalendarEvent are distinct). It also has no delivery mechanism (7 AM trigger) — it's a pure data-shaping function.
3. **Classification: MODIFY**. The bucketing/selection logic and date-matching bug fix (local vs UTC) are good and worth keeping; the underlying commitment/reminder source needs to be rebuilt on the split entities.
4. **Dependencies**: Commitment/CalendarEvent split, Reminder → attached-instruction conversion (both part of the core entity-model task).
5. **Task?**: Yes.
6. **Suggested task**: *TASK-007 — Rebuild Morning Digest on CalendarEvent/Commitment split; add M3 delivery mechanism.*

---

## 4. `src/App.tsx` changes

1. **What it does**: Adds an "Objects" workbench view (search/filter/archive-toggle), a Today digest strip + expandable digest detail sections, a blocked-vs-ready action distinction, a dependency editor in the object drawer, parent/child project linking UI (cycle-safe parent picker, child list, parent breadcrumb), canvas undo/redo buttons + keyboard shortcuts, load/save failure UI with retry and JSON backup download, and an object History panel. Also fixes canvas node placement to account for zoom+pan.
2. **Architectural fit**: Directionally strong — this is exactly the kind of UI the North Star describes (dependency-aware execution, project containment, reversibility surfaced to the user, resilient persistence). But it's all wired directly against the flat `ThoughtObject`/`AppState`, so every one of these features will need re-plumbing once the entity split lands. One specific piece is genuinely undecided rather than just "needs rework": `confirmObject()` is invoked directly from the "Confirm interpretation" button — this *is* an attempt at answering OD-001 (what interaction counts as confirmation), but nobody has actually ratified that as the answer.
3. **Classification: MODIFY** (bulk of the file); **UNCLEAR** for the Review-confirmation semantics specifically (OD-001).
4. **Dependencies**: Entity-model split; Relationship upgrade; Commitment/CalendarEvent split; resolution of OD-001 for the confirm flow.
5. **Task?**: Yes, split into the UI-reintegration task plus a standalone product decision.
6. **Suggested tasks**: *TASK-008 — Reintegrate salvaged UI (workbench, digest strip, dependency/parent editors, history panel, storage-failure UI) onto the new entity model.* / *TASK-009 (decision) — Ratify OD-001: what interaction confirms an Action.*

---

## 5. Existing capture / semantic functionality (`interpreter.ts`, `objectWorkflow.ts`, `store.ts`, `domain.ts`)

1. **What it does**:
   - `interpreter.ts` (+6 lines): adds heuristics to route clustered/comma-separated captures to `project`, explicit "remind me" phrasing to `reminder`, and — most usefully — detects uncertainty/conditionals/questions/cancellations and caps confidence, pushing them to Review.
   - `objectWorkflow.ts`: adds `setBelongsTo`, cycle-safe `parentCandidates`, `parentObject`, `projectChildren`; makes `confirmedActions` dependency-aware; stops overwriting recorded confidence/interpretation on confirm/reclassify.
   - `store.ts`: `loadStateResult`/`saveState` now surface load/save failures instead of silently substituting seed data or swallowing exceptions.
   - `domain.ts`: **unchanged** — still defines `reminder` as a first-class `ObjectKind`, and `ThoughtObject` still fuses original content + interpretation + metadata into one record.
2. **Architectural fit**:
   - The confidence/rationale heuristics align well with `NORTH_STAR.md` rule 5 ("never silently create a hard commitment from ambiguous input") and rule 6 (preserve provenance) — good direction for a placeholder interpreter, still explicitly deterministic/non-AI per its own comments.
   - The "preserve recorded interpretation on confirm" fix is a direct, correct instance of D-001 (preserve original expression) even under the old model.
   - `store.ts`'s fail-loud/retry/backup pattern is architecture-agnostic — `ARCHITECTURE.md` just says persistence must support "stable references... consistent updates," without prescribing a backend. This survives any future migration essentially unchanged.
   - `domain.ts` is the actual architecture mismatch: it's the pre-cf1e98e model `ARCHITECTURE.md` itself names as needing replacement ("Future implementation should separate capture provenance from semantic meaning... replace reminder objects with attached instructions, distinguish commitments from events").
3. **Classification**: `store.ts` changes — **KEEP** (no rework needed). `interpreter.ts` heuristics — **MODIFY** (keep the rules, but relocate behind a proper Interpretation-service boundary in M1). `objectWorkflow.ts` additions — **MODIFY** (algorithms portable, types need to change). `domain.ts` (unchanged, inherited) — **MODIFY**, and it's the highest-priority one: it's the foundational blocker for nearly everything else in this audit.
4. **Dependencies**: None for `store.ts` (can land immediately). The interpreter/workflow items depend on the entity-model split for their target shape, though the logic itself doesn't need to change.
5. **Task?**: Yes, several.
6. **Suggested tasks**: *TASK-002 — Split ThoughtObject into CaptureRecord + Interpretation + Semantic Object, replace Reminder-as-kind with attached instructions, split Commitment/CalendarEvent (implements D-001, D-004, D-005; foundational).* / *TASK-003 — Introduce ProposedAction and explicit confirmation, port `objectWorkflow.ts` helpers onto it (D-003, depends on OD-001).* / *TASK-004 — Port interpreter.ts heuristics behind an Interpretation-service interface (M1).* / *TASK-011 — Land store.ts load/save-failure handling as-is (no dependencies).*

---

## 6. `docs/IMPLEMENTATION_STATUS.md`

1. **What it does**: An overnight-generated status report — verified baseline (37 tests + build passing), a gap table per area (capture, review, project formulation, execution, commitments, digest, canvas, persistence, accessibility), and pending-verification items.
2. **Architectural fit**: This is, almost word-for-word, the deliverable `TASKS.md` TASK-001 (the task this very audit is fulfilling) asks for — "current stack, implemented features, incomplete features, architecture mismatches, reusable components, technical debt, proposed follow-up tasks." It's honest about gaps and doesn't overclaim (explicitly disclaims that passing tests doesn't prove North Star compliance).
3. **Classification: MODIFY**. Valuable raw material and a reasonably rigorous self-assessment, but it predates the task-board process, isn't framed in TASK-ID terms, and should be reconciled with this audit rather than kept as a second, divergent status doc.
4. **Dependencies**: This audit (supersedes/should be merged with it).
5. **Task?**: Yes — a doc-only task.
6. **Suggested task**: *TASK-012 — Merge IMPLEMENTATION_STATUS.md content with this audit into a single canonical status doc referencing TASKS.md IDs.*

---

## 7. `docs/OVERNIGHT_LOG.md`

1. **What it does**: A chronological changelog of a single long autonomous session — every incremental feature/fix, each ending with a test count and "browser verified" note.
2. **Architectural fit**: The *process* it documents (single agent, ad-hoc checkpointing, "do not commit until told", progress tracked in a log file) is exactly what `AGENTS.md`/`TASKS.md` (established in `50bd2f3`) replaced with the task-board lifecycle. The *content* is a legitimate historical record and occasionally the only place a design rationale is stated (e.g., why confidence isn't overwritten on confirm).
3. **Classification: DROP** as an ongoing artifact/process (superseded by `TASKS.md`); the content is worth mining once into `git log`/commit messages or `DECISIONS.md` where a rationale is still load-bearing, then the file itself can go.
4. **Dependencies**: None — can be actioned immediately.
5. **Task?**: Optional, low priority.
6. **Suggested task**: *TASK-013 (optional) — Extract any still-relevant rationale from OVERNIGHT_LOG.md into DECISIONS.md, then retire the file.*

---

## 8. `docs/QA_CHECKLIST.md`

1. **What it does**: A pre-completion checklist grouped into North Star Fit, Product Behavior, Data Safety, and Git Policy.
2. **Architectural fit**: The North Star Fit section maps cleanly onto current decisions (D-001 preserve original content, D-007 canvas structure preserved, independent priority dimensions). The Git Policy section ("do not commit/push until told", "keep progress in OVERNIGHT_LOG.md") is obsolete under the new `AGENTS.md` git rules (work on assigned branch, commit, never merge to main, report SHA).
3. **Classification: MODIFY**. Keep and update the North Star Fit / Product Behavior / Data Safety sections (they're a genuinely useful review gate); replace the Git Policy section with a reference to `AGENTS.md`.
4. **Dependencies**: None blocking; light-touch edit.
5. **Task?**: Yes, small.
6. **Suggested task**: *TASK-014 — Update QA_CHECKLIST.md's Git Policy section to reference AGENTS.md; keep the rest.*

---

## 9. Other changes in `7c0ee6b`

- **`README.md`**: Adds links to `IMPLEMENTATION_STATUS.md`/`QA_CHECKLIST.md` and a note about needing a provider-backed interpretation service. **MODIFY** — fine content, needs updating once docs 6–8 above are resolved. No standalone task; fold into TASK-012.
- **`src/interpreter.test.ts`** (+217 lines): Substantial regression coverage for the interpreter/workflow/digest/dependency/canvas-history changes above. **MODIFY** — the testing *discipline* (one test per behavior change, tracked pass counts) is worth keeping as a norm; individual test bodies will need rewriting alongside whatever they cover once the entity split lands. No standalone task — travels with each corresponding code task.
- **`src/styles.css`** (+31 lines): Presentational support for the digest strip, dependency editor, workbench controls, and storage alert. **KEEP** — purely cosmetic, no architectural coupling, ports trivially alongside whichever UI pieces survive.

---

## Cross-cutting UNCLEAR item

- **Single-parent (`belongs_to`) project hierarchy**: The wip work models project/objective membership as one parent per object. `NORTH_STAR.md` doesn't specify whether an object may belong to multiple projects/objectives simultaneously (matrix-style), and this isn't in `DECISIONS.md`'s open list either. Worth a deliberate decision before the Relationship-model rework (item in TASK-005/006) locks in single-parent semantics by default. Tracked as OD-007.

---

## Proposed salvage dependency order

```
Track A (no dependencies, can start immediately):
  TASK-011  store.ts load/save-failure handling            → land as-is
  TASK-013  Mine OVERNIGHT_LOG.md into DECISIONS.md, retire it   → land as-is
  TASK-014  QA_CHECKLIST.md Git Policy section update       → land as-is

Track B (foundational — blocks nearly everything else):
  TASK-002  Entity split: CaptureRecord / Interpretation / SemanticObject,
            Reminder → attached instruction, Commitment/CalendarEvent split
      ↓
  TASK-009  (decision) Ratify OD-001 confirmation semantics
      ↓
  TASK-003  ProposedAction + explicit confirmation, port objectWorkflow.ts helpers
      ↓
  Relationship type upgrade (scope + provenance) — bundle into TASK-002/003
      ↓
  ┌─────────────────────────────┬─────────────────────────────┐
  TASK-005  Port dependencies.ts       TASK-006  Port parent/child
            onto upgraded Relationship            linking (belongs_to)
            (needs decision on multi-parent question first — OD-007)
  └─────────────────────────────┴─────────────────────────────┘
      ↓
  TASK-007  Rebuild Morning Digest on Commitment/CalendarEvent split
      ↓
  TASK-008  Reintegrate salvaged App.tsx UI (workbench, digest strip,
            dependency/parent editors, history panel) onto new model

Track C (loosely coupled, port whenever convenient, ideally after TASK-002):
  TASK-004  Port interpreter.ts heuristics behind an Interpretation-service interface
  TASK-010  Wire canvasHistory.ts into canvas; resolve OD-002 for revision persistence

Docs (ongoing, informed by all of the above):
  TASK-012  Merge IMPLEMENTATION_STATUS.md + README updates into canonical status doc
```

No application code was modified and nothing was merged — this is analysis only.
