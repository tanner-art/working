# Q2 owner-authorized extra repair — validation receipt

This receipt applies to the cumulative Q2 source based on `75a3a20bf678a76be79c6a71dd4bb572b60b7d99`. It does not assert independent review, merge, installation, or a live Factory rehearsal. Historical review outcomes remain unchanged. No custom `PYTHONPATH` was used.

## Finding-to-test matrix

| Finding | Code/test evidence |
| --- | --- |
| WIP refusal must defer, not crash | Existing `scripts/runner/test_runner.py::test_builder_wip_refusal_defers_without_crashing_the_poll`; `BUILDER_WIP_LIMIT` remains deferrable. |
| Independent review and builder claims | Extended `scripts/runner/test_registry_control.py::test_operator_review_only_input_to_bounded_followup_claim_preserves_independence_and_exact_pr` uses a disposable real `SQLiteRegistry`, real `RunnerRegistryControl.pre_claim` and `claim_package`, the registered review input, both workers, and two real leases. |
| Review completion frees author WIP | Existing `scripts/factory_registry/test_bounded_run.py::test_builder_wip_counts_only_current_lineage_and_frees_after_real_review` records the real review outcome before the next author claim. |
| Changed run/lease/eligibility retry denial | Existing `test_reservation_does_not_retry_when_bounded_run_scope_changes` covers retry field comparison; new `test_real_registry_refuses_run_rollover_with_live_lease` proves the real Registry cannot replace a run while a lease exists. Existing changed-lease and stop tests remain. New `test_reservation_does_not_retry_after_real_capacity_loss` changes a real usage observation between baseline and retry; explicit eligibility guards remain in `reserve_attempt` and now receive the real scheduler boolean. |
| Three-plus pair dependency | Existing `scripts/factory_registry/test_bounded_run.py::test_three_registered_pairs_keep_dependency_waiting_work_unclaimable` registers three pairs and a real dependency row. |
| Ordinary validation receipts | Commands/results below. |
| Historical `VERIFY_REVIEW` must not freeze builders | `scope_dispatch_snapshot` now clears projected WIP attribution outside the active allowlist or without an in-scope pending paired review; persisted history is untouched. New `test_scoped_shadow_wip_excludes_historical_and_finished_reviews` covers projection. The real controller claim test above confirms that an old submitted parent does not block the next bounded-run parent. A read-only snapshot of the live Registry measured 10 old Agent A and 8 old Agent B submitted parents globally, versus zero attributed in a fresh run scope. |

## Commands and results

- `python3 -m unittest discover -s scripts/factory_registry` — **254 passed**. The restricted sandbox initially denied local HTTP fixture sockets; the same ordinary command passed with loopback permission. No test code was changed to mask that environment restriction.
- `python3 -m unittest discover -s scripts/runner` — **314 passed** with loopback permission. Its expected negative CLI fixtures print argument/configuration errors while the suite passes.
- `pnpm check` — **753 Vitest tests passed**, TypeScript build passed, Vite production build passed, API typecheck passed. Existing bundle-size warning remains.
- `python3 -m unittest discover -s scripts/runner -p test_registry_control.py` — **37 passed** without custom environment variables.

This is code-and-test evidence only. The author is not the sole acceptance reviewer under the repository's review rule. The Factory's live 20% Orchestra reserve also remains binding; this receipt does not authorize a Registry transition or dispatch.
