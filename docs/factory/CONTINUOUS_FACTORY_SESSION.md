# Continuous Factory session

An approved bounded session has an immutable allowlist and a distinct active
parent WIP limit. The allowlist can contain more independently reviewed pairs
than can run simultaneously; the Registry remains the authority for leases,
deadlines, capacity, paths, reviewer independence, and the kill switch.

## TASK-353 parity record

The approved TASK-353 implementation (`f36b7ced604dfe87635cf4789184d89a69894a60`)
remains present on the pinned current main: a nonempty approved backlog may
contain more pairs than its configured parent limit, while the Registry rejects
the next parent lease once that limit is occupied. Current focused coverage
exercises both three active parents at a limit of three and the original
two-active/third-refused case at a limit of two.

This is bounded-run behavior only. It does not create remediation work after a
`CHANGES_REQUESTED` verdict. In particular, `NEEDS_SCOPE`, `EXHAUSTED`,
original-author-only correction assignment, and a two-attempt remediation
budget are not live Registry or runner behavior. The rejected Q3 proposal is
retained as historical safety design in
[`Q3_CORRECTION_TRANSITION_DESIGN_2026-09-27.md`](Q3_CORRECTION_TRANSITION_DESIGN_2026-09-27.md).

Waiting-review WIP is scoped to the active bounded run's immutable allowlist:
only a parent whose paired review remains in that run can consume its author's
slot. When a run is stopped and a successor is activated, the successor gets a
new allowlist/lineage; preserved historical `VERIFY_REVIEW` records remain
visible but do not consume successor capacity. A parent still awaiting review
must be explicitly included with its review in a restarted run to count.

Each builder has a WIP limit of two parent packages. A parent awaiting its
independent review remains attributed to the worker on its latest successful
implementation attempt, so it consumes one of that builder's slots until the
review completes. This does not consume another builder's capacity or replace
the global active-parent limit.

At an idle boundary, a READY independent review is ordered before an eligible
parent. Waiting and BLOCKED packages remain in their recorded state: they are
not promoted to make a session appear runnable. Activation may retain a
dependency-waiting pair only when a capable implementer and an independent
capable reviewer are registered for that exact pair.

Between lease claim and provider launch, the runner may revalidate once after a
revision race only if dispatch is still LIVE, the run deadline remains valid,
the same lease ID and bounded-run ID/scope/deadline remain active, the package
remains ACTIVE, capacity/path eligibility remains valid, and no attempt exists.
A stop, kill switch, deadline, lease ownership change, run rollover, altered
scope, lost eligibility, or existing attempt fails closed.
