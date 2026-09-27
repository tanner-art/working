# Legacy operator bounded-review proof

TASK-317 adds the following new `OperatorFixture` methods in
`scripts/factory_registry/test_operator.py`:

- `test_bounded_run_worker_gate_keeps_normal_ready_pair_path` — normal READY
  implementation/review pair remains eligible.
- `test_bounded_review_preflight_accepts_immutable_target_scoped_followup` —
  runs `preflight(..., require_workers=True, run_package_ids=["TASK-202"])`
  against a real Registry snapshot and immutable review input, and separately
  proves the target-scoped follow-up reviewer pair.
- `test_bounded_review_gate_rejects_each_isolated_target_and_provenance_failure`
  — independently rejects a READY target, ACTIVE target, non-PARENT target,
  wrong target, missing input, recorded self-review provenance, and zero
  dependency rows.
- `test_bounded_review_gate_rejects_multiple_dependencies_and_stale_capacity`
  — independently rejects multiple dependency rows and stale worker capacity.
- `test_record_review_input_cli_publishes_valid_packet_and_refuses_tampering`
  — invokes `operator_cli.main` on a disposable Registry; it refuses a
  tampered packet without publishing evidence, then accepts the restored,
  immutable packet.

The shared fixture includes isolated preserved legacy parents, a preserved
failed review, a completed `TASK-201` target implementation, and real packet
hashes/evidence for `TASK-202`. Packet hashing is verified upstream by
`record_operator_review_input`; the bounded worker gate consumes only its
already-recorded immutable Registry evidence. The CLI test covers that
upstream boundary honestly rather than claiming the gate rehashes packets.

Validation executed on 2026-09-27:

```text
python3 -m unittest \
  scripts.factory_registry.test_operator.OperatorFixture.test_bounded_run_worker_gate_keeps_normal_ready_pair_path \
  scripts.factory_registry.test_operator.OperatorFixture.test_bounded_review_preflight_accepts_immutable_target_scoped_followup \
  scripts.factory_registry.test_operator.OperatorFixture.test_bounded_review_gate_rejects_each_isolated_target_and_provenance_failure \
  scripts.factory_registry.test_operator.OperatorFixture.test_bounded_review_gate_rejects_multiple_dependencies_and_stale_capacity \
  scripts.factory_registry.test_operator.OperatorFixture.test_record_review_input_cli_publishes_valid_packet_and_refuses_tampering
# Ran 5 tests: OK

python3 -m unittest scripts.factory_registry.test_registry
# Ran 55 tests: OK

python3 -m unittest scripts.factory_registry.test_operator
# Ran 39 tests: FAILED (one pre-existing environment-sensitive permission assertion)
```

The operator-suite failure is
`test_preservation_is_pinned_and_installed_owner_only`: its first expected
`0600` refusal was not raised in this sandbox. The same single-test rerun
failed identically. No sandbox permission denial occurred; the environment
instead allowed the source mode expected to be rejected. The five new methods
pass together, and no production operator or CLI code was changed.
