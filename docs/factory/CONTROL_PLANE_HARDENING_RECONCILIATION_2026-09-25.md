# Factory control-plane hardening reconciliation

Date: 2026-09-25

Status: authoritative pre-implementation reconciliation

Milestone: `CONTROL PLANE CANARY READY`

This document reconciles the Factory Control Plane Hardening Directive against
the current Registry, the merged control-plane implementation, and the staged
product execution graph at planning commit
`02a14969ca8af21b1a593f465947a577cccd76f7`.

It authorizes no dispatch. Product packages remain preserved, but no additional
product package should be promoted or claimed until the required pre-canary
packages below are implemented, independently reviewed, integrated, and pass
the canary-readiness gate.

## Executive decision

Do not turn the directive into one large package or dozens of state-specific
patches. Use 11 coherent control-plane packages:

- 10 packages form the pre-canary repair program.
- 1 portfolio-activation package waits until a successful bounded canary and
  its reconciliation.
- Every implementation package receives its own exact-commit independent
  review. The integrated canary-readiness assurance reviews one integrated
  commit SHA after all 10 pre-canary packages merge.

The current Registry remains the sole execution authority. GitHub, worker-local
files, runner snapshots, and dashboard projections remain collaboration or
projection surfaces only.

## Authoritative checkpoint

The Registry was read through `SQLiteRegistry.control_center_snapshot`, not by
editing or querying its database directly.

At Registry revision `1096`:

- dispatch mode is `PAUSED`;
- the kill switch is engaged;
- there are no active leases or attempts;
- the recorded reason is `90-minute operations test completed; owner review
  required`;
- `TASK-171` / WP-01 is `VERIFY_REVIEW` and its review package `TASK-172` is
  `READY`;
- `TASK-179` / WP-05 and review package `TASK-180` are both `VERIFY_REVIEW`;
- neither WP-01 nor WP-05 has review evidence or a structured review outcome in
  the Registry snapshot;
- all inspected completed attempts report `runtime_seconds = 0.0`;
- failed review attempts and changes-requested reviews have exposed real
  worktree and provenance failures; and
- legacy worker records without capabilities coexist with current worker
  records.

The product graph is preserved. Its remaining packages must stay non-runnable
during this repair program. WP-01 and WP-05 are preserved at their current
review stages; this reconciliation does not manufacture approval or completion
for either package.

Post-validation observation: after this checkpoint was recorded, an external
operator advanced the Registry to revision `1097`, mode `STOPPING`, with the
kill switch engaged and no active leases or attempts. This documentation task
did not mutate the Registry or interfere with that fail-closed reconciliation.

## Existing coverage and disposition

| Directive area | Existing coverage | Disposition |
| --- | --- | --- |
| Registry authority and lifecycle | Schema v4, revisioned snapshots, transactional leases, attempt ownership, append-only events, controlled mode changes | Modify. Centralize the remaining transition predicates and remove duplicated lifecycle assumptions from runners and operators. |
| Review separation | Append-only `review_outcomes`, implementer/reviewer separation, attempt-bound approval evidence, overlap rejection | Modify. Bind review input to the exact implementation/base commits and contract; add explicit failed/blocked handling and structured-verdict enforcement. |
| Review readiness | Dependency-aware scheduler special case for review parents at `VERIFY_REVIEW` | Modify. A review can currently be registered `READY` before all review inputs exist, and readiness is still partly projected through GitHub/runner behavior. |
| Queue contract validation | Queue body digest is pinned at registration and rechecked before claim | Modify. Validate referenced planning commits, readable contract content, base/target refs, and complete handoff before `READY`. |
| Feature/package consistency | Feature state and package state both exist; scheduler consumes both | Modify. Eliminate apparently `READY` children that an implicit feature state makes undispatchable. |
| Controlled stop and recovery | Kill-first `STOPPING`, lease reconciliation, worker disappearance handling, fail-closed `PAUSED` completion | Modify. Add a persisted run deadline, supervised stopper, independent watchdog, and terminal deadline event sequence. |
| Retry safety | Registry revision CAS, uniqueness constraints, transactional claim, append-only attempts and review decisions | Modify. Add stable operation identity and explicit replay behavior for every listed mutation. |
| Telemetry | Provider-neutral usage observations and capacity policy | Modify. The supported synchronization path is PAUSED-only even though LIVE eligibility requires fresh data. |
| Claims and assignment | Registry eligibility and atomic lease acquisition | Modify. Narrowly retry ordinary revision conflicts, and make Registry assignment the only assignment authority before GitHub projection. |
| Dashboard | Registry-backed Control Center API/projection exists | Modify. The local runner dashboard still depends on stale side-effect files on main. The unmerged `codex/dashboard-registry-refresh` work (`a86d13e`, `4df8725`, `f752bfa`) is reusable input, not an authority and not safe to merge wholesale with its product-graph ancestry. |
| Runtime accounting | Runtime fields exist on packages and attempts | Modify. Close operations do not persist calculated durations; live records remain zero. |
| Recovery testing | Unit coverage exists for stop ordering, lease expiry, disappeared workers, restart gates, review separation, and stale revisions | Modify. Add the directive's integrated crash/replay matrix and deterministic expected post-recovery states. |
| Legacy records | Preservation imports retain history and unclassified packages usually lack dispatch capabilities | Modify. Add explicit classification so historical records cannot accidentally become executable. |
| Portfolio activation | Single canary registration and follow-up review registration exist | New, after the canary. Add graph-wide validation and atomic/reconcilable activation only after the control plane proves itself. |

