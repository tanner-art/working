# Factory Operating Model

This model applies to the current Threadline prototype and governs infrastructure work only. It does not authorize product feature work.

## Worker slots

The factory has three named slots:

- **Codex A** — `agent:codex-a`
- **Codex B** — `agent:codex-b`
- **Claude** — `agent:claude`

### Current behavior: serial runner

The current runner dispatches one assigned task at a time from an isolated worktree. It validates the task, commits, pushes, and opens a draft PR; it never merges. The unattended heartbeat/Claude runner is currently paused or unavailable, so manual dispatch is the operational fallback. Parallel dispatch is **not live**.

### Proposed behavior: parallel canary

Future parallel dispatch may run one task per available slot, but only after the operator can observe each lease, heartbeat, worktree, validation result, and review state. Parallelism is a proposal, not a current capability or claim about production behavior.

## Queue readiness

An item is ready only when all criteria are true:

1. It has one concrete task, acceptance criteria, exact allowed paths, validation commands, and a named slot.
2. Its dependencies are listed and complete, or explicitly marked unnecessary.
3. It has exactly one agent label and `runner:ready`; no credentials, hooks, settings, runner configuration, or unrelated product scope is included.
4. The worktree starts from the agreed base, and the task can be validated without another active item’s uncommitted changes.

If two items touch the same path, share generated output, or have a dependency edge, they are conflicting: serialize them behind the dependency. Otherwise they may be candidates for separate slots. A conflict is resolved by the operator, never by silently overwriting another worker’s changes.

## Review, merge, and recovery

The implementer must not be the sole reviewer. An independent reviewer checks scope, diff, acceptance criteria, and validation. A human owns the final merge gate after review; no runner or worker may merge.

If a heartbeat is stale, a worker fails, or status cannot be trusted, stop relying on automatic dispatch. Record the state, preserve the worktree/branch, and manually dispatch recovery or reassignment after checking for conflicts. Do not weaken credential or certificate safeguards.

## Capacity metric

Record daily active-agent slots: the mean number of slots doing assigned work during the day, excluding idle, blocked, review-only, and failed slots. Report a rolling nine-day average. The target is **2.5 active agents on average across nine days**; this is a capacity measure, not permission to relax review or safety gates.

## Safe canary checklist

- Confirm the canary is documentation/infrastructure only; no product feature work.
- Select two independent, low-risk tasks with disjoint paths and explicit validation.
- Verify base revision, labels, dependencies, leases, and heartbeats before dispatch.
- Observe both workers through completion; stop on stale heartbeat, failure, or unexpected path changes.
- Run `pnpm check` and diff/scope checks for each item.
- Obtain independent review, then human approval before any merge.
- Record outcomes, active-slot minutes, failures, and follow-up actions; return to serial/manual dispatch if any gate fails.
