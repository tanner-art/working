# Continuous Factory session

An approved bounded session has an immutable allowlist and a distinct active
parent WIP limit. The allowlist can contain more independently reviewed pairs
than can run simultaneously; the Registry remains the authority for leases,
deadlines, capacity, paths, reviewer independence, and the kill switch.

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
