import pathlib
import tempfile
import unittest
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from registry_control import RunnerRegistryControl
from scripts.factory_registry import (
    Feature,
    Lane,
    RegistryConflict,
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
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.registry.acquire_lease(
            "TASK-1",
            "worker-a",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:20:00Z",
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
