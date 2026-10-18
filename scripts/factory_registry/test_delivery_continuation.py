"""Adversarial restart tests: no worker scope is not unrestricted authority."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.factory_registry import bounded_run_guard
from scripts.factory_registry import test_delivery_coordinator as fixtures
from scripts.factory_registry.models import ReviewOutcomeState
from scripts.factory_registry.operator import coordinator_continuation_gate, OperatorError
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.shadow_dispatch import decide_shadow
from scripts.factory_registry.test_shadow_dispatch import package, snapshot, worker
from scripts.runner.registry_control import scope_dispatch_snapshot


class DeliveryContinuationTests(unittest.TestCase):
    def setUp(self):
        self.loop = fixtures.DeliveryCoordinatorTests()
        self.loop.setUp()
        self.addCleanup(self.loop.doCleanups)
        self.fx, self.registry = self.loop.fx, self.loop.registry

    def approved_stop(self, *, dependent=False, verdict=ReviewOutcomeState.APPROVED):
        self.loop.authorize(dependent=dependent)
        self.loop.tick(seconds=1)
        self.loop.tick(seconds=2)
        source = self.loop.implement()
        self.loop.tick(seconds=25)
        self.fx.finish_review(source, verdict=verdict)
        self.fx.stop()
        self.fx.authorize(features=("FEATURE-1", "FEATURE-2") if dependent else ("FEATURE-1",),
                          run_id="run-2", seconds=52)
        self.scope = {"run_id": "run-2", "package_ids": [], "deadline": self.fx.stamp(3600),
                      "base_ref": "codex/delivery", "parent_limit": 2}
        self.loop.coordinator.run_id = "run-2"
        return source

    def preflight(self):
        return self.registry.delivery_activation_preflight(self.scope, observed_at=self.fx.stamp(53))

    def test_real_integration_after_restart_unlocks_and_certifies_successor(self):
        source = self.approved_stop(dependent=True)
        before = self.fx.revision()
        certificate = self.preflight()
        self.assertEqual(self.fx.revision(), before)
        self.assertEqual(certificate["approved_bindings"][0]["implementation_commit"], source.implementation_commit)
        self.fx.start(run="run-2", package_ids=[], seconds=54)
        baseline = self.registry.dispatch_control()["bounded_run"]
        self.assertTrue(bounded_run_guard._scope_matches(self.fx.database, baseline, baseline))
        self.loop.tick(seconds=55)
        self.loop.tick(seconds=56)
        snapshot = self.registry.delivery_snapshot(run_id="run-2")
        self.assertEqual(snapshot["features"][0]["next_action"], "COMPLETE")
        self.assertEqual(snapshot["features"][1]["implementation_status"], "READY")
        current = self.registry.dispatch_control()["bounded_run"]
        self.assertEqual(set(current["package_ids"]), {"TASK-3", "TASK-4"})
        self.assertTrue(bounded_run_guard._scope_matches(self.fx.database, baseline, current))
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, baseline,
            {**current, "package_ids": current["package_ids"] + ["TASK-999"]}))
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, baseline,
            {**current, "deadline": self.fx.stamp(7200)}))
        stored = snapshot["records"]["run-state:run-2"]["continuation_certificate"]
        self.assertEqual(stored, certificate)
        self.fx.stop(seconds=60)
        self.assertFalse(self.registry.active_attempt_runtimes())
        self.assertFalse(self.registry.active_unbound_leases())

    def test_unknown_run_empty_scope_is_rejected_atomically(self):
        before = self.fx.revision()
        with self.assertRaisesRegex(RegistryConflict, "CONTINUATION_NOT_AUTHORIZED"):
            self.fx.start(run="unknown-run", package_ids=[])
        self.assertEqual(self.fx.revision(), before)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_rejection_is_not_a_continuation_approval(self):
        self.approved_stop(verdict=ReviewOutcomeState.CHANGES_REQUESTED)
        with self.assertRaisesRegex(RegistryConflict, "CONTINUATION_NOT_AUTHORIZED"):
            self.preflight()
        with self.assertRaises(RegistryConflict):
            self.fx.start(run="run-2", package_ids=[], seconds=54)

    def test_missing_packet_or_expired_authorization_fails_before_live(self):
        source = self.approved_stop()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTIVATION_INVALID"):
            self.registry.delivery_activation_preflight(self.scope, observed_at=self.fx.stamp(3600))
        Path(source.validation_evidence["review_packet"]["path"], "contract.json").unlink()
        with self.assertRaises(RegistryConflict):
            self.fx.start(run="run-2", package_ids=[], seconds=54)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_uncertified_empty_scope_never_satisfies_guard(self):
        self.approved_stop()
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, self.scope, self.scope))

    def test_empty_worker_scope_hides_even_unrelated_ready_packages(self):
        self.approved_stop()
        self.fx.start(run="run-2", package_ids=[], seconds=54)
        with self.registry._connection() as connection:
            for package_id in ("TASK-1", "TASK-2", "TASK-999"):
                with self.subTest(package_id=package_id), self.assertRaisesRegex(RegistryConflict, "RUN_PACKAGE_NOT_ALLOWLISTED"):
                    self.registry._assert_scope_membership(connection, package_id, self.fx.stamp(55))
        dispatch = snapshot(packages=(package("TASK-999", capabilities=("implementation",)),),
                            workers=(worker("builder", capabilities=("implementation",)),))
        scoped = scope_dispatch_snapshot(dispatch, [], 2)
        self.assertFalse(decide_shadow(scoped).proposed_assignments)

    def test_unresolved_preparation_blocks_continuation(self):
        self.approved_stop()
        self.registry.reserve_delivery_action("run-2", "FEATURE-1", "pending-plan", "PLAN", {},
            owner="orchestra", expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(53))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTION_UNRESOLVED"):
            self.fx.start(run="run-2", package_ids=[], seconds=54)

    def test_failed_native_attempt_cannot_supply_continuation_certificate(self):
        self.approved_stop()
        with self.registry._connection() as connection:
            connection.execute("UPDATE attempts SET outcome='FAILED' WHERE id='review-attempt'")
        with self.assertRaisesRegex(RegistryConflict, "NATIVE_ATTEMPT_REQUIRED"):
            self.fx.start(run="run-2", package_ids=[], seconds=54)

    def test_certificate_corruption_and_changed_brief_fail_closed(self):
        self.approved_stop()
        self.fx.start(run="run-2", package_ids=[], seconds=54)
        scope = self.registry.dispatch_control()["bounded_run"]
        # Direct writes only in the isolated fault-injection fixture.
        with self.registry._connection() as connection:
            row = connection.execute("SELECT value FROM registry_metadata WHERE key='delivery:run-state:run-2'").fetchone()
            record = json.loads(row[0])
            record["continuation_certificate"]["approved_bindings"] = []
            connection.execute("UPDATE registry_metadata SET value=? WHERE key='delivery:run-state:run-2'", (json.dumps(record),))
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, scope, scope))
        self.fx.stop(seconds=55)
        self.fx.authorize(run_id="run-3", seconds=57)
        with self.registry._connection() as connection:
            row = connection.execute("SELECT value FROM registry_metadata WHERE key='delivery:request:FEATURE-1'").fetchone()
            record = json.loads(row[0])
            record["brief"]["user_experience"] = "Unapproved changed intent"
            connection.execute("UPDATE registry_metadata SET value=? WHERE key='delivery:request:FEATURE-1'", (json.dumps(record),))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_REQUEST_CHANGED"):
            self.fx.start(run="run-3", package_ids=[], seconds=58)

    def test_operator_requires_exact_service_and_fresh_coordinator_capacity(self):
        self.approved_stop()
        dispatch = self.registry.dispatch_snapshot(observed_at=self.fx.stamp(53))
        loader = "scripts.factory_registry.delivery_service.load_coordinator"
        with patch(loader, return_value=self.loop.coordinator) as load:
            result = coordinator_continuation_gate(self.registry, dispatch, self.scope, self.fx.root / "config.json")
            self.assertEqual(result["run_package_ids"], [])
            load.assert_called_once()
            self.loop.coordinator.run_id = "wrong-run"
            with self.assertRaisesRegex(OperatorError, "service binding mismatch"):
                coordinator_continuation_gate(self.registry, dispatch, self.scope, self.fx.root / "config.json")
            self.loop.coordinator.run_id = "run-2"
            for seconds, error in ((181, "HEARTBEAT_INVALID"), (1000, "CAPACITY_BLOCKED")):
                with self.subTest(seconds=seconds), self.assertRaisesRegex(OperatorError, error):
                    coordinator_continuation_gate(self.registry, replace(dispatch, observed_at=self.fx.stamp(seconds)),
                                                 self.scope, self.fx.root / "config.json")
            self.loop.telemetry(consumed=90, observed_seconds=53)
            with self.assertRaisesRegex(OperatorError, "CAPACITY_BLOCKED"):
                coordinator_continuation_gate(self.registry, self.registry.dispatch_snapshot(observed_at=self.fx.stamp(53)),
                                             self.scope, self.fx.root / "config.json")


if __name__ == "__main__":
    unittest.main()
