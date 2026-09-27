# Continuous Factory session

An approved bounded run has one explicit allowlist and a separate concurrent
parent limit. The allowlist may contain more implementation/review pairs than
can run at once; it does not make a dependency-waiting package eligible.

## Activate an approved backlog

Register every reviewed pair first, then enable the exact approved scope. The
deadline and allowlist remain fixed for that activation.

```json
{
  "run_id": "issue-316-backlog",
  "package_ids": ["TASK-401", "TASK-402", "TASK-403", "TASK-404", "TASK-405", "TASK-406"],
  "deadline": "2026-10-01T12:00:00Z",
  "base_ref": "main",
  "parent_limit": 3
}
```

Here `TASK-401`, `TASK-403`, and `TASK-405` are implementation packages; their
paired reviews are the other IDs. At most three parent implementations can
hold active leases. When an implementation moves to review, another eligible
allowlisted parent can be claimed without creating another run.

## Requested changes and retry

Do not overwrite a review result. Record the immutable `CHANGES_REQUESTED`
outcome and retain its exact input, commit, base, contract digest, and source
binding. A same-scope remediation must be assigned to the original author and
must carry that preserved lineage. If it needs a new file or contract, park it
as `NEEDS_SCOPE`; do not create authority from the runner.

The normal retry budget is two remediation attempts per lineage. At exhaustion,
record the reason and park that package; independent eligible backlog work may
continue. An approved review is not integration acceptance: dependencies move
only after the required approval and integration evidence are both recorded.

## Capability-based cross-review

Reviewer choice is based on the Registry worker capabilities and approved
lanes, not provider identity. The reviewer must differ from the worker that
authored the bound implementation attempt. Claude may implement only when no
eligible review is waiting and an independent capable reviewer is available.
Codex and other configured workers review through the read-only structured
adapter; missing, malformed, unsuccessful, or mismatched structured output is
not an approval.
