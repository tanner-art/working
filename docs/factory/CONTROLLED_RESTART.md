# Controlled restart procedure

Status: procedure contract and test harness only. This document does not
authorize a restart, enable dispatch, modify a queue, or install a service.
The installed runner remains authoritative until the live adapter described
under **Required follow-up** is separately approved and independently reviewed.

## Safety model

The Registry owns the durable control phase, kill switch, workers, leases,
attempts, packages, and audit events. A runtime supervisor may prepare a
runner, enable or disable claims, and terminate an attempt, but it must not
invent or persist scheduling state. Each Registry mutation in the procedure
must be atomic and append its event in the same transaction.

The allowed phases are:

- `PAUSED`: kill switch engaged; no active ownership.
- `LIVE`: the bounded canary may claim work at the committed Registry revision.
- `STOPPING`: kill switch engaged while runtime and ownership are drained.
- `RECOVERY_REQUIRED`: ownership remains explicit and needs intervention.

No stop path may report `PAUSED` while a lease or active attempt remains. If a
runtime termination, lease reconciliation, or post-read fails, the procedure
keeps the kill switch engaged and reports the unresolved lease identifiers.
It never releases a lease while silently leaving an attempt running.

## Enable one bounded canary

Enable is allowed only after the product owner approves the controlled restart
and all current owner gates in `OWNER_APPROVALS.md` are satisfied.

1. Read one Registry snapshot and retain its revision.
2. Require `PAUSED`, an engaged kill switch, no lease, and no active attempt.
3. Re-run preservation reconciliation. Require a clean result exactly equal to
   the owner-reviewed evidence, including its source SHA-256. The current
   reviewed counts are 33 worktrees, 8 dirty worktrees, 7 unmerged branches,
   0 unexplained records, and 0 active stale leases; later reviewed evidence
   replaces these values rather than being silently accepted.
4. In that same time-pinned Registry snapshot, recheck explicit worker
   authentication and heartbeat fields, provider capacity eligibility, the
   current and maximum active-parent counts, and current and required
   Orchestra reserve percentages. Missing, stale, malformed, or ineligible
   values fail closed before runtime preparation.
5. Prepare the supervisor while it is still unable to claim.
6. Compare-and-swap the Registry from the retained `PAUSED` revision to
   `LIVE`, recording the reason and event atomically.
7. Enable claims pinned to the committed Registry revision and dispatch only
   the approved canary. A startup failure immediately follows the rollback
   sequence below.

## Immediate stop and kill switch

The first stop action is always an atomic Registry transition to `STOPPING`
with the kill switch engaged. The supervisor then disables every claim loop,
terminates each recorded attempt runtime, and asks the Registry to atomically:

- release the matching lease;
- make the attempt terminal;
- move unfinished work to a visible `BLOCKED` state; and
- append failure, lease-release, and package events.

The procedure performs a fresh Registry read. Only an empty ownership set and
no active attempts permit the final compare-and-swap to `PAUSED`. Any failure
leaves `STOPPING` plus explicit recovery identifiers. Operators must not
manually erase ownership to make the status look clean.

## Lease expiry

An expired lease is a controlled-stop event during this phase. Engage the kill
switch, disable claims, terminate the runtime associated with every expired
lease, and atomically make those attempts terminal before draining any other
ownership. A surviving expired lease is `RECOVERY_REQUIRED`; the Factory must
remain stopped.

## Failed-attempt recovery

Retry preparation is allowed only in `PAUSED`. The selected attempt must
already be terminal `FAILED`, have an end timestamp, and own no lease. The
Registry preserves that attempt unchanged and moves its package to `READY` in
one audited transaction. A later claim creates a new attempt; retry never
rewrites the historical attempt or reuses its ownership.

## Worker disappearance

A missing worker stops the bounded Factory globally. Engage the kill switch,
disable all claim loops, terminate every recorded active runtime, mark the
worker `OFFLINE` or `CONSTRAINED`, reconcile its lease and attempt, drain any
remaining ownership, verify the worker state, and finish in `PAUSED`. If the
worker or its process group cannot be identified, retain the ownership record
and require recovery.

