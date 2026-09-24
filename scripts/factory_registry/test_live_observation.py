import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.factory_registry.live_observation import (
    LiveObservationError,
    ObservationPlan,
    PreservationExpectation,
    WorkerObservationBinding,
    capture_live_observation,
    project_live_observation,
    reconcile_preservation,
    run_live_shadow_sweep,
    validate_evidence_destination,
    verify_source_proofs,
    write_live_sweep_evidence,
)
from scripts.factory_registry.models import DispatchSnapshot
from scripts.factory_registry.shadow_dispatch import RejectionCode, snapshot_fingerprint


NOW = "2026-09-24T12:00:00Z"


def epoch(value=NOW):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def preservation_payload(tasks=(), workers=("runner-a",), active=False):
    return {
        "worktrees": [
            {
                "worktree": f"/preserved/{index}",
                "HEAD": f"{index:040x}",
                "branch": f"refs/heads/preserved-{index}",
                "dirty": index < 8,
                "status_lines": [" M file"] if index < 8 else [],
            }
            for index in range(33)
        ],
        "dirty_worktree_count": 8,
        "unmerged_local_branches": [f"branch-{index}" for index in range(7)],
        "open_task_mapping": [{"task": value} for value in tasks],
        "services": {
            "heartbeats": {
                value: {"worker": value, "status": "idle", "task": None}
                for value in workers
            }
        },
        "issue_state_records": (
            {"1": {"status": "agent"}} if active else {"1": {"status": "review"}}
        ),
    }


def snapshot(*, packages=(), worker_usage=True, leases=()):
    usages = (
        {
            "id": "orchestra-usage",
            "worker_id": "orchestra",
            "capacity_scope": "default",
            "state": "GREEN",
            "consumed_percent": 20,
            "observed_at": NOW,
        },
    )
    if worker_usage:
        usages += (
            {
                "id": "old-worker-usage",
                "worker_id": "registry-a",
                "capacity_scope": "weekly_window",
                "state": "GREEN",
                "consumed_percent": 1,
                "observed_at": "2026-09-23T12:00:00Z",
            },
        )
    return DispatchSnapshot(
        revision=3,
        observed_at=NOW,
        active_parent_limit=3,
        orchestra_reserve_percent=20,
        features=(),
        work_packages=tuple(packages),
        dependencies=(),
        workers=(
            {
                "id": "registry-a",
                "display_name": "A",
                "role": "WORKER",
                "availability": "PRESERVED",
                "capabilities": ["platform"],
                "approved_lanes": ["PLATFORM"],
                "last_heartbeat_at": None,
                "provider_diagnostics": {"legacy_worker": "runner-a"},
            },
            {
                "id": "orchestra",
                "display_name": "Orchestra",
                "role": "ORCHESTRA",
                "availability": "IDLE",
                "capabilities": [],
                "approved_lanes": [],
                "last_heartbeat_at": NOW,
                "provider_diagnostics": {},
            },
        ),
        active_leases=tuple(leases),
        usage_observations=usages,
    )


class LiveFixture:
    def __init__(self, root, *, status="idle", task=None, ready=False, usage=True):
        self.root = Path(root)
        self.state = self.root / "state"
        self.config = self.root / "config.json"
        self.preservation = self.root / "preservation.json"
        self.output = self.root / "evidence.json"
        config = {
            "state": str(self.state),
            "usage_file": str(self.state / "usage.json"),
            "repo": str(self.root / "repo"),
            "agents": {
                "runner-a": {
                    "provider": "provider",
                    "model": "model",
                    "command": ["secret-command"],
                    "env": {"TOKEN": "never-serialize"},
                }
            },
        }
        write_json(self.config, config)
        write_json(
            self.state / "queue.json",
            {
                "entries": [
                    {
                        "number": 1,
                        "title": "queued",
                        "agent": "runner-a",
                        "readiness": ready,
                        "status": "ready" if ready else "unqueued",
                        "created_at": NOW,
                        "dependencies": {"items": [], "count": 0},
                    }
                ]
            },
        )
        write_json(
            self.state / "heartbeat-runner-a.json",
            {
                "worker": "runner-a",
                "status": status,
                "issue": 1 if task else None,
                "task": task,
                "pid": 123,
                "start_time": epoch() if task else None,
                "time": epoch(),
            },
        )
        if usage:
            write_json(
                self.state / "usage.json",
                {
                    "workers": {
                        "runner-a": {
                            "account-a": {
                                "provider": "provider",
                                "model": "model",
                                "used_percent": 10,
                                "observed_at": NOW,
                                "reset_at": "2026-09-30T12:00:00Z",
                            }
                        }
                    }
                },
            )
        payload = preservation_payload()
        write_json(self.preservation, payload)
        digest = hashlib.sha256(self.preservation.read_bytes()).hexdigest()
        self.plan = ObservationPlan(
            workers=(
                WorkerObservationBinding(
                    "runner-a",
                    "registry-a",
                    capacity_scopes=("weekly_window",),
                    usage_account_by_scope=(("weekly_window", "account-a"),),
                ),
            ),
            preservation=PreservationExpectation(digest, 33, 8, 7, 0, 0),
        )


