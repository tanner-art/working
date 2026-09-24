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

## Acceptance criteria

Shadow dispatch passes only when all of these are true:

1. It performs no launch or mutation side effect in automated tests and an observed live-state run.
2. It never selects a package with an unmet dependency.
3. It never selects a worker without every required capability and an approved lane.
4. It never selects a worker whose availability is not `IDLE`, or whose role is `ORCHESTRA`.
5. Provider/model metadata cannot change eligibility or ordering except through a normalized, fresh capacity observation.
6. Missing or stale usage produces constrained eligibility rather than invented capacity.
7. It never proposes more than three active parent packages, including already active leases.
8. It preserves at least 20% of usable Orchestra capacity.
9. It orders eligible packages by satisfied dependencies, descending priority, capability compatibility, then ascending `ready_at`, with task ID as the deterministic final tie-breaker.
10. Identical inputs and registry revision produce byte-equivalent ordered decision records apart from the observation timestamp.
11. Concurrent shadow sweeps cannot create claims because shadow mode has no lease-write authority.
12. Every difference from the existing runner is classified as intended, legacy defect, or unresolved; any unresolved difference fails the gate.
13. There are zero unresolved provenance mismatches, duplicate source tasks, or unexplained dirty worktrees.
14. Three consecutive scheduled sweeps and one completion simulation and one failure simulation satisfy criteria 1–13 with zero unexpected assignments.
15. An independent ASSURANCE reviewer approves the decision trace and evidence.

## Cutover gate

Passing shadow dispatch does not itself enable live claims. Controlled restart requires a separate configuration change, independent review, passing registry contract tests, a rollback procedure, and explicit Orchestra adjudication. Main merges still require the existing human approval rule.
