import pathlib
import sys
import tempfile
import unittest
import json
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from registry_control import RunnerRegistryControl, queue_contract_digest
from runner import RegistryAttemptLifecycle, run
from scripts.factory_registry import (
    Feature,
    Lane,
    PackageKind,
    RegistryConflict,
    ReviewInput,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
)


class RunnerRegistryControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = pathlib.Path(self.temporary.name) / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def seed_assignment(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker(
                "worker-a",
                "Worker A",
                ("registry",),
                (Lane.PLATFORM,),
                usage_state="GREEN",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1",
                "FEATURE",
                "Task",
                "ORCHESTRATION",
                Lane.PLATFORM,
                ("registry",),
                10,
                ("verified",),
                status=TaskStatus.READY,
            )
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at=(now - timedelta(minutes=2)).isoformat(),
            reason="bounded canary",
        )
        self.registry.acquire_lease(
            "TASK-1",
            "worker-a",
            acquired_at=(now - timedelta(minutes=1)).isoformat(),
            expires_at=(now + timedelta(minutes=20)).isoformat(),
        )

    def test_is_absent_for_legacy_config_and_rejects_relative_database(self):
        self.assertIsNone(RunnerRegistryControl.from_config({}))
        with self.assertRaisesRegex(ValueError, "absolute"):
            RunnerRegistryControl.from_config({"registry_database": "registry.sqlite3"})

    def test_pre_claim_fails_closed_while_registry_is_paused(self):
        control = RunnerRegistryControl(self.database)
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            control.pre_claim()

    def test_pre_claim_requires_the_exact_registry_assignment_and_revision(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(revision=17)
        control.registry.require_live_dispatch.return_value = 17
        eligible = SimpleNamespace(package_id="TASK-1", worker_id="worker-a")
        decision = SimpleNamespace(proposed_assignments=(eligible,), pair_evaluations=())
        with patch("registry_control.decide_shadow", return_value=decision):
            self.assertEqual(control.pre_claim("TASK-1", "worker-a"), 17)
        control.registry.require_live_dispatch.assert_called_once_with(
            expected_revision=17
        )

        with patch(
            "registry_control.decide_shadow",
            return_value=SimpleNamespace(
                proposed_assignments=(), pair_evaluations=()
            ),
        ):
            with self.assertRaisesRegex(RegistryConflict, "PAIR_NOT_FOUND"):
                control.pre_claim("TASK-1", "worker-a")

    def test_pre_claim_pins_the_normalized_queue_contract(self):
        body = {
            "task": "TASK-1", "paths": ["docs/canary.md"],
            "instructions": "Write the canary.", "depends_on": [],
            "lane": "PLATFORM", "kind": "PARENT",
            "capacity_size": "VERY_SMALL", "capacity_risk": "BOUNDED",
        }
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            revision=17,
            work_packages=({
                "id": "TASK-1",
                "provider_diagnostics": {
                    "queue_contract_sha256": queue_contract_digest(body),
                },
            },),
        )
        control.registry.require_live_dispatch.return_value = 17
        eligible = SimpleNamespace(package_id="TASK-1", worker_id="worker-a")
        decision = SimpleNamespace(proposed_assignments=(eligible,), pair_evaluations=())
        with patch("registry_control.decide_shadow", return_value=decision):
            self.assertEqual(
                control.pre_claim("TASK-1", "worker-a", task_contract=body), 17
            )
            changed = dict(body, instructions="Different work")
            with self.assertRaisesRegex(RegistryConflict, "QUEUE_CONTRACT_MISMATCH"):
                control.pre_claim("TASK-1", "worker-a", task_contract=changed)

    def test_review_preclaim_excludes_the_actual_implementer(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            revision=17,
            work_packages=({"id": "TASK-REVIEW", "kind": "REVIEW"},),
        )
        control.registry.review_implementer_worker.return_value = "worker-a"
        control.registry.require_live_dispatch.return_value = 17
        eligible = SimpleNamespace(package_id="TASK-REVIEW", worker_id="worker-b")
        decision = SimpleNamespace(proposed_assignments=(eligible,), pair_evaluations=())
        with patch("registry_control.decide_shadow", return_value=decision):
            with self.assertRaisesRegex(
                RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"
            ):
                control.pre_claim("TASK-REVIEW", "worker-a")
            self.assertEqual(control.pre_claim("TASK-REVIEW", "worker-b"), 17)
        control.registry.review_implementer_worker.assert_called_with("TASK-REVIEW")

    def test_review_preclaim_fails_closed_when_its_bound_input_is_missing(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            revision=17,
            work_packages=({"id": "TASK-REVIEW", "kind": "REVIEW"},),
        )
        control.registry.review_input.side_effect = RegistryConflict("REVIEW_INPUT_REQUIRED")
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_REQUIRED"):
            control.pre_claim("TASK-REVIEW", "worker-b")
        control.registry.review_implementer_worker.assert_not_called()

    def test_claim_package_pins_dispatch_revision(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.acquire_lease.return_value = SimpleNamespace(id="lease-1")
        with patch("registry_control.datetime") as clock:
            clock.now.return_value = __import__('datetime').datetime(
                2026, 9, 25, tzinfo=__import__('datetime').timezone.utc
            )
            lease_id = control.claim_package(
                "TASK-1", worker_id="worker-a", expected_revision=9,
                lease_seconds=300,
            )
        self.assertEqual(lease_id, "lease-1")
        self.assertEqual(
            control.registry.acquire_lease.call_args.kwargs["expected_dispatch_revision"],
            9,
        )

    def test_pre_claim_uses_live_registry_health_and_capacity_evidence(self):
        now = datetime.now(timezone.utc).isoformat()
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker(
                "worker-a", "Worker A", ("registry",), (Lane.PLATFORM,),
                provider_diagnostics={
                    "capacity_mode": "provider_signal",
                    "capacity_scopes": ["provider_signal"],
                },
                last_heartbeat_at=now,
                usage_state="NORMAL",
            )
        )
        self.registry.register_worker(
            Worker(
                "orchestra", "Orchestra", (), (), role="ORCHESTRA",
                provider_diagnostics={
                    "capacity_mode": "percentage",
                    "capacity_scopes": ["weekly"],
                },
                last_heartbeat_at=now,
                usage_state="NORMAL",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1", "FEATURE", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 10, ("verified",), status=TaskStatus.READY,
            )
        )
        now = datetime.now(timezone.utc).isoformat()
        with self.registry._connection() as connection:
            connection.execute(
                """INSERT INTO usage_observations
                   (id, worker_id, observed_at, consumed_percent, state,
                    provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "usage-worker", "worker-a", now, None, "NORMAL",
                    json.dumps({
                        "capacity_mode": "provider_signal",
                        "capacity_scope": "provider_signal",
                        "service_state": "healthy",
                        "authentication_state": "valid",
                        "live_invocation_state": "succeeded",
                        "limit_signal": "NONE",
                    }),
                ),
            )
            connection.execute(
                """INSERT INTO usage_observations
                   (id, worker_id, observed_at, consumed_percent, state,
                    provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "usage-orchestra", "orchestra", now, 10, "NORMAL",
                    json.dumps({
                        "capacity_mode": "percentage",
                        "capacity_scope": "weekly",
                    }),
                ),
            )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=now,
            reason="bounded canary",
        )
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.utc_now", return_value=now):
            revision = control.pre_claim("TASK-1", "worker-a")
        self.assertEqual(revision, self.registry.dispatch_control()["revision"])

    def test_reserve_launch_and_failure_are_durable(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        revision = control.pre_claim()
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1",
                package_id="TASK-1",
                worker_id="worker-a",
                expected_revision=revision,
            )
        control.pre_launch()
        control.record_process("attempt-1", pid=901, pgid=901)
        control.fail("attempt-1", "bounded failure")

        with self.registry._connection() as connection:
            runtime = connection.execute(
                """SELECT runner_pid, agent_pid, agent_pgid, released_at
                   FROM attempt_runtime_ownership WHERE attempt_id='attempt-1'"""
            ).fetchone()
            attempt = connection.execute(
                "SELECT outcome, failure_detail FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            package = connection.execute(
                "SELECT status FROM work_packages WHERE id='TASK-1'"
            ).fetchone()[0]
        self.assertEqual(tuple(runtime[:3]), (900, 901, 901))
        self.assertIsNotNone(runtime[3])
        self.assertEqual(tuple(attempt), ("FAILED", "bounded failure"))
        self.assertEqual(package, "BLOCKED")

    def test_implementation_completion_and_review_input_are_atomic(self):
        self.seed_assignment()
        self.registry.register_work_package(WorkPackage(
            "REVIEW-1", "FEATURE", "Review", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 10, ("review",), kind=PackageKind.REVIEW,
            dependency_ids=("TASK-1",), status=TaskStatus.READY,
        ))
        control = RunnerRegistryControl(self.database)
        revision = control.pre_claim()
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt("attempt-atomic", package_id="TASK-1", worker_id="worker-a", expected_revision=revision)
        completed_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        contract = {"task": "TASK-1", "instructions": "résumé"}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        review_input = ReviewInput(
            id="review-input-atomic", review_package_id="REVIEW-1", target_package_id="TASK-1",
            implementation_attempt_id="attempt-atomic", implementation_commit="a" * 40,
            base_commit="b" * 40, pr_url="https://example.test/pr/1", contract_sha256=digest,
            contract=contract, validation_evidence={"focused": "passed"}, recorded_at=completed_at,
        )
        control.succeed("attempt-atomic", review_inputs=(review_input,), ended_at=completed_at)
        self.assertEqual(self.registry.review_input("REVIEW-1")["id"], "review-input-atomic")
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute("SELECT status FROM work_packages WHERE id='TASK-1'").fetchone()[0], "VERIFY_REVIEW")

    def test_lease_revocation_stops_renewal_and_recovery_closes_runtime(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker("worker-a", "Worker A", ("registry",), (Lane.PLATFORM,))
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1", "FEATURE", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 10, ("verified",), status=TaskStatus.READY,
            )
        )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=now.isoformat(), reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK-1", "worker-a", acquired_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1", package_id="TASK-1", worker_id="worker-a",
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        control.renew_runtime("attempt-1", lease.id, lease_seconds=300)
        control.record_process("attempt-1", pid=901, pgid=901)

        revoked_at = datetime.now(timezone.utc)
        self.registry.release_lease(
            lease.id, released_at=revoked_at.isoformat(),
            reason="operator revoked lease", next_status=TaskStatus.BLOCKED,
        )
        with self.assertRaisesRegex(RegistryConflict, "LEASE_REVOKED"):
            control.renew_runtime("attempt-1", lease.id, lease_seconds=300)
        control.fail("attempt-1", "runtime monitor observed lease revocation")

        with self.registry._connection() as connection:
            runtime = connection.execute(
                """SELECT released_at FROM attempt_runtime_ownership
                   WHERE attempt_id='attempt-1'"""
            ).fetchone()
            attempt = connection.execute(
                "SELECT ended_at, outcome FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            failures = connection.execute(
                """SELECT code FROM failure_observations
                   WHERE attempt_id='attempt-1' ORDER BY observed_at"""
            ).fetchall()
        self.assertIsNotNone(runtime["released_at"])
        self.assertIsNotNone(attempt["ended_at"])
        self.assertEqual(attempt["outcome"], "FAILED")
        self.assertIn("RUNTIME_RECOVERY", [row["code"] for row in failures])

    def test_real_provider_is_stopped_when_registry_lease_expires(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker("worker-a", "Worker A", ("registry",), (Lane.PLATFORM,))
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1", "FEATURE", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 10, ("verified",), status=TaskStatus.READY,
            )
        )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=now.isoformat(), reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK-1", "worker-a",
            acquired_at=(now - timedelta(seconds=10)).isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1", package_id="TASK-1", worker_id="worker-a",
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        lifecycle = RegistryAttemptLifecycle(control, "attempt-1")

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            started, completed = root / "started", root / "completed"
            command = [
                sys.executable, "-c",
                (
                    "from pathlib import Path; import time; "
                    f"Path({str(started)!r}).write_text('started'); "
                    "time.sleep(5); "
                    f"Path({str(completed)!r}).write_text('completed')"
                ),
            ]

            def bind_then_expire(pid):
                control.record_process("attempt-1", pid=pid, pgid=pid)
                expired_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat()
                with self.registry._connection() as connection:
                    connection.execute(
                        "UPDATE leases SET expires_at=? WHERE id=?",
                        (expired_at, lease.id),
                    )

            def monitor_registry():
                if started.exists():
                    control.renew_runtime("attempt-1", lease.id, lease_seconds=300)

            with self.assertRaisesRegex(RuntimeError, "LEASE_EXPIRED"):
                run(
                    command, launch_barrier=True, on_start=bind_then_expire,
                    monitor=monitor_registry, monitor_interval=0.1, timeout=10,
                )
            lifecycle.fail("runtime monitor observed lease expiry")
            self.assertTrue(started.exists())
            self.assertFalse(completed.exists())

        self.assertEqual(self.registry.active_attempt_runtimes(), ())
        with self.registry._connection() as connection:
            attempt = connection.execute(
                "SELECT outcome, ended_at FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            released = connection.execute(
                "SELECT released_at FROM leases WHERE id=?", (lease.id,)
            ).fetchone()[0]
        self.assertEqual(attempt["outcome"], "FAILED")
        self.assertIsNotNone(attempt["ended_at"])
        self.assertIsNotNone(released)

    def test_worker_disappearance_globally_stops_and_reconciles_all_runtimes(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        for suffix in ("a", "b", "c"):
            worker_id = f"worker-{suffix}"
            package_id = f"TASK-{suffix.upper()}"
            self.registry.register_worker(
                Worker(worker_id, worker_id, ("registry",), (Lane.PLATFORM,))
            )
            self.registry.register_work_package(
                WorkPackage(
                    package_id, "FEATURE", package_id, "ORCHESTRATION",
                    Lane.PLATFORM, ("registry",), 10, ("verified",),
                    status=TaskStatus.READY,
                )
            )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=now.isoformat(), reason="bounded canary",
        )
        for index, suffix in enumerate(("a", "b"), start=1):
            worker_id = f"worker-{suffix}"
            package_id = f"TASK-{suffix.upper()}"
            self.registry.acquire_lease(
                package_id, worker_id, acquired_at=now.isoformat(),
                expires_at=(now + timedelta(minutes=5)).isoformat(),
            )
            self.registry.begin_attempt_runtime(
                f"attempt-{suffix}", package_id=package_id, worker_id=worker_id,
                runner_pid=800 + index, started_at=now.isoformat(),
                expected_revision=self.registry.dispatch_control()["revision"],
            )
            if suffix == "a":
                self.registry.record_attempt_process(
                    f"attempt-{suffix}", agent_pid=900 + index,
                    agent_pgid=900 + index, recorded_at=now.isoformat(),
                )
        lease_only = self.registry.acquire_lease(
            "TASK-C", "worker-c", acquired_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )

        terminated = []
        control = RunnerRegistryControl(self.database)
        result = control.handle_worker_disappearance(
            "worker-a", terminate=terminated.append
        )
        self.assertEqual(result["unresolved"], ())
        self.assertEqual(terminated, [901])
        self.assertIn(f"lease:{lease_only.id}", result["resolved"])
        state = self.registry.dispatch_control()
        self.assertEqual(state["dispatch_mode"], "PAUSED")
        self.assertTrue(state["kill_switch_engaged"])
        self.assertEqual(self.registry.active_attempt_runtimes(), ())
        with self.registry._connection() as connection:
            workers = dict(connection.execute(
                "SELECT id, availability FROM workers ORDER BY id"
            ).fetchall())
            packages = dict(connection.execute(
                "SELECT id, status FROM work_packages ORDER BY id"
            ).fetchall())
            attempts = connection.execute(
                "SELECT outcome FROM attempts ORDER BY id"
            ).fetchall()
        self.assertEqual(workers, {
            "worker-a": "OFFLINE", "worker-b": "IDLE", "worker-c": "IDLE",
        })
        self.assertEqual(packages, {
            "TASK-A": "BLOCKED", "TASK-B": "BLOCKED", "TASK-C": "BLOCKED",
        })
        self.assertEqual([row["outcome"] for row in attempts], ["FAILED", "FAILED"])
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            control.pre_claim()
        repeated = control.handle_worker_disappearance(
            "worker-a", terminate=terminated.append
        )
        self.assertEqual(repeated, {"resolved": (), "unresolved": ()})
        self.assertEqual(terminated, [901])
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_unresolved_stop_keeps_stopping_and_records_deterministic_evidence(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1", package_id="TASK-1", worker_id="worker-a",
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        control.record_process("attempt-1", pid=901, pgid=901)
        control.engage_stop("operator pause")

        def cannot_terminate(_pgid):
            raise RuntimeError("simulated surviving process")

        result = control.reconcile_stopping_runtimes(terminate=cannot_terminate)
        self.assertEqual(result["resolved"], ())
        self.assertEqual(result["unresolved"], ("attempt-1",))
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "STOPPING")
        self.assertEqual(
            [item["attempt_id"] for item in self.registry.active_attempt_runtimes()],
            ["attempt-1"],
        )
        with self.registry._connection() as connection:
            failures = connection.execute(
                """SELECT id, code, detail FROM failure_observations
                   WHERE attempt_id='attempt-1'"""
            ).fetchall()
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["code"], "RUNTIME_RECOVERY_FAILED")
        self.assertIn("simulated surviving process", failures[0]["detail"])

    def test_process_record_fails_after_kill_switch(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1",
                package_id="TASK-1",
                worker_id="worker-a",
                expected_revision=control.pre_claim(),
            )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:00Z", reason="operator stop"
        )
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            control.record_process("attempt-1", pid=901, pgid=901)


if __name__ == "__main__":
    unittest.main()
