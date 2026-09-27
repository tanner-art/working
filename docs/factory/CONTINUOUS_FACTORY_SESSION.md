# Continuous Factory Session

This is source-only control-plane behavior until a separately reviewed, drained
installation authorizes it. The Registry remains the lease and lifecycle
authority; this document does not authorize live dispatch or merging.

| Criterion | Production functions | Scenario coverage | Result |
| --- | --- | --- | --- |
| Review work wins at an idle boundary; no active attempt is preempted | `session_queue.ordered_assignments`, `RunnerRegistryControl.pre_claim` | `test_session_queue`, `test_registry_control` | focused pass |
| A bounded envelope can retain a dormant capability-valid pair | `bounded_run_worker_gate`, `register_bounded_pilot` | `test_operator` bounded-pilot gate | focused pass |
| A heartbeat revision race cannot lose a valid lease | `RunnerRegistryControl.reserve_attempt` | Registry-control reservation scenarios | focused pass |
| Independent Codex review is read-only and packet-scoped | `review_command`, `build_review_prompt` | `test_runner` adapter scenario | focused pass |

Run the local focused matrix with:

```
PYTHONPATH=$PWD/scripts/runner:$PWD python3 -m unittest \
  scripts.factory_registry.test_operator scripts.runner.test_registry_control \
  scripts.runner.test_runner scripts.runner.test_session_queue
```

The complete Registry/runner discovery commands remain coordinator-owned. In
the restricted sandbox, loopback projection tests may report `PermissionError`
when binding `127.0.0.1`; that is an environment limitation, not acceptance
evidence.