## Package graph

```text
CP-01 Registry state machine and replay safety
  ├─ CP-02 Review integrity and provenance
  │    └─ CP-03 Readiness and execution-contract validation
  ├─ CP-04 Supervised deadline safety
  ├─ CP-05 LIVE telemetry
  │    └─ CP-06 Claim and assignment concurrency
  ├─ CP-08 Runtime accounting and audit ledger
  └─ CP-10 Legacy Registry classification

CP-03 + CP-04 + CP-05 + CP-06 + CP-08
  └─ CP-07 Authoritative dashboard observability

CP-01 through CP-08 + CP-10
  └─ CP-09 Deterministic recovery and canary-readiness assurance
       └─ bounded unattended canary
            └─ canary reconciliation
                 └─ CP-11 Portfolio graph activation
```

CP-09 is not a dumping ground for omitted implementation. A failing scenario
returns to the owning package; the recovery package owns the integrated
failure-injection harness and the final exact-SHA assurance only.

## Parent package contracts

### CP-01 — Registry state machine and replay-safe mutations

**Goal:** make the Registry the single executable lifecycle authority and make
control mutations safe to retry.

**Modify:** Registry models, schema/adapter, repository contract, operator
transitions, runner Registry adapter, and transition tests.

**Acceptance criteria:**

- One central transition policy rejects unresolved dependencies, claims without
  eligible ownership, review without a successful implementation and exact
  implementation SHA, approval without a structured verdict, completion
  without required assurance, and all ownership/status contradictions.
- Existing status names are retained unless a new persisted state is needed for
  correctness; attempt and review outcomes carry detail instead of UI-only
  states.
- Claim, assignment, attempt start/finish, evidence attachment, review record,
  lease release, pause, deadline stop, and reconciliation define deterministic
  first-call and replay outcomes.
- Stable operation or transaction IDs plus uniqueness/CAS guarantees prevent a
  retry from producing duplicate semantic effects.
- Every accepted or rejected state-changing operation is reconstructable from
  authoritative records and events.
- Contract tests run against the Registry interface, not SQLite-only behavior.

**Depends on:** none.

**Canary required:** yes.

### CP-02 — Review integrity and provenance

**Goal:** ensure a reviewer can inspect, and can only approve, the exact
implementation state named by the review assignment.

**Modify:** review assignment/worktree creation, runner handoff, review models,
structured outcome recording, evidence validation, and review tests.

**Acceptance criteria:**

- Review input separately records target package, implementation attempt,
  implementation commit, base commit, PR, contract hash/content, validation
  evidence, reviewer, and review attempt.
- The review workspace faithfully contains the exact implementation commit and
  required contract without requiring unavailable external worktrees or shell
  reconstruction.
- Reviewer output uses a validated schema with `APPROVED` or
  `CHANGES_REQUESTED`; blocked, missing, provider-failed, and unparseable
  outcomes are explicit non-approval terminal attempt outcomes.
- Review completion depends on the structured Registry outcome, not provider
  exit, a file, an evidence row, or a reviewer commit.
- An adversarial test proves approval cannot be recorded for the wrong commit,
  missing contract, self-review, overlapping target mutation, blocked reviewer,
  parser failure, or evidence from another attempt.

**Depends on:** CP-01.

**Canary required:** yes.

### CP-03 — Readiness and execution-contract validation

**Goal:** make `READY` mean the assigned work is actually executable and make
review readiness a derived Registry fact.

**Modify:** package registration/promotion, dependency evaluation, planning
reference resolver, scheduler eligibility, feature/package policy, and GitHub
readiness projection.

