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
python3 -m scripts.factory_registry.operator_cli bind-legacy-source \
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
  "validation_evidence": {
    "ci": {"state": "SUCCESS", "implementation_commit": "<same PR head>", "pr_url": "<same PR URL>"},
    "review_packet": {"path": "/absolute/read-only-packet", "manifest_sha256": "<sha256>", "files": {"base-to-implementation.diff": "<sha256>", "changed-files.txt": "<sha256>", "contract.json": "<sha256>", "validation-evidence.json": "<sha256>"}}
  },
  "recorded_at": "2026-09-27T12:00:00Z"
}
```

Run `record-review-input` with the standard reviewed operator context and
`--spec` pointing to that JSON. Under the Registry writer lock it requires a
drained `PAUSED` revision, verifies the manifest and every packet file hash,
the exact attempt/base/head and normalized contract file, green CI provenance,
and the exact registered review dependency. Recording input is not a verdict
or approval. The runner still fetches that
exact PR head and requires green CI before it can claim the review. It also
rejects the original implementer as reviewer.

Use an explicit one- or two-review `enable-live --bounded-run` envelope whose
`package_ids` contain only the review IDs. Its deadline is exact: claims at or
after it fail. Stop, reconcile, and return to `PAUSED` using the normal
operator sequence. Old `CHANGES_REQUESTED` outcomes remain append-only.

## TASK-313 verification matrix

| Requirement | Regression coverage |
| --- | --- |
| 1 | `SQLiteRegistryTest.test_followup_registration_restores_global_ready_active_exclusivity`; existing `OperatorFixture.test_telemetry_canary_and_worker_gate_are_revision_checked` preserves the accepted target flow. |
| 2 | `bounded_run_worker_gate` requires exact review-input and successful-attempt lookups before reviewer evaluation; runner pre-claim remains covered by `RunnerRegistryControlTests.test_review_preclaim_uses_real_sqlite_branch_when_no_review_input_exists`. |
| 3 | `SQLiteRegistryTest.test_operator_review_packet_requires_exact_hashes_contract_and_green_ci` covers packet hash/contract tamper rejection; `SQLiteRegistry.record_operator_review_input` performs that verification under `BEGIN IMMEDIATE`, while normal runner immutable publication remains covered by `RunnerRegistryControlTests.test_implementation_completion_and_review_input_are_atomic`. |
| 4 | Existing runner integration tests use fake GitHub/provider calls; no live provider or Registry is contacted. |
| 5 | `SQLiteRegistryTest.test_legacy_source_binding_is_contract_pinned_and_idempotent` covers contract mismatch, replacement rejection, idempotence, and preserved event history. |
| 6 | The reconciliation path adds no attempts or verdicts; `OPERATOR_REVIEW_INPUT_RECORDED` explicitly marks historical input rather than implementation authorship. |

Focused commands: `PYTHONPYCACHEPREFIX=/private/tmp/task313-pyc python3 -m unittest scripts.factory_registry.test_registry scripts.factory_registry.test_operator`; runner tests must run from `scripts/runner` because they intentionally import local runner modules. These commands do not run `pnpm check`; that immutable-packet validation remains the factory runner's responsibility.
