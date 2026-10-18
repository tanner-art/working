"""Failure-oriented tests for the independently scheduled bounded-run guards."""

from __future__ import annotations

import json
import pathlib
import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts.factory_registry import bounded_run_guard as guard
from scripts.factory_registry import test_delivery_registry as delivery_fixtures
from scripts.factory_registry.models import Feature, Lane, TaskStatus, WorkPackage
from scripts.factory_registry.operator import stop
from scripts.factory_registry.sqlite_registry import SQLiteRegistry


class BoundedRunGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.database = self.root / "registry.sqlite"
        self.spec_path = self.root / "run.json"
        self.state = self.root / "state"
        self.state.mkdir()
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.registry.register_feature(Feature("F", "Feature", 1, TaskStatus.READY))
        self.registry.register_work_package(WorkPackage(
            "TASK-1", "F", "Task", "test", Lane.PLATFORM, ("code",), 1,
            ("works",), status=TaskStatus.READY,
        ))
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.run_id = "guard-test-01"
        self.spec = {
            "run_id": self.run_id, "package_ids": ["TASK-1"],
            "deadline": self.stamp(self.now + timedelta(hours=1)),
            "base_ref": "main", "parent_limit": 1,
        }
        self.write_spec()

    @staticmethod
    def stamp(value: datetime) -> str:
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def write_spec(self) -> None:
        self.spec_path.write_text(json.dumps(self.spec), encoding="utf-8")

    def enable(self, *, scope: dict | None = None) -> None:
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.stamp(self.now), reason="test bounded run",
            bounded_run=scope or self.spec,
        )

    def run_guard(self, role: str = "primary", *, at: datetime | None = None) -> dict:
        return guard.guard_once(
            self.database, self.spec_path, self.state, self.run_id, role,
            now=at or self.now + timedelta(seconds=10),
        )

    def live_primary_heartbeat(self, *, at: datetime | None = None,
                               observed_mode: str = "LIVE") -> None:
        checked = at or self.now
        guard._atomic_heartbeat(
            guard._heartbeat_path(self.state, self.run_id, "primary"),
            {"run_id": self.run_id, "role": "primary", "checked_at": self.stamp(checked),
             "observed_mode": observed_mode, "action": "observe" if observed_mode == "LIVE" else "standby"},
        )

    def test_paused_standby_writes_private_atomic_heartbeat(self) -> None:
        record = self.run_guard()
        self.assertEqual(record["action"], "standby")
        path = guard._heartbeat_path(self.state, self.run_id, "primary")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), record)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_live_primary_uses_registry_deadline_and_reports_revision(self) -> None:
        self.enable()
        record = self.run_guard()
        self.assertEqual(record["action"], "observe")
        self.assertEqual(record["deadline"], self.spec["deadline"])
        self.assertEqual(record["registry_revision"], self.registry.dispatch_control()["revision"])
        self.assertTrue(record["scope_matches"])

    def test_deadline_stop_is_run_id_guarded_and_authoritative(self) -> None:
        self.enable()
        with patch.object(guard, "request_stop", side_effect=lambda db, why, run_id: (
            stop(db, why, expected_run_id=run_id) and True
        )) as stopper:
            record = self.run_guard(at=self.now + timedelta(hours=2))
        self.assertEqual(record["action"], "stop-requested")
        self.assertIn("deadline", record["reason"])
        self.assertEqual(stopper.call_args.args[2], self.run_id)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "STOPPING")

    def test_same_run_scope_mismatch_stops_instead_of_trusting_local_spec(self) -> None:
        changed = dict(self.spec, deadline=self.stamp(self.now + timedelta(hours=2)))
        self.enable(scope=changed)
        with patch.object(guard, "request_stop", side_effect=lambda db, why, run_id: (
            stop(db, why, expected_run_id=run_id) and True
        )):
            record = self.run_guard()
        self.assertEqual(record["deadline"], changed["deadline"])
        self.assertEqual(record["reason"], "authoritative bounded run scope mismatch")
        self.assertEqual(record["action"], "stop-requested")

    def test_legacy_package_scope_growth_remains_strict(self) -> None:
        self.registry.register_work_package(WorkPackage(
            "TASK-2", "F", "Second task", "test", Lane.PLATFORM, ("code",), 1,
            ("works",), status=TaskStatus.READY,
        ))
        self.enable(scope={**self.spec, "package_ids": ["TASK-1", "TASK-2"]})
        with patch.object(guard, "request_stop", return_value=False):
            record = self.run_guard()
        self.assertFalse(record["scope_matches"])
        self.assertEqual(record["reason"], "authoritative bounded run scope mismatch")
        self.assertEqual(record["action"], "stop-failed")

    def test_missing_primary_stops_live_review_even_before_deadline(self) -> None:
        self.enable()
        with patch.object(guard, "request_stop", side_effect=lambda db, why, run_id: (
            stop(db, why, expected_run_id=run_id) and True
        )):
            record = self.run_guard("watchdog")
        self.assertIn("primary stopper heartbeat unavailable", record["reason"])
        self.assertEqual(record["action"], "stop-requested")

    def test_non_object_primary_heartbeat_requests_stop_without_crashing(self) -> None:
        self.enable()
        path = guard._heartbeat_path(self.state, self.run_id, "primary")
        for payload in ("null", "[]", '"string"', "17"):
            with self.subTest(payload=payload):
                path.write_text(payload, encoding="utf-8")
                with patch.object(guard, "request_stop", return_value=False) as stopper:
                    record = self.run_guard("watchdog")
                self.assertEqual(record["action"], "stop-failed")
                self.assertEqual(record["reason"], "primary stopper heartbeat unavailable")
                self.assertEqual(stopper.call_args.args[2], self.run_id)

    def test_live_without_bounded_scope_requests_unscoped_stop(self) -> None:
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.stamp(self.now), reason="missing scope",
            bounded_run=None,
        )
        with patch.object(guard, "request_stop", side_effect=lambda db, why, run_id: (
            stop(db, why, expected_run_id=run_id) and True
        )) as stopper:
            record = self.run_guard()
        self.assertEqual(record["action"], "stop-requested")
        self.assertIn("no bounded run scope", record["reason"])
        self.assertIsNone(stopper.call_args.args[2])

    def test_stopping_is_terminal_for_guard_and_does_not_repeat_stop(self) -> None:
        self.enable()
        stop(self.database, "already stopping", expected_run_id=self.run_id)
        revision = self.registry.dispatch_control()["revision"]
        with patch.object(guard, "request_stop") as stopper:
            record = self.run_guard("watchdog")
        self.assertEqual(record["action"], "standby")
        stopper.assert_not_called()
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)

    def test_fresh_primary_can_warm_up_but_must_observe_live(self) -> None:
        self.enable()
        self.live_primary_heartbeat(observed_mode="PAUSED")
        self.assertEqual(self.run_guard("watchdog")["action"], "observe")
        with patch.object(guard, "request_stop", return_value=False):
            record = self.run_guard("watchdog", at=self.now + timedelta(seconds=100))
        self.assertEqual(record["action"], "stop-failed")
        self.assertIn("has not observed LIVE", record["reason"])

    def test_stale_and_future_primary_health_fail_closed(self) -> None:
        self.enable()
        for checked in (self.now - timedelta(minutes=5), self.now + timedelta(minutes=5)):
            with self.subTest(checked=checked):
                self.live_primary_heartbeat(at=checked)
                with patch.object(guard, "request_stop", return_value=False):
                    record = self.run_guard("watchdog")
                self.assertEqual(record["action"], "stop-failed")
                self.assertIn("stale", record["reason"])

    def test_invalid_local_spec_stops_matching_live_run(self) -> None:
        self.enable()
        self.spec_path.write_text("not json", encoding="utf-8")
        with patch.object(guard, "request_stop", side_effect=lambda db, why, run_id: (
            stop(db, why, expected_run_id=run_id) and True
        )) as stopper:
            record = self.run_guard()
        self.assertEqual(record["action"], "stop-requested")
        self.assertEqual(stopper.call_args.args[2], self.run_id)

    def test_invalid_local_spec_is_not_a_healthy_paused_preflight(self) -> None:
        self.spec_path.write_text("not json", encoding="utf-8")
        with patch.object(guard, "request_stop") as stopper:
            record = self.run_guard()
        self.assertEqual(record["action"], "invalid-spec")
        stopper.assert_not_called()

    def test_future_live_transition_timestamp_stops(self) -> None:
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.stamp(self.now + timedelta(minutes=10)), reason="bad future time",
            bounded_run=self.spec,
        )
        with patch.object(guard, "request_stop", return_value=False):
            record = self.run_guard()
        self.assertEqual(record["action"], "stop-failed")
        self.assertIn("transition time is in the future", record["reason"])

    def test_superseded_guard_does_not_kill_a_different_run(self) -> None:
        newer = dict(self.spec, run_id="new-run-02")
        self.enable(scope=newer)
        with patch.object(guard, "request_stop") as stopper:
            record = self.run_guard()
        self.assertEqual(record["action"], "superseded")
        stopper.assert_not_called()
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")

    def test_unknown_registry_health_requests_unscoped_emergency_stop(self) -> None:
        self.database.unlink()
        with patch.object(guard, "request_stop", return_value=False) as stopper:
            record = self.run_guard()
        self.assertEqual(record["action"], "stop-failed")
        self.assertIsNone(stopper.call_args.args[2])
        self.assertFalse(self.database.exists(), "read-only guard must not create a replacement Registry")

    def test_invalid_authoritative_scope_requests_unscoped_stop(self) -> None:
        self.enable()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE registry_metadata SET value=? WHERE key='bounded_run_scope'",
                ('{"run_id":"guard-test-01","deadline":"invalid"}',),
            )
        with patch.object(guard, "request_stop", return_value=False) as stopper:
            record = self.run_guard()
        self.assertEqual(record["action"], "stop-failed")
        self.assertIsNone(stopper.call_args.args[2])

    def test_heartbeat_write_failure_attempts_emergency_stop(self) -> None:
        self.enable()
        with patch.object(guard, "_atomic_heartbeat", side_effect=OSError("disk full")):
            with patch.object(guard, "request_stop", return_value=False) as stopper:
                with self.assertRaises(OSError):
                    self.run_guard()
        self.assertEqual(stopper.call_args.args[2], self.run_id)

    def test_stop_command_uses_reviewed_operator_and_exact_run_id(self) -> None:
        with patch.object(guard.subprocess, "run") as runner:
            runner.return_value.returncode = 0
            self.assertTrue(guard.request_stop(self.database, "test deadline", self.run_id))
        command = runner.call_args.args[0]
        self.assertEqual(command[1:5], ["-m", "scripts.factory_registry.operator_cli", "stop", "--database"])
        self.assertEqual(command[-2:], ["--run-id", self.run_id])

    def test_successful_process_exit_without_authoritative_stop_is_not_success(self) -> None:
        self.enable()
        with patch.object(guard, "request_stop", return_value=True):
            record = self.run_guard(at=self.now + timedelta(hours=2))
        self.assertEqual(record["action"], "stop-unverified")
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")


