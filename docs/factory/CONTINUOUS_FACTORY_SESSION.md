# Continuous Factory session

An approved bounded session has an immutable allowlist and a distinct active
parent WIP limit. The allowlist can contain more independently reviewed pairs
than can run simultaneously; the Registry remains the authority for leases,
deadlines, capacity, paths, reviewer independence, and the kill switch.

## Activate an approved backlog

Register every reviewed implementation/review pair before enabling the exact
approved scope. The run deadline, base reference, allowlist, and parent limit
are fixed for that activation. The allowlist is a queue, not a concurrency
budget: an eligible allowlisted parent may be claimed as another parent leaves
active work for independent review, without creating another run. A
dependency-waiting package is not eligible merely because it is allowlisted.

```json
{
  "run_id": "issue-316-backlog",
  "package_ids": ["TASK-401", "TASK-402", "TASK-403", "TASK-404", "TASK-405", "TASK-406"],
  "deadline": "2026-10-01T12:00:00Z",
  "base_ref": "main",
  "parent_limit": 3
}
```

## Requested changes, remediation, and dependencies

Do not overwrite a review result. Record an immutable `CHANGES_REQUESTED`
outcome with its exact input, implementation commit, base, contract digest,
and source binding. A same-scope remediation remains assigned to the original
author and carries that preserved lineage. If the requested work needs a new
file or contract, park it as `NEEDS_SCOPE`; the runner cannot create that
authority.

The normal retry budget is two remediation attempts per lineage. At
exhaustion, record the reason and park the package while independent eligible
backlog work may continue. An approved review is not integration acceptance:
downstream dependencies move only after the required approval and integration
evidence are both recorded.

## Capability-based cross-review

Reviewer choice uses Registry worker capabilities and approved lanes, not
provider identity. The reviewer must differ from the worker that authored the
bound implementation attempt. Claude may implement only when no eligible
review is waiting and an independent capable reviewer is available. Codex and
other configured workers review through the read-only structured adapter;
missing, malformed, unsuccessful, or mismatched structured output is not an
approval.

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