class LiveObservationTests(unittest.TestCase):
    def test_capture_normalizes_heartbeat_and_usage_without_config_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            self.assertEqual(observed.worker_updates[0]["availability"], "IDLE")
            self.assertEqual(observed.worker_updates[0]["last_heartbeat_at"], NOW.replace("Z", ".000000Z"))
            self.assertEqual(observed.usage_observations[0]["capacity_scope"], "weekly_window")
            self.assertEqual(observed.usage_observations[0]["state"], "GREEN")
            serialized = json.dumps(
                {
                    "workers": observed.worker_updates,
                    "usage": observed.usage_observations,
                    "warnings": observed.warnings,
                }
            )
            self.assertNotIn("secret-command", serialized)
            self.assertNotIn("never-serialize", serialized)
            config_source = next(
                value for value in observed.sources if value.label == "runner_config"
            )
            self.assertIsNone(config_source.raw)
            self.assertNotIn("secret-command", repr(observed))
            self.assertNotIn("never-serialize", repr(observed))

    def test_usage_warning_never_emits_raw_account_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            usage_path = fixture.state / "usage.json"
            usage = json.loads(usage_path.read_text())
            secret_key = "credential-like-account-key"
            usage["workers"]["runner-a"][secret_key] = {
                "used_percent": 1,
                "observed_at": NOW,
            }
            write_json(usage_path, usage)

            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            warning_text = "\n".join(observed.warnings)
            self.assertIn("UNMAPPED_USAGE_SOURCES:runner-a:count=1", warning_text)
            self.assertNotIn(secret_key, warning_text)
            usage_source = next(value for value in observed.sources if value.label == "usage")
            self.assertIsNone(usage_source.raw)

    def test_projection_is_copy_only_and_replaces_authoritative_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            base = snapshot()
            before = snapshot_fingerprint(base)
            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            projected = project_live_observation(base, observed, fixture.plan)
            self.assertEqual(snapshot_fingerprint(base), before)
            worker = next(value for value in projected.workers if value["id"] == "registry-a")
            self.assertEqual(worker["availability"], "IDLE")
            self.assertEqual(worker["capacity_scopes"], ["weekly_window"])
            worker_usage = [
                value for value in projected.usage_observations if value["worker_id"] == "registry-a"
            ]
            self.assertEqual(len(worker_usage), 1)
            self.assertEqual(worker_usage[0]["consumed_percent"], 10)

    def test_stale_usage_and_missing_usage_fail_closed_in_scheduler(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            usage_path = fixture.state / "usage.json"
            usage = json.loads(usage_path.read_text())
            usage["workers"]["runner-a"]["account-a"]["observed_at"] = "2026-09-24T11:00:00Z"
            write_json(usage_path, usage)
            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            projected = project_live_observation(snapshot(), observed, fixture.plan)
            from scripts.factory_registry.shadow_dispatch import decide_shadow

            decision = decide_shadow(projected, policy=fixture.plan.policy.shadow_policy())
            worker = next(value for value in decision.worker_evaluations if value.id == "registry-a")
            self.assertIn(RejectionCode.USAGE_STALE.value, {value.code for value in worker.reasons})

            usage_path.unlink()
            missing = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            missing_projected = project_live_observation(snapshot(), missing, fixture.plan)
            missing_decision = decide_shadow(
                missing_projected, policy=fixture.plan.policy.shadow_policy()
            )
            missing_worker = next(
                value for value in missing_decision.worker_evaluations if value.id == "registry-a"
            )
            self.assertIn(RejectionCode.USAGE_MISSING.value, {value.code for value in missing_worker.reasons})

    def test_missing_heartbeat_projects_constrained_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            (fixture.state / "heartbeat-runner-a.json").unlink()
            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            projected = project_live_observation(snapshot(), observed, fixture.plan)
            worker = next(value for value in projected.workers if value["id"] == "registry-a")
            self.assertEqual(worker["availability"], "CONSTRAINED")
            self.assertIsNone(worker["last_heartbeat_at"])
            self.assertIn(
                "HEARTBEAT_SOURCE_MISSING_OR_INVALID:runner-a", observed.warnings
            )

    def test_busy_heartbeat_is_observed_but_never_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory, status="agent", task="TASK-1")
            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            self.assertEqual(
                observed.legacy_observation.assignments[0].as_dict(),
                {"package_id": "TASK-1", "worker_id": "registry-a"},
            )
            self.assertEqual(observed.worker_updates[0]["availability"], "BUSY")

    def test_ready_queue_is_unresolved_instead_of_inventing_task_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory, ready=True)
            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            self.assertFalse(observed.legacy_observation.complete)
            self.assertIn("LEGACY_READY_QUEUE_UNRESOLVED:count=1", observed.warnings)

    def test_volatile_heartbeat_timestamp_change_is_semantically_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            observed = capture_live_observation(
                fixture.config, fixture.preservation, fixture.plan, observed_at=NOW
            )
            heartbeat_path = fixture.state / "heartbeat-runner-a.json"
            changed = json.loads(heartbeat_path.read_text())
            changed["time"] += 60
            changed["pid"] += 1
            changed_raw = (json.dumps(changed, sort_keys=True) + "\n").encode()

            def reader(path):
                return changed_raw if path == heartbeat_path else path.read_bytes()

            proofs = verify_source_proofs(observed.sources, reader=reader)
            heartbeat = next(value for value in proofs if value.label == "heartbeat:runner-a")
            self.assertFalse(heartbeat.content_unchanged)
            self.assertTrue(heartbeat.semantic_unchanged)

            changed["task"] = "TASK-CHANGED"
            changed_raw = (json.dumps(changed, sort_keys=True) + "\n").encode()
            proofs = verify_source_proofs(observed.sources, reader=reader)
            heartbeat = next(value for value in proofs if value.label == "heartbeat:runner-a")
            self.assertFalse(heartbeat.semantic_unchanged)

    def test_preservation_reconciliation_detects_tasks_and_active_ownership(self):
        payload = preservation_payload(tasks=("TASK-1",), active=True)
        raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
        base = snapshot(
            packages=(
                {
                    "id": "TASK-2",
                    "status": "ON_DECK",
                    "kind": "PARENT",
                    "lane": None,
                    "created_at": NOW,
                },
            ),
            leases=(
                {
                    "id": "lease",
                    "package_id": "TASK-2",
                    "worker_id": "registry-a",
                    "expired": False,
                },
            ),
        )
        expectation = PreservationExpectation(hashlib.sha256(raw).hexdigest(), 33, 8, 7, 0, 0)
        result = reconcile_preservation(raw, base, expectation)
        self.assertFalse(result.passed)
        self.assertEqual(result.unexplained_record_count, 1)
        self.assertEqual(result.active_lease_count, 1)
        self.assertEqual(result.active_legacy_record_count, 1)

    def test_preservation_reconciliation_ignores_native_post_import_packages(self):
        payload = preservation_payload(tasks=("TASK-1",))
        raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
        digest = hashlib.sha256(raw).hexdigest()
        imported = {
            "id": "TASK-1",
            "provider_diagnostics": {
                "preservation_import_id": f"preservation:{digest[:20]}"
            },
        }
        native = {
            "id": "TASK-NATIVE",
            "provider_diagnostics": {},
        }
        base = snapshot(packages=(imported, native))
        result = reconcile_preservation(
            raw,
            base,
            PreservationExpectation(digest, 33, 8, 7, 0, 0),
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.unexplained_record_count, 0)

    def test_preservation_reconciliation_rejects_duplicate_source_tasks(self):
        payload = preservation_payload(tasks=("TASK-1", "TASK-1"))
        raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
        digest = hashlib.sha256(raw).hexdigest()
        imported = {
            "id": "TASK-1",
            "provider_diagnostics": {
                "preservation_import_id": f"preservation:{digest[:20]}"
            },
        }
        result = reconcile_preservation(
            raw,
            snapshot(packages=(imported,)),
            PreservationExpectation(digest, 33, 8, 7, 0, 0),
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.unexplained_record_count, 1)
        self.assertIn("duplicate source task IDs: TASK-1", result.failures)

    def test_live_sweep_records_all_decision_surfaces_and_is_create_only(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            base = snapshot()
            before = snapshot_fingerprint(base)
            file_before = {
                path: path.read_bytes()
                for path in (
                    fixture.config,
                    fixture.state / "queue.json",
                    fixture.state / "usage.json",
                    fixture.state / "heartbeat-runner-a.json",
                    fixture.preservation,
                )
            }
            evidence = run_live_shadow_sweep(
                base,
                fixture.config,
                fixture.preservation,
                fixture.plan,
                observed_at=NOW,
            )
            self.assertTrue(evidence.passed)
            self.assertEqual(snapshot_fingerprint(base), before)
            self.assertTrue(evidence.preservation.passed)
            self.assertEqual(len(evidence.decision.worker_evaluations), 2)
            self.assertEqual(len(evidence.decision.package_evaluations), 0)
            self.assertEqual(len(evidence.decision.pair_evaluations), 0)
            self.assertTrue(evidence.legacy_comparison.gate_passed)
            self.assertEqual(file_before, {path: path.read_bytes() for path in file_before})
            self.assertNotIn("secret-command", evidence.to_json())
            self.assertNotIn("never-serialize", evidence.to_json())
            with self.assertRaises(LiveObservationError):
                write_live_sweep_evidence(
                    evidence,
                    fixture.state / "forbidden-evidence.json",
                    config_path=fixture.config,
                    preservation_path=fixture.preservation,
                )
            self.assertEqual(
                write_live_sweep_evidence(
                    evidence,
                    fixture.output,
                    config_path=fixture.config,
                    preservation_path=fixture.preservation,
                ),
                fixture.output,
            )
            with self.assertRaises(FileExistsError):
                write_live_sweep_evidence(
                    evidence,
                    fixture.output,
                    config_path=fixture.config,
                    preservation_path=fixture.preservation,
                )

    def test_live_clock_is_sampled_after_advancing_heartbeat_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            heartbeat_path = fixture.state / "heartbeat-runner-a.json"
            heartbeat = json.loads(heartbeat_path.read_text())
            heartbeat["time"] = epoch("2026-09-24T12:01:00Z")
            write_json(heartbeat_path, heartbeat)

            evidence = run_live_shadow_sweep(
                snapshot(),
                fixture.config,
                fixture.preservation,
                fixture.plan,
                clock=lambda: datetime.fromisoformat("2026-09-24T12:02:00+00:00"),
            )

            self.assertEqual(evidence.observed_at, "2026-09-24T12:02:00.000000Z")
            worker = next(
                value for value in evidence.decision.worker_evaluations
                if value.id == "registry-a"
            )
            self.assertNotIn(
                RejectionCode.HEARTBEAT_IN_FUTURE.value,
                {value.code for value in worker.reasons},
            )

    def test_source_change_and_preservation_mismatch_fail_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            queue_path = fixture.state / "queue.json"

            def reader(path):
                if path == queue_path:
                    return b'{"entries":[]}\n'
                return path.read_bytes()

            wrong_plan = copy.deepcopy(fixture.plan)
            object.__setattr__(
                wrong_plan,
                "preservation",
                PreservationExpectation("0" * 64, 33, 8, 7, 0, 0),
            )
            evidence = run_live_shadow_sweep(
                snapshot(),
                fixture.config,
                fixture.preservation,
                wrong_plan,
                observed_at=NOW,
                source_reader=reader,
            )
            self.assertFalse(evidence.passed)
            self.assertTrue(any("queue" in value for value in evidence.failures))
            self.assertTrue(any("preservation" in value for value in evidence.failures))

    def test_plan_rejects_ambiguous_scope_mappings(self):
        with self.assertRaises(LiveObservationError):
            WorkerObservationBinding(
                "runner-a",
                "registry-a",
                usage_account_by_scope=(
                    ("short_window", "same-account"),
                    ("weekly_window", "same-account"),
                ),
            )

    def test_evidence_destination_rejects_factory_and_preserved_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LiveFixture(directory)
            with self.assertRaises(LiveObservationError):
                validate_evidence_destination(
                    fixture.state / "evidence.json", fixture.config, fixture.preservation
                )
            preserved = json.loads(fixture.preservation.read_text())
            preserved["canonical_repository"] = {"path": str(fixture.root / "canonical")}
            write_json(fixture.preservation, preserved)
            with self.assertRaises(LiveObservationError):
                validate_evidence_destination(
                    fixture.root / "canonical" / "evidence.json",
                    fixture.config,
                    fixture.preservation,
                )
            validate_evidence_destination(
                fixture.root.parent / "separate-evidence.json",
                fixture.config,
                fixture.preservation,
            )


if __name__ == "__main__":
    unittest.main()
