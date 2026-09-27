# Product Execution Graph — Coherent Behavior Packages

Updated: 2026-09-25, Europe/Madrid

Status: authoritative staged execution graph for the owner priorities in
`docs/OWNER_PRODUCT_PRIORITIES_2026-09-25.md`. This document changes package
decomposition only. It does not change product decisions, activate the Factory,
or authorize dispatch from the preserved PAUSED/dry-run checkpoint.

## Package primitive

One implementation package delivers a coherent behavior that can be exercised
end-to-end, even when that package crosses UI, domain, persistence, migration, and
test layers. “One concept per package” is not a valid reason to split work.

Every implementation package has one exact-target independent reviewer who is not
its implementer. That review binds to the package PR and implementation commit.
Those reviews are lifecycle evidence, not additional conceptual product packages.

Four separate ASSURANCE gates validate integrated feature commits. Each gate
records exactly one immutable integration SHA and the implementation package SHAs
contained in it. “Latest,” a collection of package heads, or an uncommitted
workspace is not valid assurance evidence.

## Permanent decomposition heuristic

The orchestrator penalizes a proposed split when:

- packages heavily modify the same core files;
- one package produces state that only another package makes useful;
- a package can pass without an observable user-facing effect;
- acceptance depends on behavior owned by another package;
- several packages form one unavoidable sequential chain; or
- final assurance cannot bind the result to one integrated artifact.

It favors a split when:

- each package can be independently exercised and verified;
- file ownership is mostly distinct;
- rollback boundaries are meaningful;
- merging the package does not intentionally leave a broken product path; and
- the split enables real concurrency rather than parallel branches that must
  repeatedly resolve the same files.

Every package records `contention_surfaces`, `expected_writer`,
`allowed_concurrent_packages`, `sequencing_requirement`, `persistence_owner`,
`observable_completion`, `reviewer`, and `assurance_gate` as planning metadata.

### Decomposition gate

The orchestrator assesses decomposition at every ON DECK → READY transition and
stores a structured `decomposition_assessment` evidence record. It records each
penalty/favor condition above as `true`, `false`, or `not_applicable`, with a
reason and the exact package/path evidence.

READY is rejected when any of these mandatory conditions fails:

1. no end-to-end observable completion condition;
2. acceptance depends on behavior with no owning package;
3. two concurrently eligible packages share a contention surface without one
   exclusive writer;
4. persistence ownership is absent or duplicated;
5. the assurance gate cannot name one future integrated artifact; or
6. exact paths, reviewer separation, or required dependencies are unresolved.

Other penalty conditions require the orchestrator to merge, resequence, or narrow
the packages. An exception requires explicit product-owner approval recorded in
the assessment with its reason and affected package IDs. The orchestrator that
proposed the graph cannot self-approve an exception. PASS plus the assessment ID
is required READY evidence.

## Contention surfaces

| Surface | Why it is high conflict | Expected writer | Allowed concurrency |
| --- | --- | --- | --- |
| `src/App.tsx` | Global navigation, Review mounting, Calendar/Schedule mounting, Canvas focused shell, global search | One integration owner at a time; named below | No concurrent writer |
| `src/domain.ts` | Shared persisted and compatibility types | Package owning the affected persisted behavior; additive imports preferred | No concurrent writer |
| `src/migration.ts` | Evidence-preserving schema reconciliation | The package owning the schema change | No concurrent writer |
| `src/store.ts` | Validation and local persistence boundary | The package owning the schema change | No concurrent writer |
| `src/CalendarView.tsx` | Commitment and Calendar rendering | WP-04 | No concurrent writer |
| `src/Canvas.tsx` | Shell and pointer interactions are currently colocated | WP-05, then WP-06 | Sequenced only |
| `src/styles.css` | Global and Canvas responsive rules are colocated | WP-05 for Canvas shell blocks; other packages use feature-scoped sections | No overlapping selector edits |

Before READY, every package must replace “likely files” with an exact path set.
If exact ownership cannot meet this table, the package returns to ON DECK for a
boundary change rather than relying on merge conflict resolution.

## Implementation graph

### WP-11 — Cross-feature surface composition boundary — 10 agent hours