**Acceptance criteria:**

- Before implementation `READY`, every planning commit, readable contract,
  acceptance criterion, required base/target ref, and critical content hash is
  validated and included in the worker handoff.
- Before review eligibility, the parent is `VERIFY_REVIEW`, its successful
  attempt and exact implementation SHA exist, all review inputs are present,
  reviewer eligibility is fresh, and no invariant is blocked.
- Loss or invalidation of a prerequisite removes claim eligibility without
  erasing history.
- Package promotion atomically validates/promotes the containing feature
  (Model A); no `READY` child is hidden behind an implicit feature gate.
- GitHub labels are updated only after the Registry commit and never create
  readiness.
- Dashboard/scheduler rejection data names the exact missing contract or gate.

**Depends on:** CP-01 and CP-02.

**Canary required:** yes.

### CP-04 — Supervised deadline safety

**Goal:** enforce an authoritative run deadline even if the primary timer dies.

**Modify:** Registry run-control state, operator controls, runtime supervisor,
service installation/configuration, and safety tests.

**Acceptance criteria:**

- Run ID, deadline, stopper heartbeat/state, watchdog heartbeat/state, and the
  kill-switch state are persisted authoritatively.
- The primary stopper remains supervised and observable and initiates a
  kill-first stop at the persisted deadline.
- An independently supervised watchdog enforces the same deadline if the
  primary disappears; the two do not share one fragile process lifecycle.
- Unknown/unrecoverable timer health prevents or stops LIVE operation.
- Deadline handling records stop initiated, worker reconciliation, ownership
  resolution, PAUSED transition, and final run state.
- Deadline during implementation or review ends deterministically without
  hidden live processes or released-but-running ownership.

**Depends on:** CP-01.

**Canary required:** yes.

### CP-05 — LIVE-safe telemetry

**Goal:** refresh authoritative worker/account capacity during LIVE without
changing execution ownership.

**Modify:** telemetry ingestion/operator surface, worker/account binding,
capacity evaluation, heartbeat failure reporting, and tests.

**Acceptance criteria:**

- Validated telemetry can update one worker/account while LIVE without changing
  package, lease, attempt, or unrelated worker state.
- Agent B Orchestra and its Agent B implementation child share one account
  capacity pool while preserving the Orchestra reserve.
- One unavailable worker produces an explicit per-worker failure and does not
  discard successful updates for others.
- Reviewer and Orchestra telemetry have supported refresh paths.
- Stale Orchestra telemetry is an explicit operational error, never an empty
  valid schedule.
- Active leases survive telemetry refresh unchanged.

**Depends on:** CP-01.

**Canary required:** yes.

### CP-06 — Claim and assignment concurrency

**Goal:** allow valid parallel claims without provider re-execution or split
assignment authority.

**Modify:** scheduler/claim transaction, runner claim retry, assignment
projection, GitHub label update order, and concurrency tests.

**Acceptance criteria:**

- Registry assignment commits before GitHub or UI assignment projection.
- A narrow retry distinguishes ordinary revision conflict from eligibility,
  ownership, capacity, and stale-worker failures.
- Two workers concurrently claiming two independent eligible packages both
  succeed exactly once.
- Two workers competing for one package produce one owner and one explicit
  rejection.
- Retry never launches a provider twice or creates duplicate attempts, leases,
  or assignment projections.

**Depends on:** CP-01, CP-03, and CP-05.

**Canary required:** yes.

### CP-07 — Authoritative dashboard observability

**Goal:** make local and hosted dashboards honest projections of the current
Registry, including degraded operation and run safety.

**Modify:** Control Center projection/API, local dashboard backend/UI, hosted
transport, timeout/error state, and browser verification.

**Acceptance criteria:**

- The dashboard reads an API/projection generated directly from one Registry
  revision; heartbeat/queue side-effect files are not execution authority.
- It shows working now, completed this run, waiting for review, blocked with the
  exact invariant, eligible next, worker capacity/freshness, run deadline,
  stopper/watchdog health, kill switch, Registry revision, Factory mode, and
  last authoritative update.
- Fetch failure, timeout, stale data, idle, blocked, and active states are
  visually distinct.
- Local refresh works while PAUSED and LIVE.
- The actual Vercel-hosted dashboard is verified for PAUSED empty, LIVE active,
  blocked, review waiting, reload, stale telemetry, timer state, and revision.
- The useful dashboard commits `a86d13e`, `4df8725`, and `f752bfa` are extracted
  or rebased onto the current control-plane branch; their unrelated product
  graph ancestry is not merged as an activation shortcut.

