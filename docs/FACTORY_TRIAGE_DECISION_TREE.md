# Factory Triage Decision Tree

Use this tree for each assigned task. Record the lane, the next safe action, and the worktree that must be preserved.

```text
START
  |
  +-- Is the task waiting on explicit approval, a product decision, or user action?
  |     |
  |     +-- YES -> Mark approval-blocked; move it to the preserved back-burner.
  |     |          Keep its issue, notes, branch, and worktree intact. Do not retry
  |     |          or broaden scope. Continue any nonoverlapping factory task.
  |     |
  |     +-- NO -> Is the task currently executing?
  |                |
  |                +-- NO -> IDLE: verify assignment, dependencies, and a preserved
  |                |          worktree; start only when safe and authorized.
  |                |
  |                +-- YES -> Is it waiting on an internal dependency or transient
  |                           condition that may clear without new approval?
  |                           |
  |                           +-- YES -> BLOCKED: document the dependency and
  |                           |          owner; preserve the worktree; advance
  |                           |          unrelated, nonoverlapping work.
  |                           |
  |                           +-- NO -> Did execution produce an error or failed
  |                                      validation?
  |                                      |
  |                                      +-- YES -> FAILED: capture the failure,
  |                                      |          stop repeated retries, and
  |                                      |          retry only after a bounded,
  |                                      |          in-scope recovery. Preserve
  |                                      |          the worktree and hand off if
  |                                      |          recovery is not safe.
  |                                      |
  |                                      +-- NO -> Does it require independent
  |                                                 verification or author review?
  |                                                 |
  |                                                 +-- YES -> REVIEW: leave the
  |                                                 |          changes and evidence
  |                                                 |          available; request a
  |                                                 |          separate reviewer.
  |                                                 |
  |                                                 +-- NO -> Continue execution.
```

## Usage-limited lane

When the active account or runner reaches its usage limit, stop substantial implementation on that lane. Preserve the worktree and hand off with the exact status, remaining work, validation performed, and blocker. Use the lane only for brief coordination or triage; another available lane may continue nonoverlapping work. Never resolve a usage limit by deleting, resetting, rebasing, or discarding a worktree.

## Invariants

- Approval-blocked product work stays preserved on the back-burner until the required approval or decision exists.
- A back-burner task does not stop nonoverlapping factory work; check scope and shared-resource conflicts before proceeding.
- Preserve every worktree, including idle, blocked, failed, review, and handed-off worktrees.
- Do not silently change scope, retry indefinitely, or treat review as approval.