- **Product behavior delivered:** every existing application surface continues to
  navigate, mount, restore focus, and preserve state through one declarative
  composition boundary. New Review, Schedule, focused Canvas, Adaptive Plan, and
  Search modules can be added without editing `App.tsx` or a shared registration
  list.
- **Owned / likely files:** sole writer of `src/App.tsx`; new
  `src/appSurfaceRegistry.ts`, `src/surfaces/` discovery contract, and parity tests;
  limited `src/appRoutes.ts` changes.
- **Dependencies:** current main only.
- **Acceptance criteria:** all existing views and navigation behave identically;
  surface modules are discovered from distinct files through a validated contract;
  duplicate IDs, malformed exports, or unauthorized shell overrides fail closed;
  existing account, save, modal, Canvas, and focus behavior passes regression tests.
- **Persistence owner:** none; the extraction may not change stored formats or
  write ordering.
- **Observable completion:** navigate through every existing surface, enter/exit
  Canvas, open/close an object, and reload without behavioral or data change.
- **Reviewer:** independent application-shell reviewer, not the implementer.
- **Parent assurance gate:** common reviewed baseline included by AG-01–AG-04.
- **Contention metadata:** exclusive writer of `App.tsx`; no other package in this
  graph may edit it. Later packages add distinct files under `src/surfaces/`.
- **Sequencing requirement:** first package in this graph. No feature package may
  become READY until WP-11 is approved.
- **Paired review estimate:** 3 agent hours.

### WP-01 — Review resolution core — 18 agent hours

- **Product behavior delivered:** Review exposes exactly Action, Commitment,
  Reminder, and Idea through one typed continuation boundary. Captures remain in
  Review until a resolution completes. Idea resolves end-to-end with no required
  metadata. The other outcomes call three fixed adapter modules that initially
  fail safely and are replaced, one-for-one, by WP-02, WP-03, and WP-04.
- **Owned / likely files:** new `src/ReviewResolution.tsx`,
  `src/reviewResolution.ts`, safe placeholder adapters at
  `src/resolutions/action.ts`, `reminder.ts`, and `commitment.ts`, a distinct
  `src/surfaces/review.tsx` module, and focused tests; limited
  `src/objectWorkflow.ts` changes. No `App.tsx` edit.
- **Dependencies:** approved WP-11 commit.
- **Acceptance criteria:** exactly four primary choices; unresolved captures remain
  visible; Idea leaves Review and appears in Ideas; each non-Idea choice invokes
  the exact registered continuation; source/history remain immutable; missing or
  failed continuations leave the item safely in Review with a recoverable message.
- **Persistence owner:** Review resolution audit/history and Idea resolution only.
  WP-02 owns Action state, WP-03 Reminder state, and WP-04 Commitment state.
- **Observable completion:** on an integrated build, one capture can exercise each
  choice; Idea completes immediately and the other three open their real behavior.
- **Reviewer:** independent React/domain reviewer, not the implementer.
- **Parent assurance gate:** AG-01.
- **Contention metadata:** sole initial writer of the three exact adapter files.
  Ownership transfers serially to WP-02, WP-03, and WP-04; no central registry or
  mounting edit is permitted later.
- **Sequencing requirement:** after WP-11 and before WP-02/WP-03/WP-04.
- **Paired review estimate:** 4 agent hours.

### WP-02 — Action staging and persistence — 18 agent hours

- **Product behavior delivered:** resolving a capture as Action creates a durable,
  non-executable staged Action visible in Schedule. It persists locally and in
  account storage and creates no CalendarEvent until a later explicit scheduling
  gesture.
- **Owned / likely files:** new `src/actionStaging.ts`, `src/ScheduleView.tsx`, and
  tests; Action-specific additions to `src/domain.ts`, `src/migration.ts`, and
  `src/store.ts`; temporal-event service calls use existing Calendar projection;
  replaces only `src/resolutions/action.ts`; adds a distinct
  `src/surfaces/schedule.tsx`; no `App.tsx` or `CalendarView.tsx` edits.
- **Dependencies:** approved WP-01 typed continuation interface. It does not wait for
  Reminder or Commitment work.
- **Acceptance criteria:** Review→Action→Schedule works; reload and account
  round-trip preserve the staged item and priority; Today, CalendarEvents,
  notification delivery, and Adaptive Plan exclude it until explicitly eligible;
  scheduling creates a separately confirmed CalendarEvent; reversal preserves
  capture and history.