**Depends on:** CP-03, CP-04, CP-05, CP-06, and CP-08.

**Canary required:** yes.

### CP-08 — Runtime accounting and audit ledger

**Goal:** preserve truthful run timing and enough durable provenance to
reconstruct every unattended run.

**Modify:** attempt close/recovery, run records/events, Control Center
projection, and accounting tests.

**Acceptance criteria:**

- Attempt close atomically persists a calculated nonnegative duration from
  authoritative timestamps.
- Provider execution, queue wait, blocked, review, and orchestration time are
  distinguished where timestamps support them.
- Unsupported historical precision is marked unavailable, not reconstructed or
  left as a misleading measured zero.
- A run record answers eligibility at start, claim/worker/revision, commits and
  validation, exact review target and verdict, remediation, merge/failure,
  blockers, stop reason, final mode, and unresolved ownership.
- Review provenance and critical run history remain append-only or equivalently
  tamper-evident through reconciliation.

**Depends on:** CP-01.

**Canary required:** yes.

### CP-09 — Deterministic recovery and canary-readiness assurance

**Goal:** prove the integrated control plane fails closed under the directive's
failure matrix and approve one integrated artifact.

**Modify:** failure-injection/integration harness, recovery assertions, canary
preflight, and assurance report. Production fixes revealed here return to the
owning package.

**Acceptance criteria:**

- All 15 required scenarios have an asserted authoritative post-recovery state:
  worker death after claim; completion before recorder death; reviewer death;
  unparseable verdict; missing contract; claim revision conflict; dashboard
  backend loss; stale LIVE telemetry; primary stopper death; primary plus
  dashboard loss with watchdog alive; duplicate delivery; restart with active
  lease; PAUSE during work; deadline during implementation; and deadline during
  review.
- Tests prove no duplicate provider execution, false approval, contradictory
  ownership, hidden active work, or indefinite LIVE mode.
- Independent adversarial review attacks every exit criterion, not only test
  coverage.
- Final assurance names one integrated commit SHA, its merged package set,
  validation matrix, exact review decision, and unresolved findings.
- The gate passes only with no unresolved critical finding, PAUSED mode, and no
  dangling ownership.

**Depends on:** CP-01 through CP-08 and CP-10.

**Canary required:** yes; this is the final pre-canary gate.

### CP-10 — Legacy Registry classification

**Goal:** preserve history while making non-executable historical records
impossible to schedule accidentally.

**Modify:** preservation import/classification, scheduler eligibility,
dashboard labels, and migration tests.

**Acceptance criteria:**

- Every legacy entry is classified as executable, historical snapshot,
  superseded, cancelled, or needing re-registration.
- Missing lane, capabilities, acceptance criteria, or execution contract can
  never become runnable through a generic status promotion.
- Classification retains original evidence and does not rewrite review history.
- Current and legacy worker identities are visibly distinct and stale legacy
  workers cannot receive leases.

**Depends on:** CP-01.

**Canary required:** yes, because unsafe legacy eligibility can contaminate a
bounded run.

### CP-11 — Portfolio execution-graph activation

**Goal:** activate a validated multi-package graph without manual queue surgery.

**Modify/new:** graph validator, atomic/reconcilable activation operation,
activation evidence, and graph tests.

**Acceptance criteria:**

- One operation validates packages, dependencies, reviews, planning references,
  path ownership, worker capability requirements, and graph cycles before any
  root becomes runnable.
- Registration/reconciliation is atomic where possible and safely resumable
  otherwise under one activation ID.
- Only dependency-satisfied roots become ready; successors and reviews remain
  on deck until their authoritative prerequisites hold.
- One append-only activation record identifies the graph, planning commit, and
  resulting Registry revision.
- Multiple independent implementation fronts can activate without bypassing
  CP-06 assignment and concurrency controls.

**Depends on:** a successful bounded canary and its reconciliation.

**Canary required:** no; must wait until afterward.

## Merge hotspots and ownership

These files are contention surfaces, not ordinary shared files:

