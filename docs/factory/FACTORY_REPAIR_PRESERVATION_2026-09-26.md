# Factory repair consolidation and preservation

Owner request, 26 September 2026: implement the focused consultation repairs, reduce fragmentation, use the separate Agent A account for implementation and Claude for independent assurance. Product dispatch remains stopped during repair. This is not approval to merge main, deploy Production, delete preserved work, or relax ownership/review/secret controls.

## One active repair line

- Verified remote main: `c8977d53e4b75c1f02f90b1a829209b13082312b`.
- Active repair branch: `codex/factory-usable-20260926`.
- Local isolated checkout: `/private/tmp/threadline-factory-usable-9qKyFo`.
- Salvaged CP-02 implementation: `08126fc6d965ce40b271cba4d648c8bdab7ef5e8`, which already accumulates earlier CP-02 repairs. Earlier retry branches are evidence, not additional work to merge.
- Dashboard salvage source: dashboard-only changes in `a86d13e`, `4df8725`, and `f752bfa` after `02a1496`. Do not merge the source branch's unrelated planning ancestry.
- Installed controller remains `1532d86`; repair commits are not operationally installed merely because they pass tests or receive review.

The owner-authorized implementation session uses Agent A's existing configured account directory. A GPT-6 Sol launch was explicitly rejected as unavailable for that account; the bounded repair therefore used the existing GPT-5.6 Terra model at medium reasoning initially, then high reasoning for integration. Agent B/Orchestra inspected and corrected integration behavior and added verification; it did not substitute Agent-B child agents for the requested Agent A account. Claude review uses the existing keychain credential wrapper; credentials are never materialized in prompts or source files.

## Preservation inventory

A read-only inventory covered both the Factory repository and the owner's working repository, including their registered worktrees. It found:

| Observation | Count |
| --- | ---: |
| Registered worktree records | 131 |
| Existing paths | 123 |
| Missing paths referenced by Git metadata | 8 |
| Heads that are ancestors of verified main | 73 |
| Existing worktrees with uncommitted entries | 11 |

These categories overlap. An ancestor head does not establish that a dirty checkout has no valuable changes. A non-ancestor head is not an instruction to merge it, and a missing path is not proof that all corresponding work was lost. Nothing was deleted, pruned, reset, rebased, or rewritten.

Detailed generated inventory remains local at `/private/tmp/threadline-factory-preservation-inventory.json`; it contains path, head, branch, existence, ancestor classification, and dirty-entry counts, not source contents or credentials.

The specific obsolete 90-minute stop sleeper (shell PID 72196 and sleep child
72197) was retired after checking the exact process command and verifying
STOPPING/kill-switch-engaged state with zero leases, attempts and runtimes.
No Registry mutation or active-run control change was performed. Run-specific
deadline guards are still required before a later controlled run.

## Handling unfinished work without a costly rewrite

1. Use this single repair branch for accepted Factory changes. Keep exact commit and review evidence for each attempt.
2. Preserve superseded worktrees and retry records. Hide them beneath feature history in the default dashboard rather than treating each retry as an independent active feature.
3. Reconcile WP-01/WP-05 against fixes already present on the verified main ancestry before assigning implementation. The old Registry CHANGES_REQUESTED outcomes do not themselves establish that the original defects remain in current code.
4. Keep dirty and uncertain work in preservation status. Revisit it only when a selected feature needs it; do not spend another fleet-wide audit determining the value of every historical line now.
5. No mass branch closure or deletion. Physical cleanup is optional later, after the owner reviews this inventory and recoverability is established.

## Acceptance and authority boundary

The usable-release work should establish a real review adapter, task-local failure handling, live-safe truthful observations, bounded concurrent assignment, run-scoped deadlines, and a read-only Registry-backed feature dashboard. Core lease, capacity, provenance, independent review, and stop guarantees remain mandatory.

The broader CP plan remains historical acceptance context. This repair prioritizes a bounded integrated usability proof; it does not declare all CPs complete. Hosted transport parity, historical accounting backfill, and expanded worker fleets are deferred until useful throughput is demonstrated. Live installation, product activation, and any required migration/reconciliation must be separately evidenced. Main merges still require owner authorization.
