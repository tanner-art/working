# Factory registry boundary

## Role

The registry is the authoritative control plane for features, work packages, dependencies, workers, leases, attempts, evidence, usage observations, failures, and append-only events.

SQLite with WAL is the first migration adapter. It is not a permanent architecture choice. Scheduler, dashboard, telemetry, and importer code must use the `Registry` contract and must not depend on SQLite SQL, files, row types, or locking behavior. A future Postgres or Supabase adapter should implement the same behavioral contract.

GitHub issues and pull requests remain collaboration and evidence surfaces. During migration they are imported sources and projections, not an alternate scheduler.

The dormant, provider-neutral restart sequence is specified in
[`CONTROLLED_RESTART.md`](CONTROLLED_RESTART.md). It does not grant live
authority; concrete Registry and runtime adapters remain a separately reviewed
restart gate.

The SQLite migration adapter initializes dispatch control as `PAUSED` with the
kill switch engaged. Controlled callers use revision-checked mode changes and
must re-read the gate before claim and launch. Attempt runtime ownership stores
runner PID plus provider PID/process group and remains queryable after expiry,
worker disappearance, or another ownership mismatch. These tables remain
dormant until the separately approved runner/service adapter is wired.

## Entities

### Feature

The human-visible parent grouping. It has an ID, title, description, priority, and one of these states:

`ON_DECK → READY → ACTIVE → VERIFY_REVIEW → BLOCKED → DONE`

The dashboard renders `VERIFY_REVIEW` as **VERIFY / REVIEW**.

### Work package

A bounded package records:

- task ID and parent feature;
- title, category, package kind, and lane;
- required capabilities;
- priority and dependencies;
- acceptance criteria;
- state;
- current lease-derived worker ownership;
- provider/model diagnostic metadata;
- branch and pull request;
- start and heartbeat times;
- runtime and usage consumption;
- normalized failure code and human detail;
- test and review evidence.

Capacity-sensitive dispatch uses explicit package data rather than provider or
model identity: `capacity_size` is `VERY_SMALL`, `SMALL`, or `SUBSTANTIAL`, and
`capacity_risk` is `BOUNDED`, `UNCERTAIN`, or `EMERGENCY_RECOVERY`. Existing or
imported packages default conservatively to `SUBSTANTIAL` and `UNCERTAIN` until
classified.

Provider/model diagnostics never grant eligibility. A legacy import may have no lane; that makes it ineligible until the Orchestra decomposes and assigns it deliberately.

### Worker

A worker has a stable provider-neutral ID, approved capabilities and lanes, availability, last heartbeat, usage state, and optional provider/model diagnostics. Initial worker-to-lane assignments are configuration, not identity semantics. Availability is one of `IDLE`, `BUSY`, `OFFLINE`, `CONSTRAINED`, or `PRESERVED`; only an eligible `IDLE` worker can claim work.

Orchestra is represented by the `ORCHESTRA` role rather than an implementation capability. The registry refuses implementation leases for that role. Orchestra coordinates, decomposes, adjudicates, maintains backlog, and protects reserve; it is neither a routine implementer nor a sole reviewer.

### Lease

A lease is the only authoritative active ownership record. SQLite enforces:

- at most one active lease per package;
- at most one active lease per worker;
- at most three active parent-package leases globally.

Before a claim, the adapter commits any stale-lease reconciliation in its own transaction so expiry remains recorded even if the new claim is rejected. The claim then uses `BEGIN IMMEDIATE` to compare task and worker state, verify dependencies, lane approval, and capability inclusion, insert the lease, update state, and append its event atomically.

Releasing a lease and leaving `ACTIVE` also happens in one transaction. Ordinary status transitions cannot move an actively leased package; callers use the lease-release operation with the desired next state.

The shadow scheduler selects the first eligible worker-package pair by:

1. dependencies satisfied;
2. highest priority;
3. capability compatibility and smallest capability surplus;
4. oldest READY task;
5. stable package and worker IDs.

The Orchestra applies this dispatch-priority principle when it assigns package
priority and readiness: **A known production-relevant risk with a small,
bounded remediation outranks speculative platform expansion.** This changes
backlog preparation, not the deterministic scheduler ordering above.

Selection remains non-authoritative: it produces a shadow decision record and
cannot create a lease or launch work.

## Scheduler read boundary

`dispatch_snapshot(observed_at)` returns a consistent read at one monotonically increasing registry revision. It includes features; complete work-package state and `ready_at`; dependencies; workers, roles, availability, capabilities, and approved lanes; unreleased leases and expiry state; usage observations; the active-parent limit; and the Orchestra reserve percentage. Both shadow and live schedulers consume this contract. They do not query SQLite directly.

