# Legacy Runner proof — TASK-319 / issue #261

The following focused tests are the authoritative evidence for this task. All
provider/GitHub responses and process execution used by the integration test
are faked; Registry lifecycle, operator review-input recording, pre-claim,
and lease claiming use a disposable SQLite Registry.

| Test | Coverage |
| --- | --- |
| `RunnerRegistryControlTests.test_operator_review_only_input_to_bounded_followup_claim_preserves_independence_and_exact_pr` | Real historical implementation and preserved `CHANGES_REQUESTED` review; packet-bound operator review input; follow-up registration; target excluded from bounded runnable scope; independent reviewer pre-claim and claim; historical implementer refusal; exact green PR head; wrong-head refusal; exact bounded-run deadline refusal. |
| `SQLiteRegistryTest.test_operator_review_input_requires_paused_drained_target_attempt_and_is_single_write` | Successful operator review-input write and replay refusal. |
| `SQLiteRegistryTest.test_operator_review_input_rejects_write_gates_without_changing_evidence_or_state` | Non-`PAUSED`, active-ownership, and target/attempt mismatch refusals, each preserving review state, evidence, events, and revision. |
| `SQLiteRegistryTest.test_legacy_source_binding_rejects_active_ownership_and_changed_digest_without_mutation` | Real held lease refusal, changed contract digest refusal after bind, and preservation of source IDs, status, diagnostics, dependencies, and events. |

Commands run after the changes:

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
