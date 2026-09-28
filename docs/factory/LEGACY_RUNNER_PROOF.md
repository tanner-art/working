# Current-main Registry and runner proof

TASK-383 consolidates the complementary approved test evidence from TASK-317
(`e206d1d1459c6b90f42e94e7a2cfa98039462101`, PR #318) and TASK-319
(`564499059eb067854fadf3ee4502733e5d65e4ea`, PR #319) into the current-main
test package. Production ancestry is shared; this package adds no production
behavior and does not rewrite preserved historical state.

The following Registry and runner tests complement the operator coverage in
[`LEGACY_OPERATOR_PROOF.md`](LEGACY_OPERATOR_PROOF.md). All provider/GitHub
responses and process execution used by the integration test are faked;
Registry lifecycle, operator review-input recording, pre-claim, and lease
claiming use a disposable SQLite Registry.

| Test | Coverage |
| --- | --- |
| `RunnerRegistryControlTests.test_operator_review_only_input_to_bounded_followup_claim_preserves_independence_and_exact_pr` | Real historical implementation and preserved `CHANGES_REQUESTED` review; packet-bound operator review input; follow-up registration; target excluded from bounded runnable scope; independent reviewer pre-claim and claim; historical implementer refusal; exact green PR head; wrong-head refusal; exact bounded-run deadline refusal. |
| `SQLiteRegistryTest.test_operator_review_input_requires_paused_drained_target_attempt_and_is_single_write` | Successful operator review-input write and replay refusal. |
| `SQLiteRegistryTest.test_operator_review_input_rejects_write_gates_without_changing_evidence_or_state` | Non-`PAUSED`, active-ownership, and target/attempt mismatch refusals, each preserving review state, evidence, events, and revision. |
| `SQLiteRegistryTest.test_legacy_source_binding_rejects_active_ownership_and_changed_digest_without_mutation` | Real held lease refusal, changed contract digest refusal after bind, and preservation of source IDs, status, diagnostics, dependencies, and events. |

Focused current-main validation executed on 2026-09-28:

```text
PYTHONPYCACHEPREFIX=/private/tmp/task383-registry-pyc python3 -m unittest -v \
  scripts.factory_registry.test_registry.SQLiteRegistryTest.test_legacy_source_binding_rejects_active_ownership_and_changed_digest_without_mutation \
  scripts.factory_registry.test_registry.SQLiteRegistryTest.test_operator_review_input_requires_paused_drained_target_attempt_and_is_single_write \
  scripts.factory_registry.test_registry.SQLiteRegistryTest.test_operator_review_input_rejects_write_gates_without_changing_evidence_or_state
# Ran 3 tests: OK

cd scripts/runner && PYTHONPYCACHEPREFIX=/private/tmp/task383-runner-pyc python3 -m unittest -v \
  test_registry_control.RunnerRegistryControlTests.test_operator_review_only_input_to_bounded_followup_claim_preserves_independence_and_exact_pr
# Ran 1 test: OK
```

Historical commands run after TASK-319:

```sh
umask 022 && PYTHONPYCACHEPREFIX=/private/tmp/task321-runner-pyc python3 -m unittest discover -s scripts/runner -p 'test_*.py' -v
# Ran 289 tests: FAILED (1 loopback-bind error)
```

The one error is `HttpRouteTests.setUpClass`: this sandbox rejects binding a
loopback `127.0.0.1` HTTP server with `PermissionError: [Errno 1] Operation not
permitted`. The integrated Registry/runner path listed above completed; the
error is a platform restriction, not a review-input, independence, exact-SHA,
ownership, or deadline-gate failure.

Limitations: this is disposable local SQLite evidence only. It performs no
live Registry/service/configuration mutation, provider probe, GitHub request,
or shared `pnpm` validation; the runner retains those responsibilities.
