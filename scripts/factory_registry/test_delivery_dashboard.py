"""Read-only local dashboard evidence for continuous delivery."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

# The existing dashboard also supports direct execution from scripts/runner.
_RUNNER = str(Path(__file__).resolve().parents[1] / "runner")
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

from scripts.runner import factory_dashboard as dashboard
from scripts.factory_registry import test_delivery_registry as fixtures


class DeliveryDashboardTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.DeliveryRegistryTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.registry = self.fx.registry
        self.config = {"registry_database": str(self.fx.database), "agents": {
            "codex-b": {"command": ["PRIVATE_COMMAND_CANARY"], "env": {"TOKEN": "PRIVATE_ENV_CANARY"}},
        }}

    def report(self, seconds=7):
        before = self.registry.dispatch_control()
        result = dashboard.load_registry_report(self.config, self.fx.stamp(seconds))
        self.assertEqual(self.registry.dispatch_control(), before, "dashboard reads must not mutate authority")
        self.assertTrue(result["available"], result)
        self.assertEqual(result["projection"]["registryRevision"], str(result["control"]["revision"]))
        return result

    def prepared_pair(self):
        self.fx.submit()
        self.fx.authorize()
        plan, pair = self.fx.plan_and_pair(action_id=None)
        self.registry.reserve_delivery_action("run-1", "FEATURE-1", "plan-1", "PLAN", {
            "generation": 0, "base_commit": self.fx.base, "prompt": "PRIVATE_PROMPT_CANARY",
            "environment": {"TOKEN": "PRIVATE_ENV_CANARY"},
        }, owner="orchestra", expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(1))
        self.registry.update_delivery_action("plan-1", owner="orchestra", state="SUCCEEDED", result={
            "plan": plan.as_dict(), "raw_diagnostics": "PRIVATE_DIAGNOSTICS_CANARY",
            "logs": "/private/host/PRIVATE_LOG_PATH_CANARY",
        }, expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(5))
        return pair

    def test_delivery_summary_tracks_real_registration_review_and_integration(self):
        pair = self.prepared_pair()
        self.assertEqual(self.report()["delivery"][0]["next_action"], "PROJECT")
        self.fx.register(pair)
        first = self.report()
        self.assertEqual(first["delivery"], [{
            "feature_id": "FEATURE-1", "title": "User feature FEATURE-1", "next_action": "WAIT_IMPLEMENTATION",
            "reason": None, "implementation_id": "TASK-1", "review_id": "TASK-2", "integration_commit": None,
        }])
        review_input, ci = self.fx.finish_implementation(pair)
        waiting = self.report(seconds=21)
        self.assertEqual(waiting["delivery"][0]["next_action"], "PUBLISH_REVIEW")
        self.assertEqual(waiting["control"]["dispatch_mode"], "LIVE")
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(25))
        self.assertEqual(self.report(seconds=26)["delivery"][0]["next_action"], "WAIT_REVIEW")
        self.fx.finish_review(review_input)
        self.assertEqual(self.report(seconds=43)["delivery"][0]["next_action"], "INTEGRATE")
        candidate, publication, _, _ = self.fx.publish_candidate()
        self.registry.record_delivery_integration("run-1", "FEATURE-1", "integrate-1", publication,
            expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(46))
        completed = self.report(seconds=47)
        self.assertEqual(completed["delivery"][0]["next_action"], "COMPLETE")
        self.assertEqual(completed["delivery"][0]["integration_commit"], candidate["target_after"])

    def test_owner_intake_and_blocked_dependency_are_visible_before_registration(self):
        self.fx.submit()
        self.fx.submit(self.fx.brief("FEATURE-2", ("FEATURE-1",)))
        self.fx.authorize(("FEATURE-1", "FEATURE-2"))
        rows = {row["feature_id"]: row for row in self.report()["delivery"]}
        self.assertEqual(rows["FEATURE-1"]["next_action"], "PLAN")
        self.assertEqual(rows["FEATURE-2"]["next_action"], "WAIT_DEPENDENCIES")
        self.assertIsNone(rows["FEATURE-1"]["implementation_id"])
        self.assertIsNone(rows["FEATURE-2"]["review_id"])

    def test_delivery_rows_do_not_expose_prompts_environment_logs_or_raw_action_diagnostics(self):
        pair = self.prepared_pair()
        self.fx.register(pair)
        result = self.report()
        serialized = json.dumps(result)
        for forbidden in ("PRIVATE_PROMPT_CANARY", "PRIVATE_ENV_CANARY", "PRIVATE_COMMAND_CANARY",
                          "PRIVATE_DIAGNOSTICS_CANARY", "PRIVATE_LOG_PATH_CANARY", str(self.fx.database)):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(set(result["delivery"][0]), {
            "feature_id", "title", "next_action", "reason", "implementation_id", "review_id", "integration_commit",
        })

    def test_raw_delivery_failure_details_are_sanitized_not_copied_to_dashboard(self):
        self.fx.submit()
        self.fx.authorize()
        original = self.registry.delivery_snapshot(run_id="run-1")
        for raw in ("provider failed: token=PRIVATE_TOKEN_CANARY /private/host/PRIVATE_LOG_PATH_CANARY",
                    "PRIVATE_TOKEN_CANARY"):
            with self.subTest(raw=raw):
                row = {**original["features"][0], "next_action": "BLOCKED", "reason": raw}
                poisoned = {**original, "features": [row], "records": {
                    "raw_prompt": "PRIVATE_PROMPT_CANARY", "env": {"token": "PRIVATE_ENV_CANARY"},
                }}
                with patch.object(dashboard.SQLiteRegistry, "delivery_snapshot", return_value=poisoned):
                    result = self.report()
                self.assertEqual(result["delivery"][0]["next_action"], "BLOCKED")
                self.assertIsNotNone(result["delivery"][0]["reason"])
                serialized = json.dumps(result)
                for forbidden in ("PRIVATE_TOKEN_CANARY", "PRIVATE_LOG_PATH_CANARY", "PRIVATE_PROMPT_CANARY", "PRIVATE_ENV_CANARY"):
                    self.assertNotIn(forbidden, serialized)

    def test_known_delivery_blocker_code_remains_observable(self):
        self.fx.submit()
        original = self.registry.delivery_snapshot()
        code = "DELIVERY_GENERATION_BUDGET_EXHAUSTED"
        row = {**original["features"][0], "next_action": "BLOCKED", "reason": code}
        with patch.object(dashboard.SQLiteRegistry, "delivery_snapshot", return_value={**original, "features": [row]}):
            result = self.report()
        self.assertEqual(result["delivery"][0]["reason"], code)

    def test_delivery_revision_drift_fails_closed_without_showing_mixed_state(self):
        self.fx.submit()
        original = self.registry.delivery_snapshot()
        with patch.object(dashboard.SQLiteRegistry, "delivery_snapshot",
                          return_value={**original, "revision": original["revision"] + 1}):
            result = dashboard.load_registry_report(self.config, self.fx.stamp(7))
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "authoritative Registry observation failed")
        self.assertIsNone(result["projection"])
        self.assertIsNone(result["control"])
        self.assertNotIn("delivery", result)

    def test_projection_revision_drift_fails_closed_before_reading_delivery(self):
        self.fx.submit()
        projection = dashboard.build_control_center_projection(self.registry, observed_at=self.fx.stamp(7))
        projection["registryRevision"] = str(int(projection["registryRevision"]) + 1)
        with patch.object(dashboard, "build_control_center_projection", return_value=projection), \
                patch.object(dashboard.SQLiteRegistry, "delivery_snapshot") as lookup:
            result = dashboard.load_registry_report(self.config, self.fx.stamp(7))
        self.assertFalse(result["available"])
        lookup.assert_not_called()
        self.assertIsNone(result["projection"])

    def test_unavailable_delivery_reader_is_degraded_not_empty_or_leaking_exception(self):
        with patch.object(dashboard.SQLiteRegistry, "delivery_snapshot",
                          side_effect=RuntimeError("PRIVATE_TOKEN_CANARY at /private/host/database")):
            result = dashboard.load_registry_report(self.config, self.fx.stamp(7))
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "authoritative Registry observation failed")
        self.assertNotIn("delivery", result)
        self.assertNotIn("PRIVATE_TOKEN_CANARY", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
