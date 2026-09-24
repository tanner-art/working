# Product-owner approvals still required

These decisions do not block the registry foundation, importer, lane skeletons, or shadow-mode implementation. They must be resolved before the named boundary is enabled.

## Before registry cutover

- Approve the exact moment when the reconciled registry replaces GitHub labels/local queue files as the dispatch source of truth.
- Decide whether preserved historical worktrees appear in the default Queue view or only in an expandable preservation/archive section.
- Approve a retention policy for detailed task events, attempt logs, and usage observations. Until then, retain them indefinitely and perform no deletion.

## Before authenticated dashboard editing

- Decide whether the initial dashboard has one owner account or supports multiple factory administrators.
- Approve which roles may create, reprioritize, pause, reassign, dependency-lock, and unblock work.

## Before controlled restart

- Approve the initial worker capability configuration after it is presented as data. Agent A, Agent B, and Claude names will not be embedded as permanent lane semantics.
- Approve any change to the existing human rule that agents do not merge `main`. The migration assumes that rule remains.

## Before capacity enforcement

- Identify which provider/account usage window constitutes Orchestra capacity when the coordinating session and implementation workers share or change accounts.
- Decide whether the 20% reserve applies independently to each relevant usage window or to the most constrained current window. Until approved, the stricter interpretation wins.
- Map each real Orchestra provider/account usage window to the normalized
  `capacity_scope` identifiers supplied to `DispatchSnapshot`. Shadow mode
  requires every declared scope and evaluates each independently until this is
  approved.
- Approve the reporting precision for reserve thresholds. The implementation default will compare unrounded values and round only dashboard display values.
- Define a provider-neutral low-cost work-package classification before `SLOW`
  capacity can receive work. Until then, shadow dispatch accepts only fresh
  normalized `GREEN` capacity; it does not assume every package can use a
  fallback model safely.
- Approve or delegate the live-policy freshness windows. Shadow defaults are a
  180-second heartbeat window, 900-second usage window, and 900-second sweep
  interval with 60 seconds of scheduling tolerance.
- Ratify the provider-neutral scope names `short_window`, `weekly_window`, and
  optional `billing_budget`, then approve the explicit mapping from each real
  usage source to one scope. The current legacy feed retains only its most
  constrained window, so missing windows remain constrained.
- Ratify the package capacity classes `FULL_CAPABILITY_REQUIRED` (default) and
  `ECONOMY_ELIGIBLE` (explicit). Until then, every package requires fresh
  `GREEN` capacity and `SLOW` remains ineligible.
- Approve the proposed 60-second legacy-observation alignment tolerance in
  addition to the heartbeat, usage, and sweep tolerances above.

## Current technical defaults that do not require product approval

- SQLite/WAL is temporary and accessed only through the registry contract.
- Three active parent packages is an authoritative central limit.
- Unknown or stale usage is constrained.
- Orchestra retains at least 20% capacity.
- Implementer is not the sole reviewer.
- Preservation data is immutable and no destructive cleanup is allowed.