- **Persistence owner:** staged Action lifecycle, persisted priority, explicit
  scheduling state, and compatibility migration.
- **Observable completion:** a classified Action appears in Schedule after reload,
  remains unscheduled by default, and enters Calendar only after the schedule
  action.
- **Reviewer:** independent workflow/persistence reviewer.
- **Parent assurance gate:** AG-01.
- **Contention metadata:** sole writer of Action schema changes. Cannot run
  concurrently with WP-03 or WP-04 while any of them owns `domain.ts`,
  `migration.ts`, or `store.ts`; implementation work in new files may overlap.
- **Sequencing requirement:** schema commit lands before WP-03/WP-04 schema commits;
  UI modules may be developed concurrently after the WP-01 interface is stable.
- **Paired review estimate:** 4 agent hours.

### WP-03 — Reminder behavior — 16 agent hours

- **Product behavior delivered:** Reminder resolution creates an instruction
  attached to a semantic object. Specific reminders surface at the selected time;
  Daily-log reminders remain visible in the daily log until handled or dismissed.
- **Owned / likely files:** new `src/reminderWorkflow.ts`,
  `src/ReminderResolution.tsx`, `src/reminderProjection.ts`, tests, and
  Reminder-specific schema/migration additions; replaces only
  `src/resolutions/reminder.ts`; adds its own daily-log projection module. No
  `App.tsx` edit.
- **Dependencies:** WP-01 continuation interface and the reviewed schema baseline
  from WP-02.
- **Acceptance criteria:** exactly Specific and Daily log modes; every instruction
  has a semantic target and source evidence; Specific has a confirmed date/time and
  becomes visibly due; Daily log is visible across reloads; handled/dismissed state
  removes it from the active projection without deleting evidence; delivery
  unavailability has a visible safe fallback.
- **Persistence owner:** ReminderInstruction modes, target/source linkage,
  due/active/handled/dismissed state, and compatibility migration.
- **Observable completion:** both modes can be created from Review, reloaded, seen
  in the correct surface, and handled without exposing graph mechanics.
- **Reviewer:** independent reminder/temporal/persistence reviewer.
- **Parent assurance gate:** AG-01.
- **Contention metadata:** expected writer of Reminder schema changes; new UI and
  projection files may run concurrently with WP-04 after the shared migration
  baseline is merged.
- **Sequencing requirement:** shared schema edits follow WP-02; no other necessary
  sequencing.
- **Paired review estimate:** 4 agent hours.

### WP-04 — Commitment handling — 14 agent hours

- **Product behavior delivered:** Commitment classification opens the minimal
  Title, Date, Time, and Dependencies flow, persists the obligation separately
  from temporal scheduling, and exposes a stable retrieval/navigation contract.
- **Owned / likely files:** new `src/CommitmentResolution.tsx` and
  `src/commitmentWorkflow.ts`; `src/calendarEntry.ts`, `src/CalendarView.tsx`,
  dependency helpers, Commitment schema/migration additions, and focused tests.
  Replaces only `src/resolutions/commitment.ts`; no `App.tsx` edit.
- **Dependencies:** WP-01 continuation interface and the reviewed schema baseline
  from WP-03.
- **Acceptance criteria:** only four primary fields; dependencies persist without
  exposing graph internals; saving the obligation creates no CalendarEvent;
  date-only fixed deadline and date+time event require separate traceable temporal
  confirmation; retrieval returns a stable object/route identity; stale identities
  fail safely.
- **Persistence owner:** Commitment obligation fields, dependency links, retrieval
  identity, and compatibility migration. CalendarEvent remains separately owned by
  the temporal model.
- **Observable completion:** a Review capture becomes a retrievable Commitment,
  survives reload, and appears on Calendar only after explicit scheduling.
- **Reviewer:** independent temporal/domain reviewer.
- **Parent assurance gate:** AG-01.
- **Contention metadata:** sole expected writer of Commitment changes in
  `CalendarView.tsx` for this graph.
- **Sequencing requirement:** shared schema edits follow WP-03; no second WP-02
  integration phase is permitted.
