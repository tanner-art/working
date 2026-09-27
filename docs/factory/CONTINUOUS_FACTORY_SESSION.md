# Continuous Factory Session

The bounded-run allowlist is an approved backlog, while `parent_limit` remains
the simultaneous-parent ceiling. `parse_bounded_pilot_spec`,
`bounded_run_worker_gate`, and `SQLiteRegistry.register_bounded_pilot` retain
registered dependency rows, so a dependency-waiting package is in scope but is
not eligible until its dependency has the required state.

The runner calls `RunnerRegistryControl.pre_claim` and `claim_with_retry` for
every claim. Registry leases enforce one worker lease, the global active cap,
the run allowlist, exact deadline, capabilities, lane permissions, and review
author separation. An implementation completion creates immutable review input
and the review path records the structured outcome through
`SQLiteRegistry.record_review_outcome`.

For `CHANGES_REQUESTED`, `record_review_outcome` preserves the outcome and may
activate one pre-registered `ON_DECK` remediation slot. The slot must have the
same feature, source binding, contract digest, original author binding, and a
remediation index of one or two. Otherwise the target retains an explicit
`NEEDS_SCOPE` failure detail; no ID, path, contract, or deadline is created or
expanded by the queue. Slot activation is inside the outcome receipt
transaction, so replay cannot create another slot.

Codex assurance uses `review_command` to normalize the configured `codex exec`
command to `--sandbox read-only --json --output-schema FILE`. The schema file
is materialized in the immutable review packet. `parse_review_verdict` accepts
only one successful final Codex JSONL agent message and verifies the exact
commit, base, and contract digest; error, incomplete, or ambiguous streams
fail closed.