## Rollback to paused

Rollback is the immediate-stop sequence with a rollback reason. It does not
restore a prior live service after a partial failure. Preservation is then
reconciled again and compared with the reviewed evidence before any later
canary is considered.

## Testable procedure boundary

`scripts/factory_registry/controlled_restart.py` is executable against injected
Registry and supervisor ports. Its tests cover enable ordering, preservation
drift, startup rollback, kill-first stop, termination failure, lease expiry,
terminal-attempt retry, worker disappearance, and explicit rollback. The test
Registry models atomic revision changes and checks that no transition can hide
active ownership.

The module has no concrete database, queue, process, service, or launchd
adapter. Importing it cannot start work. That separation is intentional for
this package because live dispatch remains paused.

## Concrete Registry wiring

The Registry schema now creates a singleton `factory_control` row with the
fail-closed default `PAUSED` and `kill_switch_engaged=1`. The SQLite adapter
provides revision-checked mode changes, an unconditional kill-switch operation,
and read gates intended for both the pre-claim and pre-launch boundaries.
Every transition to `LIVE`, including `STOPPING` to `LIVE`, rejects an
unreleased runtime-ownership row even when its attempt and lease were made
terminal by an incomplete recovery. Control APIs accept only the explicitly
supported control schema version and fail closed on missing, malformed, or
newer metadata.

`attempt_runtime_ownership` durably maps a Registry attempt to its runner PID
and provider PID/process group. Reserving an attempt requires a live control
row, the expected Registry revision, and a matching unexpired lease. Binding a
provider process rechecks the live gate and lease. Finishing an attempt updates
the runtime record, attempt, lease, package, worker, event, and revision in one
transaction. Expired leases, missing/released leases, terminal attempts, and
offline or constrained workers remain visible through the orphan query.

`scripts/runner/registry_control.py` is wired into every non-dry-run poll. A
live runner refuses to start without `registry_database`. Before its local
claim, it requires the exact package/worker pair in the Registry scheduler's
current eligible assignments and pins that revision through atomic lease
acquisition. It reserves the attempt before setup and rechecks LIVE immediately
before provider launch. A pipe-backed exec gate starts only the runner-owned
barrier process, records that stable PID/PGID in the Registry, and releases the
provider command only after the bind succeeds. A rejected bind terminates the
process group before provider code can run. The main runner thread renews the
lease and Registry heartbeats throughout setup, provider execution, validation,
push, and PR creation; expiry, revocation, or a stopped gate terminates the
current child and enters durable recovery. Success, failure, timeout, and
interruption issue at most one terminal ownership mutation.

A disappeared worker engages the global kill switch first, marks that worker
OFFLINE, terminates every recorded runtime, and reconciles bound, unbound, and
lease-only ownership. It returns to PAUSED only after a fresh ownership read is
empty. Failed termination or Registry recovery leaves STOPPING in force and
records a deterministic failure observation for the unresolved ownership.

`pause_to_dry_run` in `scripts/runner/install_launchd.py` is an injected,
non-CLI helper. It engages the Registry kill switch first, backs up and boots
out loaded services from both serial and lane modes, then reconciles every
runtime and lease-only setup/validation gap. It writes reviewed dry-run
definitions, commits PAUSED, and bootstraps them only after ownership drains.
Unresolved ownership leaves the Registry STOPPING with recovery evidence and
keeps the live definitions on disk. The helper never automatically restores or
reloads a live definition after a stop or dry-run bootstrap failure. This
package does not call the helper or touch installed services.

## Required follow-up before restart

The remaining restart work is operational: independent ASSURANCE must approve
this wiring, the reviewed configuration must name the authoritative Registry,
and an owner-approved A5 canary must exercise it. `pause_to_dry_run` remains
deliberately unavailable from the installer CLI until that review; operators
cannot invoke it accidentally through an existing service command. No service
installation, LIVE transition, queue claim, or provider invocation occurred in
this package.