- **Paired review estimate:** 4 agent hours.

### WP-05 — Mobile Canvas shell — 14 agent hours

- **Product behavior delivered:** mobile Canvas is a focused, full-viewport mode
  with hidden normal navigation, a fixed top toolbar, compact accessible controls,
  progressive disclosure, and a safe top-left X exit.
- **Owned / likely files:** expected writer of the Canvas shell in `src/Canvas.tsx`,
  a distinct `src/surfaces/canvas.tsx`, and Canvas/mobile sections of
  `src/styles.css`; focused shell tests. No `App.tsx` edit.
- **Dependencies:** approved WP-11 commit plus existing Canvas Bank and save/exit guards.
- **Acceptance criteria:** toolbar remains fixed through canvas transforms; primary
  controls fit 390 CSS pixels without horizontal scrolling; every icon has an
  accessible name; X flushes text/save queues and returns to the prior context;
  normal navigation consumes no Canvas editing space.
- **Persistence owner:** none; existing Canvas Bank/save ownership is preserved.
- **Observable completion:** enter a Canvas on a phone-sized viewport, edit a title
  or block, exit with X, and reopen with the edit preserved.
- **Reviewer:** independent mobile React/CSS/accessibility reviewer.
- **Parent assurance gate:** AG-02.
- **Contention metadata:** expected writer of `Canvas.tsx` and Canvas CSS during
  this package; no concurrent writers on those files.
- **Sequencing requirement:** precedes WP-06 because it establishes stable viewport
  and toolbar boundaries.
- **Paired review estimate:** 3 agent hours.

### WP-06 — Mobile Canvas interaction — 18 agent hours

- **Product behavior delivered:** tap selection, drag-selected movement,
  finger-safe resize, empty-canvas pan, pinch zoom, outside deselect, and complete
  gesture arbitration work together without text-edit or undo regressions.
- **Owned / likely files:** interaction regions of `src/Canvas.tsx`,
  `src/canvasGestures.ts`, `src/canvasGeometry.ts`, relevant scoped CSS, and gesture
  tests.
- **Dependencies:** approved WP-05 commit.
- **Acceptance criteria:** one committed drag creates one undo step; resize target
  is at least 44×44 CSS pixels; two pointers safely cancel/transition any one-pointer
  gesture; textarea editing remains reliable; pointer cancellation/loss commits no
  stale movement; pan/zoom never alter content coordinates; existing pen, lasso,
  connection, and refinement interactions pass regression tests.
- **Persistence owner:** current Canvas geometry and viewport only through existing
  repository/session interfaces; no semantic persistence changes.
- **Observable completion:** the full select→move→resize→pan→pinch→deselect sequence
  succeeds on a physical phone and persists after reopen.
- **Reviewer:** independent touch-state-machine reviewer.
- **Parent assurance gate:** AG-02.
- **Contention metadata:** sole writer of `Canvas.tsx` and gesture/geometry files
  after WP-05; no concurrent Canvas implementation package.
- **Sequencing requirement:** strictly after WP-05.
- **Paired review estimate:** 4 agent hours.

### WP-07 — Canvas provenance and semantic integrity — 8 agent hours

- **Product behavior delivered:** mobile manipulation cannot create semantic
  meaning, confirmation, or notification eligibility, and it cannot mutate source
  evidence referenced by an existing interpretation. Capturing Canvas content uses
  the existing explicit semantic boundary.
- **Owned / likely files:** tests only: a focused
  `src/canvasSemanticIntegrity.test.ts` fixture plus existing Canvas provenance
  test files named exactly before READY. No production, migration, or persistence
  file is in scope.
- **Dependencies:** approved WP-06 commit.
- **Acceptance criteria:** gesture-only edits create no semantic object or
  confirmation; pre-existing captured evidence remains reconstructable under the
  current provenance policy; a new semantic capture is explicit and references the
  correct current expression; account/local round trips preserve the same result.
- **Persistence owner:** none. Existing capture/interpretation provenance remains
  authoritative; this package owns regression evidence only.
- **Observable completion:** compare an interpretation's referenced evidence before
  and after move/resize/pan/zoom; it is unchanged, while a later explicit capture
  records the current expression through the established boundary.
