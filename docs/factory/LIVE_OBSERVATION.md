# Live observation boundary

## Purpose

The live observation adapter connects the installed runner's sanitized local
telemetry to the backend-neutral Factory scheduler without granting dispatch
authority. It reads:

- the runner configuration only to identify configured worker names and the
  state and usage-file locations;
- `heartbeat-<worker>.json` for worker, status, task, and timestamp;
- `usage.json` for already-sanitized percentage observations;
- `queue.json` for observable legacy queue state; and
- the immutable preservation snapshot for reconciliation.

It does not retain or emit runner commands, environment variables, credential
locations, raw provider replies, usage-account keys, or issue bodies. Raw
runner config, queue, usage, and heartbeat bytes are discarded immediately
after their whitelisted projection and source hashes are produced. It has no registry writer,
lease API, process launcher, service controller, GitHub client, queue writer, or
dashboard writer.

`capture_live_observation` reads the files into a provider-neutral observation.
`project_live_observation` applies that observation to a copied
`DispatchSnapshot`. `run_live_shadow_sweep` passes only the copied snapshot to
the pure shadow scheduler and compares the result with observable legacy state.
`write_live_sweep_evidence` can create an immutable JSON artifact outside the
Factory state directory. It validates the destination against the supplied
Factory inputs and preserved roots, then refuses to overwrite existing
evidence.

The command-line adapter accepts a serialized `DispatchSnapshot`; it does not
open SQLite or depend on a storage backend:

```bash
python3 -m scripts.factory_registry.live_observation_cli \
  --config /absolute/runner-config.json \
  --snapshot /absolute/dispatch-snapshot.json \
  --plan /absolute/observation-plan.json \
  --preservation /absolute/preservation-snapshot.json \
  --output /absolute/new-live-sweep-evidence.json
```

The output destination must not be the runner state, registry database,
canonical checkout, or a preserved worktree. The CLI enforces this boundary.
It samples the effective observation and decision timestamp after capturing
all input files. This prevents a heartbeat that advances during a slower
preservation read from being misclassified as future telemetry. The Python
callable accepts an explicit timestamp only for deterministic replay and tests;
live callers must use the post-capture clock.

## Worker projection

Worker identity is an explicit one-to-one mapping between a runner worker ID
and a registry worker ID. Provider/model names do not establish that mapping.

Runner heartbeat states project as follows:

| Runner state | Snapshot availability |
| --- | --- |
| `idle`, `polling` | `IDLE` |
| `starting`, `agent`, `validation`, `review` | `BUSY` |
| missing, malformed, failed, or unknown | `CONSTRAINED` |

A busy heartbeat contributes an observable legacy assignment only when it has
a task ID. An active heartbeat without a task is incomplete legacy evidence and
fails comparison. Because sanitized `queue.json` intentionally excludes issue
bodies and task IDs, a ready queue entry is recorded as unresolved rather than
being guessed into a work-package assignment.

## Capacity policy

- `short_window`: a provider's short rolling request/token window;
- `weekly_window`: the provider/account weekly allocation;
- `billing_budget`: an optional explicit spend budget.
- `provider_signal`: health/auth/live-invocation and actual limit signals for a
  worker without percentage telemetry.

Every worker declares the scopes it requires. One account record may carry
separate named observations for short and weekly windows; each scope is mapped
explicitly. The observer never clones one percentage into several scopes or
guesses scope from provider/model identity. A legacy flat record can supply only
one mapped scope. Missing or unmapped scopes remain constrained.

Packages carry explicit `capacity_size` (`VERY_SMALL`, `SMALL`, or
`SUBSTANTIAL`) and `capacity_risk` (`BOUNDED`, `UNCERTAIN`, or
`EMERGENCY_RECOVERY`). Percentage observations normalize at the ratified
90/95/98 thresholds. Provider-signal observations normalize actual health and
limit evidence without fabricating a provider percentage.

Recommended shadow tolerances are:

- heartbeat freshness: 180 seconds;
- usage freshness: 900 seconds;
- scheduled sweep: 900 seconds with ±60 seconds tolerance;
- legacy comparison alignment: 60 seconds.

These values are proposals. Missing, stale, future, malformed, unknown, or
unmapped telemetry remains constrained regardless of the proposal.

## Evidence and side-effect proof

Every artifact contains:

- base and projected snapshot fingerprints;
- exact hashes for stable sources before and after the sweep;
- byte hashes for heartbeats before and after the sweep;
- semantic heartbeat hashes over only worker, task, and status;
- preservation counts and source digest;
- all shadow worker, package, and worker-package evaluations;
- every rejection reason and proposed assignment;
- the observable legacy comparison; and
- a failing gate reason whenever evidence is unresolved.

The machine-readable artifact contract is
[`LIVE_SWEEP_EVIDENCE_SCHEMA.json`](LIVE_SWEEP_EVIDENCE_SCHEMA.json).

Heartbeats update every minute. A timestamp or PID-only heartbeat change is
recorded but does not fail the side-effect proof. A worker, task, or status
change is material and fails that sweep so the caller can capture a consistent
replacement. Stable config, queue, usage, and preservation sources must remain
byte-identical during one sweep.

Preservation reconciliation verifies the immutable snapshot digest, 33
worktrees, 8 dirty worktrees, 7 unmerged branches, imported task and worker
identity parity, zero unexplained records, zero active registry leases, and zero
active legacy records. Task parity considers only packages carrying the current
snapshot's explicit `preservation_import_id`; native packages created after the
import do not become false provenance mismatches. Duplicate or malformed source
task records fail closed with an explicit reconciliation failure. Dirty status is based on the preservation collector's
normalized `.strip().splitlines()` result; leading porcelain whitespace is not
treated as a distinct change.

## Current observed constraints

At reconciliation time the three parent heartbeats were idle and updating.
The queue contained no READY entries. Agent A and Agent B usage records were
stale, and Claude had no usage record. Therefore a current shadow sweep must
constrain all implementation workers. This is expected evidence, not a reason
to invent fresh capacity or enable live dispatch.

## Live authority boundary

This unit cannot claim work. Passing one or more live sweeps does not authorize
registry cutover, leases, launches, queue changes, service recovery, or
controlled restart. Three scheduled sweeps, completion/failure evidence, clean
legacy comparisons, and independent ASSURANCE review remain separate gates.
