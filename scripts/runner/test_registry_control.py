import pathlib
import tempfile
import unittest
from unittest.mock import patch

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