- **Reviewer:** independent provenance/migration reviewer.
- **Parent assurance gate:** AG-02.
- **Contention metadata:** no production-file ownership. The orchestrator runs the
  adversarial fixture while WP-07 is ON DECK. If it fails, WP-07 becomes BLOCKED
  and a separately named remediation package must own the exact defect and paths;
  WP-07 cannot silently expand into a conditional fix.
- **Sequencing requirement:** fixture planning follows WP-06; READY requires a
  passing fixture or completion of an independently reviewed remediation.
- **Paired review estimate:** 3 agent hours.

### WP-08 — Adaptive Plan behavior — 14 agent hours

- **Product behavior delivered:** a staged Action can be explicitly made eligible
  for the Adaptive Plan, the plan actually consumes it, and the user sees the
  resulting plan consequence. Reversal removes future eligibility without erasing
  provenance or pretending to undo completed external effects.
- **Owned / likely files:** new `src/adaptivePlan.ts`, Action eligibility adapter,
  `src/surfaces/adaptivePlan.tsx`, and focused tests. No `App.tsx` edit.
- **Dependencies:** approved WP-11 commit, WP-02 commit, and AG-01 integrated SHA.
- **Acceptance criteria:** staged Actions are excluded; one explicit gesture adds
  eligibility with audit evidence; the plan consumes the eligible Action and shows
  an observable allocation/recommendation; blocked dependencies remain excluded;
  reversal recalculates the visible plan deterministically.
- **Persistence owner:** Action plan-eligibility gesture/history. Derived plan
  output remains recomputable rather than silently becoming semantic truth.
- **Observable completion:** the same Action is absent before eligibility, visible
  in the plan after confirmation, and absent from the next recalculation after
  reversal.
- **Reviewer:** independent planning/workflow reviewer.
- **Parent assurance gate:** AG-03.
- **Contention metadata:** expected writer of its isolated plan and surface
  modules; it registers through WP-11's composition contract.
- **Sequencing requirement:** after AG-01; otherwise independent of Canvas/Search.
- **Paired review estimate:** 3 agent hours.

### WP-09 — Universal Search indexing and performance — 14 agent hours

- **Product behavior delivered:** one deterministic local index returns complete
  conventional text matches across Captures, Actions, Commitments, Reminders,
  Ideas, and Canvases with source/provenance identities intact.
- **Owned / likely files:** new `src/universalSearch.ts`, source adapters and tests;
  no navigation or `App.tsx` ownership.
- **Dependencies:** AG-01 integrated SHA and existing Canvas Bank records.
- **Acceptance criteria:** all six types are represented once; original capture
  text and current meaning are distinguishable; updates invalidate correctly;
  local/account projections match; malformed/stale source records fail safely;
  a cold query over 10,000 indexed documents completes in at most 100 ms and a warm
  query in at most 50 ms on the repository's CI runner, reported with fixture size
  and environment.
- **Persistence owner:** none; index is derived and rebuildable. Source packages
  remain persistence owners.
- **Observable completion:** a fixed query matrix returns the expected six-type
  result set and recorded latency without network access.
- **Reviewer:** independent search/performance reviewer.
- **Parent assurance gate:** AG-04.
- **Contention metadata:** isolated new files; may run concurrently with WP-05,
  WP-06, WP-07, or WP-08 after AG-01.
- **Sequencing requirement:** only the AG-01 schema baseline is required.
- **Paired review estimate:** 3 agent hours.

### WP-10 — Universal Search navigation — 12 agent hours

- **Product behavior delivered:** a single global search surface opens every valid
  result at the correct source or object and handles stale/invalid results without
  trapping or corrupting state.
- **Owned / likely files:** new `src/UniversalSearch.tsx`,
  `src/searchNavigation.ts`, `src/surfaces/search.tsx`, and search routing tests;
  `src/appRoutes.ts` only if WP-11's exact route contract assigns that path before
  READY. No `App.tsx` edit.
- **Dependencies:** approved WP-11 and WP-09 commits, Commitment retrieval contract
  from WP-04, Schedule surface from WP-02, Reminder projection from WP-03,
  Ideas/Review route from WP-01, and Canvas Bank navigation.
