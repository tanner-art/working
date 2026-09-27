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

TASK-321 corrected the disposable CLI fixture, rather than the operator gate:
before both packet branches it explicitly establishes `0700` Registry, state,
and worktree directories and `0600` database, SQLite WAL/SHM sidecars when
present, and config. The release remains private and immutable. Thus the test
reaches its intended tamper assertion under Linux-default `umask 022` without
weakening any production permission validation.

Validation executed on 2026-09-27:

```text
umask 022 && PYTHONPYCACHEPREFIX=/private/tmp/task321-umask022-pyc python3 -m unittest -v scripts.factory_registry.test_operator.OperatorFixture.test_record_review_input_cli_publishes_valid_packet_and_refuses_tampering
# Ran 1 test: OK

umask 077 && PYTHONPYCACHEPREFIX=/private/tmp/task321-umask077-pyc python3 -m unittest -v scripts.factory_registry.test_operator.OperatorFixture.test_record_review_input_cli_publishes_valid_packet_and_refuses_tampering
# Ran 1 test: OK

umask 022 && PYTHONPYCACHEPREFIX=/private/tmp/task321-registry-discovery-pyc python3 -m unittest discover -s scripts/factory_registry -p 'test_*.py' -v
# Ran 244 tests: FAILED (29 loopback-bind errors)
```

The 29 discovery errors are `ProjectionTransportTest` setup failures because
this sandbox forbids binding a loopback `127.0.0.1` HTTP server. They do not
indicate a permission-gate failure; the corrected CLI regression passes under
both umasks. No production operator or CLI policy was weakened.
