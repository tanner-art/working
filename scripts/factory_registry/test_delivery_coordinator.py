from __future__ import annotations

import json
from dataclasses import replace
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.factory_registry import test_delivery_registry as fixtures
from scripts.factory_registry.delivery_coordinator import DeliveryCoordinator, PlannerConfiguration
from scripts.factory_registry.delivery_integration import IntegrationPolicy
from scripts.factory_registry.delivery_plan import FeatureBrief, build_packages, validate_plan
from scripts.factory_registry.models import Lane, ReviewOutcomeState, Worker
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.sqlite_delivery import digest


class FakeGitHub:
    """Deterministic API boundary; Registry and Git underneath remain real."""
    repository = "example/app"

    def __init__(self):
        self.issues = {}
        self.contracts = {}
        self.next_issue = 1
        self.pr = {}
        self.runs = []
        self.requests = []

    def allocate_issue(self, marker, title, *, on_create, reconcile_only=False):
        if marker not in self.issues:
            if reconcile_only:
                raise AssertionError("A test may not invent a successful uncertain issue creation")
            on_create()
            self.issues[marker] = self.next_issue
            self.next_issue += 1
        return self.issues[marker]

    def update_contract(self, number, contract):
        self.contracts[number] = dict(contract)
        return {"contract_sha256": digest(contract)}

    def _request(self, argv):
        self.requests.append(list(argv))
        if argv[:2] == ["pr", "view"]:
            return dict(self.pr)
        if argv[:2] == ["run", "list"]:
            return list(self.runs)
        raise AssertionError("Unexpected fake GitHub operation: " + repr(argv))

    def green(self, review_input):
        self.pr = {"headRefOid": review_input.implementation_commit, "state": "OPEN"}
        self.runs = [{"headSha": review_input.implementation_commit, "status": "completed",
                      "conclusion": "success", "workflowName": "Validate app",
                      "url": "https://github.com/example/app/actions/runs/123",
                      "createdAt": "2026-10-16T12:00:21Z"}]


class DeliveryCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.DeliveryRegistryTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.registry = self.fx.registry
        self.repository = self.fx.repository
        self.remote = self.fx.root / "remote.git"
        self.fx.git("init", "--bare", str(self.remote))
        self.fx.git("remote", "add", "origin", str(self.remote))
        self.fx.git("push", "origin", "codex/delivery")
        self.github = FakeGitHub()
        self.seconds = 1
        self.planner_calls = []
        self.needs_decision = set()
        self.telemetry()
        self.policy = IntegrationPolicy(remote="origin", target_branch="codex/delivery",
            validation_commands=((sys.executable, "-c", "from pathlib import Path; "
                                  "assert Path('src/thoughtDisplay.tsx').exists()"),))
        self.coordinator = self.new_coordinator()

    def telemetry(self, *, consumed=10, observed_seconds=0, worker_pool="a" * 64, usage_pool="a" * 64):
        worker = Worker("orchestra", "Coordinator", ("coordination",), (Lane.FEATURE,), role="ORCHESTRA",
                        provider_diagnostics={"capacity_pool": worker_pool},
                        last_heartbeat_at=self.fx.stamp(observed_seconds), usage_state="GREEN")
        self.registry.sync_worker_telemetry(worker, [{
            "id": f"usage-{consumed}-{observed_seconds}", "worker_id": worker.id,
            "observed_at": self.fx.stamp(observed_seconds), "reset_at": self.fx.stamp(7200),
            "consumed_percent": consumed, "state": "GREEN", "capacity_scope": "default",
            "provider_diagnostics": {"capacity_pool": usage_pool},
        }], expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(observed_seconds))

    def new_coordinator(self):
        return DeliveryCoordinator(self.registry, repository=self.repository, run_id="run-1",
            state_directory=self.fx.root / "coordinator", github=self.github, integration=self.policy,
            planner=PlannerConfiguration(provider="openai", command=("fixture-only",), environment={}, worker_id="orchestra", capacity_pool="a" * 64),
            clock=lambda: self.fx.stamp(self.seconds), planner_runner=self.planner)

    def planner(self, **kwargs):
        self.planner_calls.append(kwargs["prompt"])
        kwargs["monitor"]()
        owner_json = kwargs["prompt"].split("OWNER_REQUEST_JSON\n", 1)[1].split("\n\n", 1)[0]
        brief = FeatureBrief.from_dict(json.loads(owner_json))
        if brief.id in self.needs_decision:
            result = {"state": "NEEDS_DECISION", "feature_id": brief.id,
                      "base_commit": self.fx.git("rev-parse", "refs/heads/codex/delivery"),
                      "user_experience": brief.user_experience,
                      "dependency_feature_ids": list(brief.dependency_feature_ids),
                      "decisions_needed": ["Choose whether this action deletes existing captures."], "package": None}
            kwargs["validate_result"](result)
            kwargs["on_result"](result, 0.25)
            return {"result": result}
        self.fx.base = self.fx.git("rev-parse", "refs/heads/codex/delivery")
        records = self.registry.delivery_snapshot()["records"]
        dependencies = {dep: records["integration:" + dep]["package_id"] for dep in brief.dependency_feature_ids}
        plan, _ = self.fx.plan_and_pair(brief, action_id=None, dependencies=dependencies, implementation_issue=100)
        kwargs["validate_result"](plan.as_dict())
        kwargs["on_result"](plan.as_dict(), 0.25)
        return {"result": plan.as_dict()}

    def authorize(self, *, dependent=False):
        self.fx.submit()
        features = ["FEATURE-1"]
        if dependent:
            self.fx.submit(self.fx.brief("FEATURE-2", ("FEATURE-1",)))
            features.append("FEATURE-2")
        self.fx.authorize(tuple(features))

    def tick(self, *, seconds=None, coordinator=None):
        if seconds is not None:
            self.seconds = seconds
        result = (coordinator or self.coordinator).tick()
        self.seconds += 1
        return result

    def pair(self):
        record = self.registry.delivery_snapshot(run_id="run-1")["features"][0]
        plan_data = self.registry.delivery_snapshot()["records"]["action:" + record["pair"]["plan_action_id"]]["checkpoint"]["plan"]
        plan = validate_plan(plan_data, brief=self.fx.brief(), repository=self.repository, target_ref="codex/delivery")
        return build_packages(plan, repository=self.repository, target_ref="codex/delivery", implementation_issue=1, review_issue=2)

    def implement(self):
        review_input, _ = self.fx.finish_implementation(self.pair())
        self.github.green(review_input)
        self.fx.git("push", "origin", "codex/implementation")
        return review_input

    def remote_sha(self):
        result = subprocess.run(["git", "--git-dir", str(self.remote), "rev-parse", "refs/heads/codex/delivery"],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def test_owner_request_plans_and_projects_a_real_ready_pair(self):
        self.authorize()
        first = self.tick()
        self.assertEqual(first["results"], [{"feature_id": "FEATURE-1", "action": "PLAN", "state": "OBSERVED"}])
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][0]["next_action"], "PROJECT")
        self.tick()
        packages = {row["id"]: row for row in self.registry.control_center_snapshot(observed_at=self.fx.stamp(3)).work_packages}
        self.assertEqual((packages["TASK-1"]["status"], packages["TASK-2"]["status"]), ("READY", "ON_DECK"))
        self.assertEqual(len(self.planner_calls), 1)
        self.assertEqual(set(self.github.contracts), {1, 2})
        self.assertIn(self.fx.brief().user_experience, self.github.contracts[1]["instructions"])
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_dependent_feature_waits_until_reviewed_parent_is_really_integrated(self):
        self.authorize(dependent=True)
        self.tick()
        self.tick()
        self.assertEqual(len(self.planner_calls), 1)
        review_input = self.implement()
        self.tick(seconds=25)
        self.fx.finish_review(review_input)
        self.assertNotEqual(self.remote_sha(), review_input.implementation_commit)
        rows = {row["feature_id"]: row for row in self.registry.delivery_snapshot(run_id="run-1")["features"]}
        self.assertEqual(rows["FEATURE-2"]["next_action"], "WAIT_DEPENDENCIES")
        result = self.tick(seconds=50)
        self.assertTrue(all(item["state"] == "OBSERVED" for item in result["results"]), result)
        rows = {row["feature_id"]: row for row in self.registry.delivery_snapshot(run_id="run-1")["features"]}
        self.assertEqual(rows["FEATURE-1"]["next_action"], "COMPLETE")
        self.assertEqual(rows["FEATURE-2"]["next_action"], "PROJECT")
        self.assertEqual(self.remote_sha(), rows["FEATURE-1"]["integration"]["integration_commit"])
        self.assertEqual(len(self.planner_calls), 2)
        self.tick()
        packages = {row["id"]: row for row in self.registry.control_center_snapshot(observed_at=self.fx.stamp(52)).work_packages}
        self.assertEqual(packages["TASK-3"]["status"], "READY")
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")

    def test_stale_plan_is_invalidated_and_replanned_before_issue_projection(self):
        self.authorize()
        self.tick()
        self.fx.advance_target()
        self.fx.git("push", "origin", "codex/delivery")
        result = self.tick()
        self.assertEqual(result["results"][0]["state"], "OBSERVED", result)
        self.assertFalse(self.github.issues)
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][0]["next_action"], "PLAN")
        self.tick()
        self.tick()
        self.assertEqual(len(self.planner_calls), 2)
        self.assertEqual(len(self.github.issues), 2)
        records = self.registry.delivery_snapshot()["records"]
        self.assertEqual(len([key for key in records if key.startswith("invalid-plan:")]), 1)

    def test_latest_failed_ci_blocks_review_despite_older_success(self):
        self.authorize()
        self.tick()
        self.tick()
        review_input = self.implement()
        self.github.runs.append({**self.github.runs[0], "createdAt": "2026-10-16T12:00:24Z", "conclusion": "failure"})
        result = self.tick(seconds=25)
        self.assertEqual(result["results"][0]["code"], "DELIVERY_CI_NOT_GREEN")
        packages = {row["id"]: row for row in self.registry.control_center_snapshot(observed_at=self.fx.stamp(26)).work_packages}
        self.assertEqual(packages["TASK-2"]["status"], "ON_DECK")
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")
        self.github.green(review_input)
        self.github.pr["headRefOid"] = self.fx.base
        result = self.tick()
        self.assertEqual(result["results"][0]["code"], "DELIVERY_PR_HEAD_CHANGED")

    def test_rejected_review_prepares_correction_without_integrating_it(self):
        self.authorize()
        self.tick()
        self.tick()
        review_input = self.implement()
        self.tick(seconds=25)
        self.fx.finish_review(review_input, verdict=ReviewOutcomeState.CHANGES_REQUESTED)
        before = self.remote_sha()
        result = self.tick(seconds=50)
        self.assertEqual(result["results"][0]["action"], "REPAIR")
        self.assertEqual(result["results"][0]["state"], "OBSERVED", result)
        self.assertIn("Wire the missing button", self.planner_calls[-1])
        self.tick()
        self.assertEqual(self.remote_sha(), before)
        self.assertEqual(self.registry.delivery_repair_binding("TASK-3")["implementation_commit"], review_input.implementation_commit)

    def test_waiting_live_run_refreshes_health_without_launching_a_planner(self):
        self.authorize()
        self.tick()
        self.tick()
        self.fx.start()
        with patch.object(self.coordinator, "health_refresh") as refresh:
            result = self.tick(seconds=11)
        refresh.assert_called_once_with()
        self.assertEqual(result["health"], {"state": "FRESH"})
        self.assertEqual(len(self.planner_calls), 1)

    def test_waiting_live_run_exposes_telemetry_failure_without_provider_work(self):
        self.authorize()
        self.tick()
        self.tick()
        self.fx.start()
        with patch.object(self.coordinator, "health_refresh", side_effect=RegistryConflict("DELIVERY_COORDINATOR_TELEMETRY_UNAVAILABLE")):
            result = self.tick(seconds=11)
        self.assertEqual(result["health"], {"state": "DEGRADED", "code": "DELIVERY_COORDINATOR_TELEMETRY_UNAVAILABLE"})
        self.assertEqual(len(self.planner_calls), 1)

    def test_expired_run_does_not_refresh_health(self):
        self.authorize()
        self.tick()
        self.tick()
        self.fx.start()
        with patch.object(self.coordinator, "health_refresh") as refresh:
            result = self.tick(seconds=10000)
        refresh.assert_not_called()
        self.assertNotIn("health", result)

    def test_reserve_exhausted_capacity_launches_no_planner(self):
        self.authorize()
        self.telemetry(consumed=85, observed_seconds=1)
        result = self.tick(seconds=2)
        self.assertEqual(result["results"][0]["code"], "DELIVERY_COORDINATOR_CAPACITY_BLOCKED")
        self.assertFalse(self.planner_calls)
        self.assertFalse([key for key in self.registry.delivery_snapshot()["records"] if key.startswith("action:")])
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_stopped_run_cannot_bootstrap_more_work(self):
        self.authorize()
        self.tick()
        self.tick()
        self.fx.start()
        self.registry.set_dispatch_control(expected_revision=self.fx.revision(), expected_mode="LIVE",
            new_mode="STOPPING", kill_switch_engaged=True, changed_at=self.fx.stamp(11), reason="owner stop")
        self.registry.set_dispatch_control(expected_revision=self.fx.revision(), expected_mode="STOPPING",
            new_mode="PAUSED", kill_switch_engaged=True, changed_at=self.fx.stamp(12), reason="drained")
        result = self.tick(seconds=13)
        self.assertEqual(result["results"][0]["code"], "DISPATCH_PAUSED")
        self.assertEqual(len(self.planner_calls), 1)
        self.assertEqual(len(self.github.issues), 2)

    def test_cas_retry_does_not_repeat_planner_invocation(self):
        self.authorize()
        original = self.registry.reserve_delivery_action
        raced = []
        def race(*args, **kwargs):
            if not raced:
                raced.append(True)
                self.registry.register_worker(Worker("concurrent-worker", "Concurrent observer", (), ()))
            return original(*args, **kwargs)
        with patch.object(self.registry, "reserve_delivery_action", side_effect=race):
            result = self.tick()
        self.assertEqual(result["results"][0]["state"], "OBSERVED", result)
        self.assertEqual(len(self.planner_calls), 1)
        self.assertEqual(len([key for key in self.registry.delivery_snapshot()["records"] if key.startswith("action:")]), 1)

    def test_crash_after_remote_publish_recovers_record_after_pause_without_another_push(self):
        self.authorize()
        self.tick()
        self.tick()
        review_input = self.implement()
        self.tick(seconds=25)
        self.fx.finish_review(review_input)
        before_remote = self.remote_sha()
        with patch.object(self.registry, "record_delivery_integration", side_effect=OSError("simulated recording interruption")):
            failed = self.tick(seconds=50)
        self.assertEqual(failed["results"][0]["state"], "BLOCKED")
        published = self.remote_sha()
        self.assertNotEqual(published, before_remote)
        feature = self.registry.delivery_snapshot(run_id="run-1")["features"][0]
        self.assertEqual(feature["next_action"], "RECONCILE_ACTION")
        self.assertEqual(feature["unresolved_actions"][0]["state"], "UNCERTAIN")
        self.registry.set_dispatch_control(expected_revision=self.fx.revision(), expected_mode="LIVE",
            new_mode="STOPPING", kill_switch_engaged=True, changed_at=self.fx.stamp(3600), reason="deadline")
        self.registry.set_dispatch_control(expected_revision=self.fx.revision(), expected_mode="STOPPING",
            new_mode="PAUSED", kill_switch_engaged=True, changed_at=self.fx.stamp(3601), reason="drained")
        restarted = self.new_coordinator()
        calls_before = len(self.github.requests)
        recovered = self.tick(seconds=3602, coordinator=restarted)
        self.assertEqual(recovered["results"][0]["state"], "OBSERVED", recovered)
        feature = self.registry.delivery_snapshot(run_id="run-1")["features"][0]
        self.assertEqual(feature["next_action"], "COMPLETE")
        self.assertEqual(feature["integration"]["publication"]["state"], "ALREADY_PUBLISHED")
        self.assertEqual(self.remote_sha(), published)
        self.assertEqual(len(self.github.requests), calls_before)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_feature_needing_owner_decision_does_not_stop_independent_preparation(self):
        self.fx.submit()
        self.fx.submit(self.fx.brief("FEATURE-2"))
        self.fx.authorize(("FEATURE-1", "FEATURE-2"))
        self.needs_decision.add("FEATURE-1")
        first = self.tick()
        self.assertTrue(all(item["state"] == "OBSERVED" for item in first["results"]), first)
        rows = {row["feature_id"]: row for row in self.registry.delivery_snapshot(run_id="run-1")["features"]}
        self.assertEqual(rows["FEATURE-1"]["next_action"], "NEEDS_DECISION")
        self.assertEqual(rows["FEATURE-2"]["next_action"], "PROJECT")
        self.tick()
        packages = self.registry.control_center_snapshot(observed_at=self.fx.stamp(3)).work_packages
        self.assertEqual({row["feature_id"] for row in packages}, {"FEATURE-2"})
        self.assertEqual(len(self.planner_calls), 2)

    def test_planner_account_pool_must_match_authoritative_coordinator(self):
        self.authorize()
        for value in (None, "not-an-account-binding", "b" * 64):
            with self.subTest(pool=value):
                self.coordinator.planner = replace(self.coordinator.planner, capacity_pool=value)
                result = self.tick()
                self.assertEqual(result["results"][0]["code"], "DELIVERY_COORDINATOR_ACCOUNT_UNBOUND")
        self.assertFalse(self.planner_calls)
        self.assertFalse(self.github.issues)
        self.assertFalse([key for key in self.registry.delivery_snapshot()["records"] if key.startswith("action:")])

    def test_fresh_usage_for_another_account_cannot_authorize_planner(self):
        self.authorize()
        self.telemetry(observed_seconds=1, usage_pool="b" * 64)
        result = self.tick(seconds=2)
        self.assertEqual(result["results"][0]["code"], "DELIVERY_COORDINATOR_CAPACITY_ACCOUNT_MISMATCH")
        self.assertFalse(self.planner_calls)
        self.assertFalse([key for key in self.registry.delivery_snapshot()["records"] if key.startswith("action:")])

    def test_stale_coordinator_heartbeat_blocks_planner_even_when_usage_is_fresh(self):
        self.authorize()
        result = self.tick(seconds=181)
        self.assertEqual(result["results"][0]["code"], "DELIVERY_COORDINATOR_HEARTBEAT_INVALID")
        self.assertFalse(self.planner_calls)
        self.assertFalse([key for key in self.registry.delivery_snapshot()["records"] if key.startswith("action:")])

    def test_exclusive_database_lock_prevents_second_tick_with_a_different_log_directory(self):
        self.authorize()
        second = self.new_coordinator()
        second.state = self.fx.root / "another-coordinator-directory"
        before = self.fx.revision()
        with self.coordinator._exclusive_service():
            with self.assertRaisesRegex(RegistryConflict, "DELIVERY_COORDINATOR_BUSY"):
                second.tick()
        self.assertEqual(self.fx.revision(), before)
        self.assertFalse(self.planner_calls)
        self.assertFalse(self.github.issues)
        result = second.tick()
        self.assertEqual(result["results"][0]["state"], "OBSERVED")
        self.assertEqual(len(self.planner_calls), 1)

    def test_review_pr_must_belong_to_the_exact_configured_repository_before_any_query(self):
        for url in ("https://github.com/another/app/pull/1", "https://github.com/example/app-other/pull/1",
                    "https://github.com/example/app/pull/1?token=private", "https://github.com/example/app/pull/0",
                    "https://evil.invalid/example/app/pull/1"):
            with self.subTest(url=url), self.assertRaisesRegex(RegistryConflict, "DELIVERY_REPOSITORY_MISMATCH"):
                self.coordinator._ci({"pr_url": url, "implementation_commit": "a" * 40})
        self.assertFalse(self.github.requests)

    def test_unknown_pr_or_ci_response_fails_as_an_operational_block_not_a_loop_crash(self):
        self.authorize()
        self.tick()
        self.tick()
        self.implement()
        valid_pr = dict(self.github.pr)
        valid_run = dict(self.github.runs[0])
        responses = (
            [None], [[]], ["not structured"],
            [valid_pr, None], [valid_pr, {"unexpected": "shape"}],
            [valid_pr, [{key: value for key, value in valid_run.items() if key != "url"}]],
            [valid_pr, [{**valid_run, "url": "https://github.com/another/app/actions/runs/123"}]],
            [valid_pr, [valid_run, {**valid_run, "createdAt": None}]],
        )
        for responses_for_case in responses:
            with self.subTest(response=responses_for_case):
                with patch.object(self.github, "_request", side_effect=responses_for_case):
                    result = self.tick(seconds=25)
                self.assertEqual(result["results"][0]["state"], "BLOCKED")
                statuses = {row["id"]: row["status"] for row in self.registry.control_center_snapshot(observed_at=self.fx.stamp(26)).work_packages}
                self.assertEqual(statuses["TASK-2"], "ON_DECK")
        self.assertEqual(len(self.planner_calls), 1)
        self.assertFalse(self.registry.control_center_snapshot(observed_at=self.fx.stamp(26)).review_outcomes)


if __name__ == "__main__":
    unittest.main()