- **Acceptance criteria:** the navigation matrix covers Capture, Action,
  Commitment, Reminder, Idea, and Canvas; every valid result focuses or opens its
  intended destination; back/close restores focus; stale/deleted/unauthorized
  identities show a recoverable result and perform no mutation.
- **Persistence owner:** none.
- **Observable completion:** six representative results navigate correctly in one
  end-to-end run; stale and invalid fixtures fail safely.
- **Reviewer:** independent routing/accessibility reviewer.
- **Parent assurance gate:** AG-04.
- **Contention metadata:** expected writer of isolated search routing and surface
  modules; it registers through WP-11's composition contract.
- **Sequencing requirement:** after WP-09 and the named destination contracts.
- **Paired review estimate:** 3 agent hours.

## Cross-feature cleanup boundary

WP-11 is the only predeclared cross-feature cleanup package. It is activated
because the graph analysis proved `App.tsx` would otherwise have four competing
writers. It has a bounded parity outcome and may not absorb feature behavior.
Further cleanup is not generic assurance work: a gate may raise a concrete
remediation package only for a specific blocking defect with exact paths,
acceptance criteria, and rollback boundary.

## Integrated assurance gates

Every gate below inherits one provenance contract. Its evidence record must name:

- the exact integration SHA, tree hash, merge-target branch/ref, base SHA, and
  ordered parent SHAs;
- every included package ID, PR URL, implementation SHA, paired-review evidence
  ID, reviewer identity, outcome, and reviewer-separation check;
- ancestry or patch-inclusion proof showing that every approved package commit is
  incorporated in the declared order. For an explicitly transferred path, the
  record must include the predecessor SHA/path handoff and each independently
  reviewed successor diff; blob-equality proof is required only for paths that
  were not transferred;
- a base-to-integration diff proving the artifact contains only the declared
  packages and approved remediations, with no unrelated work;
- full validation and the gate-specific acceptance matrix against that exact SHA;
  and
- an assurance reviewer who implemented none of the included packages.

The integration assembler authors no product change. A conflict resolution or
other code change requires a bounded remediation package, independent review, and
a new integration SHA. APPROVED is valid only when the reviewed SHA is the exact
merge target; “latest,” a moving branch, or a collection of heads is invalid.

### AG-01 — Review, Action, Reminder, and Commitment assurance — 10 agent hours

- **Dependencies:** approved WP-01, WP-02, WP-03, and WP-04 commits.
- **Integrated artifact:** one commit SHA containing the approved WP-11 baseline
  and those exact implementation SHAs.
- **Acceptance matrix:** all four Review choices; immutable evidence; Idea storage;
  Action staging/no automatic calendar event; both visible Reminder modes;
  minimal Commitment flow; local/account reloads; retrieval identities; reversal;
  keyboard and 390px touch flows.
- **Reviewer:** independent feature-assurance reviewer who implemented none of the
  four packages.
- **Evidence:** the common provenance record plus matrix results, screenshots,
  findings, and APPROVED/CHANGES_REQUESTED decision.

### AG-02 — Mobile Canvas assurance — 8 agent hours

- **Dependencies:** approved WP-05, WP-06, and WP-07 commits.
- **Integrated artifact:** one commit SHA containing the approved WP-11 baseline
  and those exact implementation SHAs.
- **Acceptance matrix:** focused shell, fixed toolbar/X, save-safe exit, full basic
  gesture sequence, undo, existing-tool regressions, provenance guard, 390px check,
  and at least one physical iPhone Safari/PWA run; Android is additional evidence,
  not a blocking substitute.
- **Reviewer:** independent mobile/provenance assurance reviewer.
- **Evidence:** the common provenance record plus automated results,
  device/OS/browser, recording/screenshots, findings, and structured decision.

### AG-03 — Adaptive Plan assurance — 6 agent hours

- **Dependencies:** approved WP-08 commit and AG-01 integrated SHA.
- **Integrated artifact:** one commit SHA containing WP-08 on the exact AG-01
  baseline.
- **Acceptance matrix:** staged exclusion, explicit eligibility, actual plan
  consumption, visible consequence, dependency exclusion, reversal, and
  deterministic recalculation.
- **Reviewer:** independent planning assurance reviewer.
- **Evidence:** the common provenance record plus transition fixtures, visible
  output, findings, and structured decision.

