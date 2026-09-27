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

## Cumulative verification matrix (TASK-311 through TASK-321)

| Requirement | Regression coverage |
| --- | --- |
| Operator cardinality | `bounded_run_worker_gate` now rejects a review with zero or multiple dependency rows before target lookup. |
| Operator review input | `SQLiteRegistryTest.test_operator_review_input_requires_paused_drained_target_attempt_and_is_single_write` exercises the real `record_operator_review_input` transaction, successful attempt provenance, revision bump, and replay refusal. |
| Legacy source binding | `SQLiteRegistryTest.test_legacy_source_binding_rejects_each_gate_without_rewriting_history` exercises status, attempt-history, replacement, replay, contract identity, and dependency preservation. |
| Runner review gate | `RunnerRegistryControlTests.test_review_preclaim_excludes_the_actual_implementer` and `test_review_preclaim_fails_closed_when_its_bound_input_is_missing` cover review-only pre-claim rejection; `ReviewValidationTests.test_pending_failed_or_wrong_head_are_not_review_ready` retains exact-head and green-CI checks. |
| Immutable operator packet | The five methods enumerated in `LEGACY_OPERATOR_PROOF.md` cover normal readiness, target-scoped review preflight, every listed provenance/target failure, dependency cardinality, stale capacity, and CLI packet tampering. The CLI fixture uses real `0700` registry/state/worktree and `0600` database/WAL/SHM/config modes before both its tampered and restored-packet paths. |
| Integrated runner path | `RunnerRegistryControlTests.test_operator_review_only_input_to_bounded_followup_claim_preserves_independence_and_exact_pr`, enumerated in `LEGACY_RUNNER_PROOF.md`, covers the real disposable Registry write/pre-claim/claim path, actual-implementer exclusion, exact PR head and deadline gates, and preserved historical `CHANGES_REQUESTED`. |

No prior failed head is accepted by this reconciliation: historical
`CHANGES_REQUESTED` remains append-only. The integrated repair is subject to
independent whole-diff review.

Validation executed on 2026-09-27:

```text
umask 022 && PYTHONPYCACHEPREFIX=/private/tmp/task321-umask022-pyc python3 -m unittest -v scripts.factory_registry.test_operator.OperatorFixture.test_record_review_input_cli_publishes_valid_packet_and_refuses_tampering
# Ran 1 test: OK

umask 077 && PYTHONPYCACHEPREFIX=/private/tmp/task321-umask077-pyc python3 -m unittest -v scripts.factory_registry.test_operator.OperatorFixture.test_record_review_input_cli_publishes_valid_packet_and_refuses_tampering
# Ran 1 test: OK

umask 022 && PYTHONPYCACHEPREFIX=/private/tmp/task321-registry-discovery-pyc python3 -m unittest discover -s scripts/factory_registry -p 'test_*.py' -v
# Ran 244 tests: FAILED (29 errors)

umask 022 && PYTHONPYCACHEPREFIX=/private/tmp/task321-runner-pyc python3 -m unittest discover -s scripts/runner -p 'test_*.py' -v
# Ran 289 tests: FAILED (1 error)
```

The discovery commands are the CI discovery commands, with only a private
bytecode-cache prefix and the stated umask added. All 30 reported errors are
the sandbox's `PermissionError: [Errno 1] Operation not permitted` when tests
bind a loopback `127.0.0.1` HTTP server: 29 `ProjectionTransportTest` cases in
the Registry discovery and `HttpRouteTests.setUpClass` in the runner discovery.
The packet regression itself passes under both umasks. These local Python
checks do not run `pnpm check`; the runner owns that shared-lock validation.