class DeliveryGuardGrowthTests(unittest.TestCase):
    """Certify real registered pairs, not a mock permission to grow scope."""

    def setUp(self):
        self.fixture = delivery_fixtures.DeliveryRegistryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.fixture.submit()
        self.fixture.submit(self.fixture.brief("FEATURE-2"))
        self.fixture.authorize(("FEATURE-1", "FEATURE-2"))
        _, pair = self.fixture.plan_and_pair()
        self.fixture.register(pair)
        self.fixture.start()
        self.expected = self.fixture.registry.dispatch_control()["bounded_run"]
        self.spec = self.fixture.root / "guard-spec.json"
        self.spec.write_text(json.dumps(self.expected))
        self.state = self.fixture.root / "guard-state"
        self.state.mkdir()
        _, second = self.fixture.plan_and_pair(self.fixture.brief("FEATURE-2"),
            implementation_issue=3, action_id="plan-2", seconds=11)
        self.fixture.register(second, feature="FEATURE-2", action="plan-2", seconds=16)
        self.current = self.fixture.registry.dispatch_control()["bounded_run"]

    def guard(self, *, at=None):
        return guard.guard_once(self.fixture.database, self.spec, self.state, "run-1", "primary",
            now=at or self.fixture.now + timedelta(seconds=20))

    def corrupt_scope(self, scope):
        # Disposable test corruption exercises the independent guard against
        # state that the normal registration commands would never authorize.
        with sqlite3.connect(self.fixture.database) as connection:
            connection.execute("UPDATE registry_metadata SET value=? WHERE key='bounded_run_scope'",
                               (json.dumps(scope),))

    def test_certified_monotonic_pair_growth_is_healthy_without_changing_deadline(self):
        before = self.fixture.revision()
        with patch.object(guard, "request_stop") as stopper:
            result = self.guard()
        self.assertEqual(result["action"], "observe")
        self.assertTrue(result["scope_matches"])
        self.assertEqual(result["deadline"], self.expected["deadline"])
        self.assertEqual(result["registry_revision"], before)
        self.assertEqual(self.fixture.revision(), before)
        self.assertEqual(self.current["package_ids"], ["TASK-1", "TASK-2", "TASK-3", "TASK-4"])
        stopper.assert_not_called()

    def test_uncertified_addition_deletion_and_changed_envelope_fail_closed(self):
        for mutation in (
            {"package_ids": [*self.current["package_ids"], "TASK-999"]},
            {"package_ids": ["TASK-2", "TASK-3", "TASK-4"]},
            {"deadline": self.fixture.stamp(7200)},
            {"base_ref": "codex/other"},
            {"parent_limit": 1},
        ):
            with self.subTest(mutation=mutation):
                self.corrupt_scope({**self.current, **mutation})
                with patch.object(guard, "request_stop", return_value=False) as stopper:
                    result = self.guard()
                self.assertFalse(result["scope_matches"])
                self.assertEqual(result["reason"], "authoritative bounded run scope mismatch")
                self.assertEqual(result["action"], "stop-failed")
                self.assertEqual(stopper.call_args.args[2], "run-1")

    def test_every_actual_package_must_be_certified_including_baseline(self):
        expected = {**self.expected, "package_ids": [*self.expected["package_ids"], "TASK-999"]}
        self.spec.write_text(json.dumps(expected))
        self.corrupt_scope({**self.current, "package_ids": [*self.current["package_ids"], "TASK-999"]})
        with patch.object(guard, "request_stop", return_value=False):
            self.assertEqual(self.guard()["action"], "stop-failed")

    def test_stale_authority_snapshot_is_not_a_scope_certificate(self):
        observed = guard.read_authority(self.fixture.database)
        observed["scope"] = {**self.current, "package_ids": ["TASK-1", "TASK-2", "TASK-3"]}
        with patch.object(guard, "read_authority", return_value=observed), \
                patch.object(guard, "request_stop", return_value=False):
            result = self.guard()
        self.assertEqual(result["action"], "stop-failed")
        self.assertFalse(result["scope_matches"])

    def test_certification_failure_does_not_create_missing_database(self):
        self.fixture.database.unlink()
        self.assertFalse(guard._scope_matches(self.fixture.database, self.expected, self.current))
        self.assertFalse(self.fixture.database.exists())

    def test_certified_growth_still_stops_at_original_deadline(self):
        with patch.object(guard, "request_stop", side_effect=lambda db, why, run_id: (
            stop(db, why, expected_run_id=run_id) and True
        )):
            result = self.guard(at=self.fixture.now + timedelta(seconds=3601))
        self.assertEqual(result["action"], "stop-requested")
        self.assertEqual(result["reason"], "authoritative bounded run deadline reached")
        self.assertEqual(self.fixture.registry.dispatch_control()["dispatch_mode"], "STOPPING")


if __name__ == "__main__":
    unittest.main()
