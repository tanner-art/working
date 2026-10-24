"""A full rejected/corrected feature and dependent successor reach integration.

Registry transactions, path ownership, Git commits, correction materialization,
review packets and integration publication are real. Provider decisions and the
GitHub transport use the existing deterministic coordinator fixture.
"""
from __future__ import annotations

import hashlib
import json
import unittest

from scripts.factory_registry import test_delivery_coordinator as fixtures
from scripts.factory_registry.delivery_plan import FeatureBrief, build_packages, validate_plan
from scripts.factory_registry.delivery_repair import materialize_correction
from scripts.factory_registry.models import Evidence, ReviewInput, ReviewOutcome, ReviewOutcomeState, TaskStatus


class DeliveryFullCycleTests(unittest.TestCase):
    def setUp(self):
        self.loop = fixtures.DeliveryCoordinatorTests()
        self.loop.setUp()
        self.addCleanup(self.loop.doCleanups)
        self.fx = self.loop.fx
        self.registry = self.loop.registry

    def pair(self, feature_id):
        snapshot = self.registry.delivery_snapshot(run_id="run-1")
        feature = next(row for row in snapshot["features"] if row["feature_id"] == feature_id)
        registered = feature["pair"]
        plan_data = snapshot["records"]["action:" + registered["plan_action_id"]]["checkpoint"]["plan"]
        brief = FeatureBrief.from_dict(feature["brief"])
        plan = validate_plan(plan_data, brief=brief, repository=self.fx.repository, target_ref="codex/delivery")
        dependencies = {dep: snapshot["records"]["integration:" + dep]["package_id"] for dep in brief.dependency_feature_ids}
        return build_packages(plan, repository=self.fx.repository, target_ref="codex/delivery",
            implementation_issue=int(registered["implementation_id"].split("-")[1]),
            review_issue=int(registered["review_id"].split("-")[1]), dependency_packages=dependencies)

    def tick(self, seconds):
        result = self.loop.tick(seconds=seconds)
        self.assertTrue(all(row["state"] == "OBSERVED" for row in result["results"]), result)
        return result

    def implement(self, pair, seconds, *, correction=False):
        package_id, review_id = pair.implementation.id, pair.review.id
        base = pair.implementation.provider_diagnostics["readiness_proof"]["base_commit"]
        attempt_id = "implementation-" + package_id
        self.registry.acquire_lease(package_id, "builder", acquired_at=self.fx.stamp(seconds), expires_at=self.fx.stamp(seconds + 200))
        self.registry.begin_attempt_runtime(attempt_id, package_id=package_id, worker_id="builder",
            runner_pid=12345, started_at=self.fx.stamp(seconds + 1), expected_revision=self.fx.revision())
        branch = "codex/implementation-" + package_id.lower()
        self.fx.git("checkout", "-b", branch, base)
        if correction:
            binding = self.registry.delivery_repair_binding(package_id)
            applied = materialize_correction(self.fx.repository, base, binding,
                                            pair.implementation.provider_diagnostics["exclusive_paths"])
            self.assertEqual(applied["state"], "APPLIED")
            self.assertIn("saved thought", (self.fx.repository / "src/thoughtDisplay.tsx").read_text())
            (self.fx.repository / "src/App.tsx").write_text(
                "export const App = () => <button>saved thought</button>\n")
        else:
            self.assertIn("saved thought", (self.fx.repository / "src/App.tsx").read_text())
            (self.fx.repository / "src/childDisplay.tsx").write_text(
                "export const ChildDisplay = () => 'dependent thought'\n")
            (self.fx.repository / "src/childDisplay.test.tsx").write_text(
                "// Fixture validation: dependent thought remains visible.\n")
            (self.fx.repository / "src/App.tsx").write_text(
                "export const App = () => <><button>saved thought</button><span>dependent thought</span></>\n")
        self.fx.git("add", ".")
        self.fx.git("commit", "-m", "simulated worker implementation " + package_id)
        implementation = self.fx.git("rev-parse", "HEAD")
        self.fx.git("push", "origin", branch)
        packet = self.fx.root / ("review-packet-" + package_id)
        packet.mkdir()
        contents = {
            "base-to-implementation.diff": self.fx.git("diff", base, implementation).encode(),
            "changed-files.txt": self.fx.git("diff", "--name-only", base, implementation).encode(),
            "contract.json": json.dumps(pair.implementation_contract, sort_keys=True).encode(),
            "validation-evidence.json": b'{"fixture_validation":"passed"}',
        }
        hashes = {}
        for name, content in contents.items():
            (packet / name).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        manifest = {"schema_version": 1, "implementation_attempt_id": attempt_id,
                    "implementation_commit": implementation, "base_commit": base, "files": hashes}
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        (packet / "manifest.json").write_bytes(manifest_bytes)
        review_input = ReviewInput(id="input-" + review_id, review_package_id=review_id, target_package_id=package_id,
            implementation_attempt_id=attempt_id, implementation_commit=implementation, base_commit=base,
            pr_url="https://github.com/example/app/pull/" + package_id.split("-")[1],
            contract_sha256=pair.implementation.provider_diagnostics["queue_contract_sha256"],
            contract=pair.implementation_contract, validation_evidence={"review_packet": {
                "path": str(packet), "files": hashes, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}},
            recorded_at=self.fx.stamp(seconds + 5))
        self.registry.finish_attempt_runtime(attempt_id, ended_at=self.fx.stamp(seconds + 5),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="simulated worker completed",
            review_inputs=(review_input,))
        self.loop.github.green(review_input)
        return review_input

    def approve(self, packet, seconds):
        review_id = packet.review_package_id
        attempt_id, evidence_id = "review-" + review_id, "evidence-" + review_id
        self.registry.acquire_lease(review_id, "reviewer", acquired_at=self.fx.stamp(seconds), expires_at=self.fx.stamp(seconds + 200))
        self.registry.begin_attempt_runtime(attempt_id, package_id=review_id, worker_id="reviewer",
            runner_pid=12346, started_at=self.fx.stamp(seconds + 1), expected_revision=self.fx.revision())
        self.registry.finish_attempt_runtime(attempt_id, ended_at=self.fx.stamp(seconds + 2), outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW, reason="simulated independent review completed")
        outcome = ReviewOutcome(id="verdict-" + review_id, review_package_id=review_id, target_package_id=packet.target_package_id,
            implementer_worker_id="builder", reviewer_worker_id="reviewer", requested_at=packet.recorded_at,
            decided_at=self.fx.stamp(seconds + 4), state=ReviewOutcomeState.APPROVED,
            findings=("Exact corrected behavior and acceptance contract reviewed",), changes_requested=(),
            approval_evidence_ids=(evidence_id,), reviewed_commit=packet.implementation_commit,
            reviewed_base_commit=packet.base_commit, contract_sha256=packet.contract_sha256,
            review_input_evidence_id=packet.id, reviewer_attempt_id=attempt_id)
        evidence = Evidence(evidence_id, review_id, "review", packet.pr_url, "Exact independent approval",
            self.fx.stamp(seconds + 3), {"attempt_id": attempt_id, "reviewed_commit": packet.implementation_commit,
                "reviewed_base_commit": packet.base_commit, "contract_sha256": packet.contract_sha256,
                "review_input_evidence_id": packet.id})
        self.registry.record_review_outcome(outcome, evidence=evidence, expected_revision=self.fx.revision())

    def test_rejected_feature_is_corrected_then_both_it_and_its_successor_are_integrated(self):
        self.loop.authorize(dependent=True)
        original_requests = {key: value for key, value in self.registry.delivery_snapshot()["records"].items()
                             if key.startswith("request:")}
        self.tick(1)
        self.tick(2)
        rejected = self.loop.implement()
        self.tick(25)
        self.fx.finish_review(rejected, verdict=ReviewOutcomeState.CHANGES_REQUESTED)
        original_target = self.loop.remote_sha()
        before = self.registry.delivery_snapshot(run_id="run-1")
        self.assertEqual(before["features"][1]["next_action"], "WAIT_DEPENDENCIES")
        rejected_outcome = before["features"][0]["review_outcome"]

        self.tick(50)
        self.tick(51)
        correction = self.pair("FEATURE-1")
        self.assertEqual((correction.implementation.id, correction.review.id), ("TASK-3", "TASK-4"))
        self.assertEqual(self.loop.remote_sha(), original_target)
        corrected = self.implement(correction, 60, correction=True)
        self.tick(70)
        self.approve(corrected, 80)
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][1]["next_action"], "WAIT_DEPENDENCIES")
        self.tick(90)
        first = self.registry.delivery_snapshot(run_id="run-1")["features"][0]
        self.assertEqual(first["next_action"], "COMPLETE")
        self.assertEqual(first["integration"]["implementation_commit"], corrected.implementation_commit)
        self.tick(91)

        successor = self.pair("FEATURE-2")
        self.assertEqual((successor.implementation.id, successor.review.id), ("TASK-5", "TASK-6"))
        self.assertEqual(successor.implementation.dependency_ids, ("TASK-3",))
        self.assertEqual(successor.implementation.provider_diagnostics["readiness_proof"]["base_commit"],
                         first["integration"]["integration_commit"])
        child = self.implement(successor, 100)
        self.tick(110)
        self.approve(child, 120)
        self.tick(130)

        final = self.registry.delivery_snapshot(run_id="run-1")
        self.assertEqual([row["next_action"] for row in final["features"]], ["COMPLETE", "COMPLETE"])
        self.assertEqual(self.loop.remote_sha(), final["features"][1]["integration"]["integration_commit"])
        content = self.fx.git("show", self.loop.remote_sha() + ":src/App.tsx")
        self.assertIn("saved thought", content)
        self.assertIn("dependent thought", content)
        self.assertEqual({key: value for key, value in final["records"].items() if key.startswith("request:")}, original_requests)
        review_rows = self.registry.control_center_snapshot(observed_at=self.fx.stamp(131)).review_outcomes
        self.assertEqual(len(review_rows), 3)
        self.assertEqual(next(row for row in review_rows if row["id"] == rejected_outcome["id"])["state"], "CHANGES_REQUESTED")
        self.assertEqual(sum(row["state"] == "APPROVED" for row in review_rows), 2)
        self.assertEqual(len(self.loop.planner_calls), 3)
        self.assertEqual(len(self.loop.github.issues), 6)
        self.assertEqual(set(self.registry.dispatch_control()["bounded_run"]["package_ids"]),
                         {"TASK-1", "TASK-2", "TASK-3", "TASK-4", "TASK-5", "TASK-6"})
        self.fx.stop(seconds=140)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")
        self.assertTrue(self.registry.dispatch_control()["kill_switch_engaged"])
        self.assertFalse(self.registry.active_attempt_runtimes())
        self.assertFalse(self.registry.active_unbound_leases())
        self.assertFalse(self.registry.runtime_orphans(observed_at=self.fx.stamp(142)))


if __name__ == "__main__":
    unittest.main()