### AG-04 — Universal Search and portfolio integration assurance — 10 agent hours

- **Dependencies:** approved WP-09 and WP-10 commits plus the exact approved
  AG-01, AG-02, and AG-03 integrated SHAs.
- **Integrated artifact:** the final portfolio commit SHA incorporating the exact
  approved AG-01, AG-02, and AG-03 commits in declared parent order plus WP-09 and
  WP-10, with transferred paths proven by the common provenance contract. This is
  the sole graph-level artifact eligible for controlled product merge.
- **Acceptance matrix:** six-type completeness, deterministic queries, explicit
  latency thresholds, source/provenance labels, six-type navigation, focus restore,
  stale/invalid handling, local/account parity, mobile layout, focused Canvas mode
  exposing search only after exit, plus focused smoke coverage of every AG-01–AG-03
  observable completion condition.
- **Reviewer:** independent search/integration assurance reviewer.
- **Evidence:** the common provenance record plus query/navigation matrices,
  timing environment/results, cross-feature smoke results, findings, and
  structured decision.

## Merge and concurrency order

The concurrency contract is exact; eligibility still depends on each listed
dependency being approved.

| Package | Allowed concurrent package IDs | Must not overlap | Necessary order |
| --- | --- | --- | --- |
| WP-11 | none | every feature package | first |
| WP-01 | WP-05 | WP-02, WP-03, WP-04 | after WP-11 |
| WP-02 | WP-05, WP-06, WP-07 | WP-03, WP-04 | after WP-01 |
| WP-03 | WP-05, WP-06, WP-07 | WP-02, WP-04 | schema baseline after WP-02 |
| WP-04 | WP-05, WP-06, WP-07 | WP-02, WP-03 | schema baseline after WP-03 |
| WP-05 | WP-01, WP-02, WP-03, WP-04 | WP-06, WP-07 | after WP-11 |
| WP-06 | WP-02, WP-03, WP-04 | WP-05, WP-07 | after WP-05 |
| WP-07 | WP-02, WP-03, WP-04 | WP-05, WP-06 | after WP-06 |
| WP-08 | WP-09, WP-10 | none beyond declared paths | after AG-01 |
| WP-09 | WP-08, WP-05, WP-06, WP-07 | WP-10 | after AG-01 |
| WP-10 | WP-08 | WP-09 | after WP-09 and destination contracts |

Only these integration sequences are required:

1. WP-11 establishes the composition boundary.
2. WP-01 establishes the continuation boundary; WP-02 → WP-03 → WP-04 then
   serialize shared schema/migration files. Their new-file work may overlap only
   as permitted above.
3. An integration merge with no authored product changes creates the AG-01 SHA.
4. WP-05 → WP-06 → WP-07 serialize Canvas work, followed by AG-02.
5. WP-08 and WP-09 may proceed after AG-01; WP-10 follows WP-09. AG-03 follows
   WP-08.
6. AG-04 assembles and validates the exact AG-01, AG-02, and AG-03 artifacts with
   WP-09 and WP-10 as the final combined portfolio SHA.

No other sequencing is implied. Canvas implementation can overlap Review work,
and Search indexing need not wait for Adaptive Plan implementation. Any required
code change during integration is a remediation package, never gate-authored glue.

## Agent-hour rollup

| Parent assurance | Implementation packages | Implementation hours | Paired-review hours | Assurance hours | Total |
| --- | --- | ---: | ---: | ---: | ---: |
| Shared composition baseline | WP-11 | 10 | 3 | 0 | 13 |
| AG-01 Review/time flows | WP-01–WP-04 | 66 | 16 | 10 | 92 |
| AG-02 Mobile Canvas | WP-05–WP-07 | 40 | 10 | 8 | 58 |
| AG-03 Adaptive Plan | WP-08 | 14 | 3 | 6 | 23 |
| AG-04 Search/final integration | WP-09–WP-10 | 26 | 6 | 10 | 42 |
| **Portfolio** | **11 implementation packages** | **156** | **38** | **34** | **228** |

These are planning estimates. Factory records actual implementation-active,
review-active, assurance-active, and blocked hours by package/attempt. Unknown
native-provider time remains unknown and is never reconstructed from estimates.