| Surface | Expected primary writer | Concurrent changes allowed |
| --- | --- | --- |
| `scripts/factory_registry/sqlite_registry.py` | CP-01, then CP-02/03/04/05/06/08/10 in merge order | No overlapping integration. Each package rebases after the preceding Registry-core merge. |
| `scripts/factory_registry/schema.sql` | CP-01; CP-04/08 only for approved additive records | No concurrent schema writers. |
| `scripts/factory_registry/models.py` and `repository.py` | CP-01 contract owner | Later packages extend only after CP-01 contract review. |
| `scripts/factory_registry/operator.py` and `operator_cli.py` | Package owning the operation being added | One writer per integration window. |
| `scripts/factory_registry/shadow_dispatch.py` | CP-03, then CP-05/06 | Serialize eligibility, telemetry, and retry changes. |
| `scripts/runner/registry_control.py` and `runner.py` | CP-02, then CP-06/08 | Serialize review handoff, claim retry, and accounting changes. |
| `scripts/runner/install_launchd.py` | CP-04 | Exclusive writer during deadline-safety integration. |
| `scripts/factory_registry/control_center_projection.py` | CP-07 after stable upstream contracts | CP-07 owns projection integration. |
| `scripts/runner/factory_dashboard.py` and `.html` | CP-07 | Exclusive dashboard writer; extract the three existing dashboard commits here. |
| Mirrored Registry/runner tests | Same package as production owner | Test edits follow the production ownership boundary. |

## Parallelism and serialization

Safe development parallelism is intentionally limited:

- CP-01 serializes first.
- After CP-01, CP-02, CP-04, CP-05, CP-08, and CP-10 may be developed in
  isolated worktrees, but their Registry-core integrations merge one at a time
  in that order unless exact path ownership proves otherwise.
- CP-07 can extract and test its UI-only work while core packages progress, but
  its API/projection integration waits for CP-03 through CP-06 and CP-08.
- CP-06 waits for CP-03 and CP-05.
- CP-09 waits for every pre-canary implementation package.
- Each independent review can run after its exact implementation commit is
  frozen; review does not overlap mutation of the reviewed target.

Maximum useful implementation concurrency is two fronts, and only when their
declared path sets do not overlap. Increasing worker count before these
boundaries are stable would increase merge and provenance risk without useful
throughput.

## Canary gate and deferred work

Required before the next unattended canary:

- CP-01 through CP-10, excluding only CP-11;
- exact-commit independent review for each package;
- CP-09 integrated assurance on one commit SHA;
- a real hosted dashboard with tested timeout/degraded states;
- healthy primary stopper and independent watchdog;
- fresh LIVE telemetry for Orchestra, implementation workers, and reviewer;
- no active product promotion beyond the deliberately bounded canary graph;
- `PAUSED` with no unresolved ownership immediately before activation.

May safely wait until after the canary:

- CP-11 portfolio graph activation;
- historical runtime backfill where precision cannot be proven;
- dashboard cosmetics that do not affect truth, error distinction, or safety;
- broader throughput tuning and more than two implementation fronts;
- additional product execution from the preserved graph.

## Items that do not fully click yet

These are explicit planning issues, not permission to improvise:

1. The directive says WP-01 and WP-05 were implemented and committed. The
   Registry confirms successful implementation attempts and `VERIFY_REVIEW`,
   but it contains no evidence or structured review outcome for either package.
   Their exact implementation commit and PR must be recovered and bound before
   review; they must not be called complete from the current Registry state.
2. The conceptual lifecycle names `CLAIMED`, `IMPLEMENTING`, `APPROVED`, and
   `COMPLETE`, while the persisted model uses `ACTIVE`, `VERIFY_REVIEW`, and
   `DONE` plus attempt/review records. Adding cosmetic states would create more
   ambiguity. CP-01 should define one semantic transition table over the
   current model and add persisted states only when an invariant cannot be
   represented otherwise.
3. The required hosted dashboard cannot securely read a laptop-local SQLite
   Registry directly. CP-07 needs one explicit outbound, authenticated,
   revisioned projection transport. The current code does not establish which
   durable Vercel-accessible transport is authoritative. That architecture
   choice must be recorded before CP-07 becomes `READY`; direct public exposure
   of the local Registry is not acceptable.
4. The Registry allows only `APPROVED` and `CHANGES_REQUESTED` review decisions,
   which is correct for substantive verdicts, but provider/parser/access
   failures need a separate attempt-level failed or blocked outcome. They must
   not be encoded as a reviewer decision and must never complete review.
5. Current task documentation still describes the installed runner as the live
   authority. The observed Registry-driven operations run has moved beyond that
   historical wording. The repair program should update operational docs only
   when the corresponding authority change is implemented and reviewed, not as
   a planning assertion.

## Activation rule

No package in this document becomes `READY` merely because this reconciliation
is committed. Registration and activation require a separate owner-authorized
operation after exact path sets, reviewers, planning contracts, and independent
review packages are prepared. Until then the Factory remains `PAUSED` and the
kill switch remains engaged.
