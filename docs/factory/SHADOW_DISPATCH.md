# Shadow dispatch acceptance criteria

Shadow dispatch evaluates the new scheduler against live registry state but never starts a process, creates a worktree, changes a task state, creates a lease, updates GitHub, or consumes a worker claim.

## Required inputs

- A reconciled registry import with zero unexplained active or dirty work items.
- Fresh machine heartbeats.
- Fresh usage observations or an explicit `UNKNOWN_CONSTRAINED` state.
- Worker capabilities and approved lanes.
- Worker availability: only `IDLE` workers are candidates; `BUSY`, `OFFLINE`, `CONSTRAINED`, and `PRESERVED` workers are rejected with a recorded reason.
- Work package dependencies, priorities, `ready_at`, creation times, and acceptance criteria.
- The global three-parent-package cap and 20% Orchestra reserve settings.

## Decision record

Every sweep records:

- eligible and rejected workers;
- eligible and rejected packages;
- each rejection reason;
- dependency evaluation;
- capability and lane evaluation;
- usage freshness and capacity evaluation;
- Orchestra reserve evaluation;
- the ordered package candidates;
- the assignment that would have occurred;
- comparison with the existing runner's observable choice;
- source registry revision and decision timestamp. The revision is a monotonically increasing integer changed by every registry mutation; the decision reads one consistent revision.

The machine-readable record is defined by
[`SHADOW_DECISION_SCHEMA.json`](SHADOW_DECISION_SCHEMA.json). Its `decision_id`
is the SHA-256 of the canonical record without the ID field. Provider/model
diagnostics are intentionally absent.

## Pure scheduler boundary

`scripts.factory_registry.shadow_dispatch.decide_shadow` accepts only a
`DispatchSnapshot` and explicit policy thresholds. It cannot acquire a lease or
reach the runner, queue, GitHub, services, or worktrees. The comparison layer
accepts a caller-supplied, read-only `LegacyObservation`; it does not discover or
invoke the legacy runner itself.

Dependencies are an eligibility gate. Eligible worker-package pairs are ordered
by package priority descending, capability surplus ascending, package
`ready_at` ascending, package ID, and worker ID. Capability surplus is used only
to choose the narrowest compatible worker; missing capability rejects the pair.

The harness callable requires exactly three scheduled snapshot/legacy pairs,
a named `ACTIVE` package/`BUSY` worker assignment backed by exactly one
non-expired lease, and legacy observations for its completion and failure
projections. The harness constructs both post-outcome snapshots itself and
validates the exact package status, released worker, removed lease, incremented
revision, normalized failure evidence, and requested timestamp. An unchanged
`READY` snapshot cannot satisfy either simulation. Simulations produce copied
in-memory snapshots and cannot mutate the registry.

`write_shadow_harness_evidence` persists the five decisions, comparisons, and
simulation proof to a caller-selected JSON path using create-only semantics. It
refuses to overwrite prior evidence. This is the callable output boundary for
the eventual live three-sweep observation; it is not a registry or runner
write.

Real runner files enter through the separate read-only boundary documented in
[`LIVE_OBSERVATION.md`](LIVE_OBSERVATION.md). That adapter produces a copied
`DispatchSnapshot`; the scheduler remains unaware of filesystem paths, runner
configuration, provider identities, and storage backends.

## Conservative capacity rule

Usage observations are normalized before entering the snapshot and may carry a
provider-neutral `capacity_scope`. Workers declare their expected normalized
scopes in snapshot configuration; `default` is used when none is declared. Every
expected scope must have a fresh valid observation. For Orchestra workers, every
scope must retain at least 20% usable capacity. Any missing, stale, future,
invalid, or unknown scope blocks the full sweep.

Only scopes listed in the worker's `capacity_scopes` configuration participate
in eligibility. Unexpected historical scopes and unexpected fresh scopes are
ignored because they have no configured authority over that worker. A new real
usage window must first be normalized and added to worker configuration; a
fresh observation alone cannot silently change scheduling policy.

Only normalized `GREEN` worker capacity is eligible in this unit. Although the
legacy runner can route a `SLOW` account to a provider-specific fallback model,
the registry does not yet identify which work packages are approved low-cost
work. Shadow mode therefore refuses `SLOW` instead of treating every package as
safe fallback work.

The initial shadow policy treats a heartbeat as fresh for 180 seconds, usage as
fresh for 900 seconds, and scheduled sweeps as 900 seconds apart with 60 seconds
of tolerance. Legacy observations must also fall within 60 seconds of the
corresponding shadow decision. A stale, future, or malformed legacy timestamp
is always unresolved and cannot be waived by a difference classification. These
are explicit scheduler-policy values, not registry or provider identities, and
require review before live dispatch authority exists.

Every non-expired lease is checked as central ownership truth. Duplicate lease,
package, or worker identities and references to missing packages or workers
block the full sweep. Each non-expired lease is counted conservatively against
the parent cap when referential integrity is broken, so corrupt input cannot
create apparent capacity. A worker holding a non-expired lease is ineligible
even if its projected availability incorrectly says `IDLE`. A `READY` package
whose `ready_at` is later than the snapshot observation time is also ineligible.

Which real provider/account windows map into these normalized Orchestra scopes
remains an owner decision. Until it is resolved, the strict rule evaluates every
declared scope independently and does not infer spare capacity.

## Acceptance criteria

Shadow dispatch passes only when all of these are true:

1. It performs no launch or mutation side effect in automated tests and an observed live-state run.
2. It never selects a package with an unmet dependency.
3. It never selects a worker without every required capability and an approved lane.
4. It never selects a worker whose availability is not `IDLE`, whose role is `ORCHESTRA`, or which already holds a non-expired lease even if its availability is inconsistent.
5. Provider/model diagnostic metadata cannot change eligibility or ordering. Only normalized top-level capacity observations can affect capacity eligibility.
6. Missing or stale usage produces constrained eligibility rather than invented capacity.
7. It never proposes more than three active parent packages, including already active leases.
8. It preserves at least 20% of usable Orchestra capacity.
9. Dependencies are an eligibility gate. It orders remaining worker-package pairs by descending package priority, ascending capability surplus, ascending `ready_at`, package ID, then worker ID.
10. Identical inputs and registry revision produce byte-equivalent ordered decision records apart from the observation timestamp.
11. Concurrent shadow sweeps cannot create claims because shadow mode has no lease-write authority.
12. Every difference from the existing runner is classified as intended, legacy defect, or unresolved; any unresolved difference fails the gate.
13. There are zero unresolved provenance mismatches, duplicate source tasks, or unexplained dirty worktrees.
14. Three consecutive scheduled sweeps and one completion simulation and one failure simulation satisfy criteria 1–13 with zero unexpected assignments.
15. An independent ASSURANCE reviewer approves the decision trace and evidence.
16. Non-expired lease corruption, future-ready work, or time-misaligned legacy evidence fails closed with an explicit reason.

## Cutover gate

Passing shadow dispatch does not itself enable live claims. Controlled restart requires a separate configuration change, independent review, passing registry contract tests, a rollback procedure, and explicit Orchestra adjudication. Main merges still require the existing human approval rule.
