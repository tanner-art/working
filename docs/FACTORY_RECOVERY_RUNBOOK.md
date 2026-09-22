# Factory Recovery Runbook

This runbook covers recovery of the local Threadline runner only. The current
runner is serial: finish, validate, and preserve one assigned issue before
starting another.

## 1. Detect a stale heartbeat

Treat a run as stale when its heartbeat has stopped advancing beyond the
runner's configured interval plus a reasonable grace period, or when the
runner process is absent while the issue remains assigned/in progress. Record
the last heartbeat, process state, issue number, agent, and worktree before
intervening. Do not assume a timeout means the work is lost.

## 2. Preserve and inspect before retrying

Inspect the issue record and its exact task, path allowlist, labels, and
comments. Inspect the assigned worktree for uncommitted changes, the branch
status, and any validation output. Inspect existing branches and pull requests
for the issue before dispatching anything again. Preserve all evidence; do not
reset, clean, delete, rebase, or discard a worktree during recovery.

## 3. macOS path failure

The verified macOS failure is that the runner cannot reliably access the
Documents-based working/state paths. The supported recovery is relocation of
runner working state and worktrees to the corresponding
`~/Library/Application Support/ThreadlineFactory/` location, with permissions
verified there. This is an infrastructure relocation, not a product change.

## 4. Authentication, TLS, and manual fallback

Check the runner's credential presence, ownership, permissions, expiry, host,
clock, proxy, and CA/TLS diagnostics. Repair or re-authenticate through the
normal approved flow. Never disable certificate verification, accept an
unknown CA, print credentials, or reset runner state to bypass an error.

If automation remains unavailable, use the documented manual CLI flow: inspect
the issue, create or enter the preserved worktree, make only the assigned
change, run the required checks, and leave the result for human review. Manual
execution must not push, open a PR, merge, or broaden the task.

## 5. Retry and review gates

Relabel an issue only when its recorded state is stale or incorrect and the
preserved issue/worktree/PR inspection proves no active run owns it. Retry only
after the root cause is fixed, the prior attempt is preserved, and exactly one
runner assignment is ready; do not retry merely because output is delayed.

Every completed attempt requires human review of the diff, scope, validation,
and any existing PR before merge. The implementer is not the sole reviewer;
merge remains a separate human gate.
