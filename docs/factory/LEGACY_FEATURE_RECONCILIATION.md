# Legacy feature reconciliation

This is a narrow preservation path for an unstarted legacy package or an
already-successful implementation awaiting an independent review. It does not
change package contracts, dependencies, attempts, old review verdicts, or
approval state. In particular, a later coordinator merge is evidence of
remediation, not a fabricated Factory implementation attempt.

## Bind a queued legacy package

While the Registry is `PAUSED`, drained, and at the expected revision, bind
the exact existing normalized queue body to its GitHub issue:

```sh
python3 scripts/factory_registry/operator_cli.py bind-legacy-source \
  --database /absolute/factory.sqlite3 --config /absolute/config.json \
  --release /absolute/release --release-commit <release-sha> \
  --preservation /absolute/preservation.json --expect-revision <revision> \
  --package TASK-173 --issue 173 --queue-contract /absolute/TASK-173.json
```

The command accepts only `ON_DECK` or `READY` packages with no attempt history.
The supplied body must hash to the package's existing
`queue_contract_sha256`; source identity and dependencies are never replaced.
Repeating the identical binding is an idempotent no-op. A different issue,
contract, status, active ownership, or any attempt history fails closed.

## Register and activate an existing review independently

Register each follow-up review (for example `TASK-212` targeting `TASK-171`,
then `TASK-213` targeting `TASK-179`) with `register-followup-review`. The
target remains prerequisite context and is not a bounded allowlist member.
Before enabling a review-only run, record its immutable input packet:

```json
{
  "id": "review-input:TASK-212:<successful-attempt-id>",
  "review_package_id": "TASK-212",
  "target_package_id": "TASK-171",
  "implementation_attempt_id": "<successful-attempt-id>",
  "implementation_commit": "<40-or-64-hex PR head>",
  "base_commit": "<40-or-64-hex base>",
  "pr_url": "https://github.com/owner/repo/pull/209",
  "contract": {"the": "exact normalized queue contract"},
  "validation_evidence": {"ci": "exact PR head is green"},
  "recorded_at": "2026-09-27T12:00:00Z"
}
```

Run `record-review-input` with the standard reviewed operator context and
`--spec` pointing to that JSON. It validates the packet hash, exact registered
review dependency, successful historical attempt identity, and full SHA shape;
recording input is not a verdict or approval. The runner still fetches that
exact PR head and requires green CI before it can claim the review. It also
rejects the original implementer as reviewer.

Use an explicit one- or two-review `enable-live --bounded-run` envelope whose
`package_ids` contain only the review IDs. Its deadline is exact: claims at or
after it fail. Stop, reconcile, and return to `PAUSED` using the normal
operator sequence. Old `CHANGES_REQUESTED` outcomes remain append-only.