The read-only Control Center export is documented in [CONTROL_CENTER_PROJECTION.md](CONTROL_CENTER_PROJECTION.md). It reads one Registry revision through the backend-neutral `Registry.control_center_snapshot()` contract and does not create a dashboard database or grant write authority.

Capacity observations may include a provider-neutral `capacity_scope`, and
worker configuration may declare expected `capacity_scopes`. This is part of
the read contract rather than provider/model ownership. Until the owner maps
real usage windows, shadow dispatch treats every declared scope independently,
requires fresh evidence for each one, and uses `default` when none is declared.
Observations for scopes absent from that configuration—whether historical or
fresh—do not influence eligibility. Adding a real capacity window therefore
requires an explicit worker-configuration change rather than merely emitting a
new observation.

Percentage-observed workers follow the staged policy in
[CAPACITY_POLICY.md](CAPACITY_POLICY.md): below 90% normal, 90–95% caution,
95–98% checkpoint, and 98% hard stop with only the documented small exceptions.
A healthy active lease is not revoked merely because usage crosses 95%.
Workers without percentage telemetry may instead declare `provider_signal`
mode. Fresh healthy service/auth/live-invocation evidence with no explicit
limit signal is eligible; observed rate, exhaustion, throttle, or
capacity-launch failures constrain the worker without inventing a percentage.

### Attempt, evidence, review outcome, usage, and failure

Attempts retain each execution rather than overwriting retry history. Evidence records commits, checks, tests, reviews, and external artifacts. Usage observations are timestamped and preserve unknown or stale states. Failures store a normalized code and human-readable detail.

Registry schema version 4 adds append-only final review outcomes. Each outcome binds one REVIEW package to its reviewed package, Registry-verified implementer, independent reviewer, request and decision times, findings, requested changes, and typed review evidence. The implementer must match the latest successful target attempt; the reviewer must own a successful review-package attempt and must have no attempt on the target. No target attempt may overlap the review interval, including an attempt that began before the request and completed afterward or remained active. Approval evidence must be a `review` record on the review package whose metadata names that reviewer-owned attempt. The Registry rejects stale target reviews, self-review, mismatched dependencies, missing or forged attempt provenance, ineligible reviewers, and outcome replacement. Pending review assignment still comes from the review package and lease; completion status or evidence prose never implies approval.

Registry schema version 5 adds append-only control-operation receipts. A caller
may supply a stable operation ID for claim, attempt start/finish, evidence,
review outcome, lease release, package transition, and dispatch-mode changes.
An exact retry returns the original result without another event or state
mutation. Reusing that ID for a different semantic request fails closed with
`OPERATION_ID_REUSED`. The runner derives stable IDs from authoritative package,
attempt, lease, and Registry revision identities rather than process-local
randomness.

Invocation consumption is stored separately in the append-only usage ledger.
Each provider/worker/account/invocation tuple is counted once, while a linked
append-only source table retains CLI JSON, stream JSON, and transcript
observations without double-counting. The ledger records measurable token
components, duration, outcome, completion/review throughput, and explicit
provider limit signals. Factory-measured consumption does not become a
provider-reported quota percentage. See [Claude telemetry](CLAUDE_TELEMETRY.md)
for the first provider parser and privacy boundary.

Autonomous ledger records require package and attempt provenance, and the
Registry verifies that the attempt belongs to the package. Unlinked service or
authentication probes use a distinct `DIAGNOSTIC` observation class. Canonical
reads reconcile all append-only source observations deterministically, so
ingestion order cannot hide a later explicit limit signal or completion fact.

### Events

`task_events` is append-only. SQLite rejects updates and deletes. Other adapters must provide equivalent behavior.

## Backend portability requirements

- IDs are application-generated strings.
- Times are UTC ISO-8601 strings at the API boundary.
- Structured metadata is represented as JSON-compatible values.
- Atomic claim behavior is specified by outcomes, not SQLite primitives.
- Dashboard projections use registry methods or an API service, never direct database ownership.
- The active-parent limit is registry configuration and remains authoritative across adapters.
- A future adapter must pass the same contract tests before cutover.

## Failure codes

The contract reserves these normalized codes:

- `UNDERUTILIZED_SESSION`
- `WEEKLY_CAPACITY_UNUSED`
- `BACKLOG_STARVATION`
- `HEARTBEAT_MISSED`
- `RATE_LIMIT`
- `CONTEXT_EXHAUSTED`
- `SCOPE_DRIFT`
- `CI_FAILURE`
- `REVIEW_FAILURE`
- `DEPENDENCY_BLOCKED`
- `MERGE_CONFLICT`
- `AUTH_FAILURE`
- `TASK_TOO_LARGE`
- `ORCHESTRA_CAPACITY_RISK`

The taxonomy will receive transition rules and telemetry integration in its scheduled migration unit.
