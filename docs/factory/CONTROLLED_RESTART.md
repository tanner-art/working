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
4. Recheck worker authentication, heartbeat, provider health/capacity, the
   three-parent limit, and the 20% Orchestra reserve through the Registry.
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

## Dormant Registry wiring

The Registry schema now creates a singleton `factory_control` row with the
fail-closed default `PAUSED` and `kill_switch_engaged=1`. The SQLite adapter
provides revision-checked mode changes, an unconditional kill-switch operation,
and read gates intended for both the pre-claim and pre-launch boundaries.

`attempt_runtime_ownership` durably maps a Registry attempt to its runner PID
and provider PID/process group. Reserving an attempt requires a live control
row, the expected Registry revision, and a matching unexpired lease. Binding a
provider process rechecks the live gate and lease. Finishing an attempt updates
the runtime record, attempt, lease, package, worker, event, and revision in one
transaction. Expired leases, missing/released leases, terminal attempts, and
offline or constrained workers remain visible through the orphan query.

`scripts/runner/registry_control.py` is the opt-in runner-facing adapter. An
absent `registry_database` returns no adapter, preserving the current legacy
GitHub runner. When explicitly wired later, its `pre_claim` and `pre_launch`
methods fail closed and its process callback records PID/PGID provenance. The
adapter is dormant: `runner.py` does not import or call it in this commit.

## Required follow-up before restart

The remaining authority-bound runner/service integration must:

1. make the runner check the Registry kill switch immediately before every
   claim and launch;
2. call the dormant attempt lifecycle methods from claim, launch, completion,
   interruption, and failure paths;
3. add a fail-closed launchd operation that unloads live runners and installs
   reviewed dry-run definitions without restoring live definitions on error;
4. preserve the current launchd backup and dry-run inspection behavior;
5. prove enable, stop, disappearance, lease expiry, rollback, and restart-after-
   crash through mock-backed launchctl tests; and
6. receive independent ASSURANCE before any live invocation.

The existing installer can promote reviewed dry-run definitions with
`--live --replace-current`, but there is no corresponding fail-closed pause
primitive and legacy runner records do not carry a Registry attempt ID. Those
gaps block a safe concrete cutover and must not be papered over by this
procedure contract.
