# Capability dispatch shadow-mode work package

## Scope

Implement the first scheduler projection on top of the backend-neutral
`DispatchSnapshot`. The unit proposes assignments and compares them with a
caller-supplied observation of the legacy runner. It has no launch, lease,
registry-write, queue-write, GitHub, service, or worktree authority.

## Lane

PLATFORM: orchestration infrastructure.

## Allowed files

- `scripts/factory_registry/**`
- `docs/factory/**`

## Ordering contract

Dependencies are an eligibility gate. Remaining worker-package pairs sort by:

1. package priority descending;
2. capability surplus ascending, so the first compatible best-fit worker wins;
3. package `ready_at` ascending;
4. package ID ascending;
5. worker ID ascending.

Provider and model diagnostics are excluded from this comparison. Capability
surplus is the number of approved worker capabilities not required by the
package. Missing required capabilities reject the pair rather than contributing
to a score.

## Acceptance criteria

- The scheduler consumes only `DispatchSnapshot` plus explicit policy values.
- Dependencies, lane approval, all required capabilities, worker role,
  availability, heartbeat freshness, and normalized capacity are enforced.
- Missing, stale, future-dated, invalid, unknown, or stopped capacity fails
  closed.
- Only fresh normalized `GREEN` capacity is eligible until a provider-neutral
  low-cost package classification exists; `SLOW` does not claim arbitrary work.
- Every expected normalized Orchestra capacity scope is fresh and retains at
  least the configured 20% reserve. Any missing scope blocks proposals.
- Only explicitly configured capacity scopes affect eligibility. Unexpected
  historical or fresh scopes are ignored until worker configuration authorizes
  them.
- Only non-expired parent leases count toward the authoritative three-parent
  cap. Any expired unreconciled lease blocks the complete sweep. Duplicate or
  orphan non-expired lease identities/references fail closed and are counted
  conservatively so they cannot create apparent capacity.
- A worker with a non-expired lease cannot receive a proposal even if its
  availability is incorrectly projected as `IDLE`.
- A `READY` package with `ready_at` after the snapshot observation time is
  explicitly rejected.
- Decision JSON is deterministic for identical input and conforms to
  `SHADOW_DECISION_SCHEMA.json`.
- Worker, package, pair, and global rejection reasons remain inspectable.
- Legacy differences default to `UNRESOLVED`; an unresolved difference fails
  the comparison gate. Legacy observations must be within the configured
  timestamp tolerance; stale, future, and malformed observation times remain
  non-overridable unresolved differences.
- Three scheduled sweeps, a completion simulation, and a failure simulation can
  be run through one pure harness. The harness creates both outcomes from one
  named active assignment and validates state, lease removal, revision, time,
  and normalized failure evidence.
- The harness evidence can be written to an immutable caller-selected JSON
  artifact path; existing evidence cannot be overwritten.
- The implementation performs no registry or legacy-runner mutation.
- Provider/model diagnostic changes cannot change a decision.
- Independent ASSURANCE review is required before the PR is merge-ready.

## Exclusions

- Acquiring, renewing, expiring, or releasing a lease.
- Launching or recovering a worker.
- Updating the legacy queue, dashboard, GitHub, services, or worktrees.
- Registry cutover or live scheduler authority.
- Resolving owner decisions in `OWNER_APPROVALS.md`.
- Changing the human approval rule for merges to `main`.

## Completion evidence required

- Focused shadow scheduler tests.
- Existing registry contract tests.
- Full repository check and diff inspection.
- Three timestamped sweep decision records.
- Completion and failure simulation decision records.
- A legacy comparison for every decision with no unresolved difference.
- Independent ASSURANCE approval.
