"""Stage-A bounded review progression against the real Registry adapter."""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from registry_control import RunnerRegistryControl, queue_contract_digest
from runner import materialize_review_packet
from task_readiness import check_packet, registration_proof
from scripts.factory_registry.models import (
    Feature, Lane, PackageKind, ReviewInput, TaskStatus, Worker, WorkPackage,
)
from scripts.factory_registry.operator import bounded_run_worker_gate
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.sqlite_registry import SQLiteRegistry


class BoundedReviewProgressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for name in ("docs/PLAN.md", "src/implementation.py", "tests/test_implementation.py",
                     "docs/REVIEW.md", "src/second.py", "tests/test_second.py",
                     "docs/SECOND_REVIEW.md"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "base"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "branch", "-M", "main"], check=True)
        self.base = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True,
        ).strip()
        # Terminal fixture events must not sit in the scheduler's future.
        self.now = (datetime.now(timezone.utc) - timedelta(seconds=10)).replace(microsecond=0)
        self.registry = SQLiteRegistry(self.root / "registry.sqlite")
        self.registry.initialize()
        self.registry.register_feature(Feature("F", "Bounded pair", 10, TaskStatus.READY))
        for worker in (
            Worker("builder", "Builder", ("code",), (Lane.PLATFORM,),
                   last_heartbeat_at=self.now.isoformat(), usage_state="NORMAL",
                   provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["builder"]}),
            Worker("reviewer", "Reviewer", ("independent-review",), (Lane.ASSURANCE,),
                   last_heartbeat_at=self.now.isoformat(), usage_state="NORMAL",
                   provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["reviewer"]}),
            Worker("orchestra", "Orchestra", (), (), role="ORCHESTRA",
                   last_heartbeat_at=self.now.isoformat(), usage_state="NORMAL",
                   provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["orchestra"]}),
        ):
            self.registry.register_worker(worker)
            self.registry.record_worker_capacity_observations(worker.id, ({
                "id": f"usage-{worker.id}", "worker_id": worker.id,
                "observed_at": self.now.isoformat(), "reset_at": None,
                "consumed_percent": 10, "state": "NORMAL",
                "provider_diagnostics": {"capacity_mode": "percentage", "capacity_scope": worker.id},
            },), recorded_at=self.now.isoformat())
        self.implementation = self.contract(1, kind="PARENT", paths=[
            "src/implementation.py", "tests/test_implementation.py",
        ], dependencies=[])
        self.review = self.contract(2, kind="REVIEW", paths=["docs/REVIEW.md"],
                                    dependencies=[1])
        self.register("TASK-1", self.implementation, TaskStatus.READY, PackageKind.PARENT,
                      Lane.PLATFORM, ("code",), ())
        self.register("TASK-2", self.review, TaskStatus.ON_DECK, PackageKind.REVIEW,
                      Lane.ASSURANCE, ("independent-review",), ("TASK-1",))
        self.control = RunnerRegistryControl(self.root / "registry.sqlite", self.repo)

    def contract(self, number, *, kind, paths, dependencies):
        return {
            "schema_version": 2, "task": f"TASK-{number}",
            "instructions": f"Deliver the exact {kind.lower()} packet.",
            "paths": paths, "depends_on": dependencies,
            "lane": "ASSURANCE" if kind == "REVIEW" else "PLATFORM",
            "kind": kind, "capacity_size": "VERY_SMALL", "capacity_risk": "BOUNDED",
            "readiness": {
                "base_commit": self.base, "planning_paths": ["docs/PLAN.md"],
                "existing_paths": paths, "new_paths": [],
                "integration_paths": [paths[0]], "test_paths": [paths[-1]],
                "dependency_kinds": {f"TASK-{item}": "coding" for item in dependencies},
            },
        }

    def register(self, task_id, contract, status, kind, lane, capabilities, dependencies):
        proof = registration_proof(contract, repository=self.repo, target_ref="main",
                                   acceptance_criteria=("exact result",))
        package = WorkPackage(
            task_id, "F", task_id, "OPERATIONS", lane, capabilities, 10,
            ("exact result",), status=status, kind=kind, dependency_ids=dependencies,
            provider_diagnostics={
                "readiness_schema_version": 2,
                "queue_contract_sha256": queue_contract_digest(contract),
                "readiness_proof": proof, "exclusive_paths": contract["paths"],
            },
        )
        self.registry.register_work_package(package)
        self.registry.bind_legacy_package_source(
            task_id, github_issue=int(task_id.removeprefix("TASK-")),
            queue_contract=contract,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=self.now.isoformat(),
        )

    def activate(self, ids=("TASK-1", "TASK-2")):
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.now.isoformat(), reason="stage A test",
            bounded_run={"run_id": "stage-a-fixture", "package_ids": list(ids),
                         "deadline": (self.now + timedelta(minutes=10)).isoformat(),
                         "base_ref": "main", "parent_limit": 1},
        )

    def finish_parent(self, *, publish_input=True):
        acquired = self.now + timedelta(seconds=1)
        lease = self.registry.acquire_lease(
            "TASK-1", "builder", acquired_at=acquired.isoformat(),
            expires_at=(acquired + timedelta(minutes=5)).isoformat(),
            expected_dispatch_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.begin_attempt_runtime(
            "implementation-attempt", package_id="TASK-1", worker_id="builder",
            runner_pid=1, started_at=acquired.isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.assertTrue(lease.id)
        review_inputs = ()
        if publish_input:
            validation = {"ci": {"state": "SUCCESS", "implementation_commit": "a" * 40,
                                 "pr_url": "https://example.test/pull/1"}}
            packet = materialize_review_packet(
                self.root, implementation_attempt_id="implementation-attempt",
                base_commit=self.base, implementation_commit="a" * 40,
                contract=self.implementation, validation_evidence=validation,
                diff="diff --git a/x b/x", changed_files=["src/implementation.py"],
            )
            validation["review_packet"] = packet
            review_inputs = (ReviewInput(
                "review-input-1", "TASK-2", "TASK-1", "implementation-attempt",
                "a" * 40, self.base, "https://example.test/pull/1",
                queue_contract_digest(self.implementation), self.implementation,
                validation, (self.now + timedelta(seconds=2)).isoformat(),
            ),)
        self.registry.finish_attempt_runtime(
            "implementation-attempt", ended_at=(self.now + timedelta(seconds=2)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="submitted for review", review_inputs=review_inputs,
        )

    def advance(self, *, body=None, source_green=True):
        return self.control.advance_bounded_reviews(
            ({"number": 2, "body": body or self.review},),
            normalize_contract=lambda issue: issue["body"],
            source_is_green=lambda _review_input: source_green,
        )

    def test_review_is_authorized_but_not_claimable_until_exact_input(self):
        gate = bounded_run_worker_gate(
            self.registry.dispatch_snapshot(observed_at=self.now.isoformat()),
            ("TASK-1", "TASK-2"),
        )
        self.assertIn(["TASK-1", "builder", "reviewer"], gate["independent_pairs"])
        self.activate()
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")
        self.assertEqual(self.advance()[0]["state"], "WAITING")
        with self.assertRaisesRegex(RegistryConflict, "PACKAGE_NOT_READY"):
            self.registry.acquire_lease(
                "TASK-2", "reviewer", acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=1)).isoformat(),
            )
        self.finish_parent(publish_input=False)
        result = self.advance()[0]
        self.assertEqual(result["state"], "WAITING")
        self.assertIn("REVIEW_INPUT_REQUIRED", result["reasons"])
        # An empty READY frontier remains LIVE; only the deadline/kill guard stops it.
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")

    def test_exact_input_promotes_once_and_reviewer_remains_separate(self):
        self.activate()
        self.finish_parent()
        self.assertEqual(self.advance(source_green=False)[0]["reasons"],
                         ("REVIEW_SOURCE_OR_CI_NOT_GREEN",))
        before = self.registry.dispatch_control()["revision"]
        result = self.advance()[0]
        self.assertEqual(result["state"], "READY")
        after = self.registry.dispatch_control()["revision"]
        self.assertEqual(self.registry.promote_bounded_review(
            "TASK-2", expected_revision=before, expected_run_id="stage-a-fixture",
            expected_contract_sha256=queue_contract_digest(self.review),
            changed_at=self.now.isoformat(),
        ), after)
        self.assertEqual(self.registry.dispatch_control()["revision"], after)
        self.assertEqual(self.advance(), ())
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"):
            self.control.pre_claim("TASK-2", "builder", task_contract=self.review,
                                   github_issue=2)
        self.assertEqual(self.control.proposed_worker("TASK-2"), "reviewer")
        revision = self.control.pre_claim("TASK-2", "reviewer",
                                          task_contract=self.review, github_issue=2)
        self.assertTrue(self.control.claim_package(
            "TASK-2", worker_id="reviewer", expected_revision=revision,
            lease_seconds=60,
        ))

    def test_scope_sparse_evaluation_and_dependent_parent_fail_closed(self):
        self.registry.register_work_package(WorkPackage(
            "TASK-3", "F", "outside", "OPERATIONS", Lane.PLATFORM, ("code",), 10,
            ("outside",), status=TaskStatus.READY,
        ))
        with self.assertRaisesRegex(RegistryConflict, "RUN_V2_PAIR_REQUIRED"):
            self.activate(("TASK-1", "TASK-2", "TASK-3"))
        self.registry.transition_work_package(
            "TASK-3", expected_status=TaskStatus.READY,
            new_status=TaskStatus.ON_DECK, changed_at=self.now.isoformat(),
        )
        with self.assertRaisesRegex(RegistryConflict, "RUN_V2_PAIR_REQUIRED"):
            self.activate(("TASK-1", "TASK-2", "TASK-3"))
        self.activate()
        with self.assertRaisesRegex(RegistryConflict, "RUN_PACKAGE_NOT_ALLOWLISTED"):
            self.registry.acquire_lease(
                "TASK-3", "builder", acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=1)).isoformat(),
            )

    def test_evaluation_and_dependent_v2_parent_cannot_join_stage_a(self):
        evaluation = self.contract(3, kind="EVALUATION", paths=["docs/REVIEW.md"],
                                   dependencies=[])
        evaluation["lane"] = "ASSURANCE"
        self.register("TASK-3", evaluation, TaskStatus.READY, PackageKind.EVALUATION,
                      Lane.ASSURANCE, ("independent-review",), ())
        with self.assertRaisesRegex(RegistryConflict, "RUN_V2_PAIR_REQUIRED"):
            self.activate(("TASK-1", "TASK-2", "TASK-3"))

    def test_done_dependency_does_not_authorize_successor_parent(self):
        predecessor = self.contract(3, kind="PARENT", paths=["docs/REVIEW.md"],
                                    dependencies=[1])
        self.register("TASK-3", predecessor, TaskStatus.READY, PackageKind.PARENT,
                      Lane.PLATFORM, ("code",), ("TASK-1",))
        with self.assertRaisesRegex(RegistryConflict, "RUN_INDEPENDENT_ROOT_REQUIRED"):
            self.activate(("TASK-1", "TASK-2", "TASK-3"))

    def test_changed_issue_contract_waits_without_affecting_live_mode(self):
        self.activate()
        self.finish_parent()
        changed = {**self.review, "instructions": "Silently changed issue"}
        result = self.advance(body=changed)[0]
        self.assertEqual(result["state"], "WAITING")
        self.assertIn("REGISTRATION_PROOF_CHANGED", result["reasons"])
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")

    def test_stale_revision_and_deadline_cannot_promote(self):
        self.activate()
        self.finish_parent()
        before = self.registry.dispatch_control()["revision"]
        self.registry.append_event("RACE", recorded_at=self.now.isoformat())
        with self.assertRaisesRegex(RegistryConflict, "REGISTRY_REVISION_CHANGED"):
            self.registry.promote_bounded_review(
                "TASK-2", expected_revision=before,
                expected_run_id="stage-a-fixture",
                expected_contract_sha256=queue_contract_digest(self.review),
                changed_at=(self.now + timedelta(seconds=3)).isoformat(),
            )
        with self.assertRaisesRegex(RegistryConflict, "RUN_DEADLINE_EXPIRED"):
            self.registry.promote_bounded_review(
                "TASK-2", expected_revision=self.registry.dispatch_control()["revision"],
                expected_run_id="stage-a-fixture",
                expected_contract_sha256=queue_contract_digest(self.review),
                changed_at=(self.now + timedelta(minutes=11)).isoformat(),
            )
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")

    def test_source_check_crossing_deadline_cannot_publish_review(self):
        self.activate()
        self.finish_parent()
        clock = [self.now + timedelta(seconds=3)]

        def slow_source_check(_review_input):
            clock[0] = self.now + timedelta(minutes=11)
            return True

        with patch("registry_control.utc_now", side_effect=lambda: clock[0].isoformat()), \
                patch("scripts.factory_registry.sqlite_registry._utc_now",
                      side_effect=lambda: clock[0].isoformat()):
            result = self.control.advance_bounded_reviews(
                ({"number": 2, "body": self.review},),
                normalize_contract=lambda issue: issue["body"],
                source_is_green=slow_source_check,
            )
            self.assertEqual(result[0]["state"], "WAITING")
            self.assertIn("RUN_DEADLINE_EXPIRED", result[0]["reasons"])
            # Even a stale caller-supplied timestamp cannot bypass the
            # Registry's own persisted-deadline check.
            with self.assertRaisesRegex(RegistryConflict, "RUN_DEADLINE_EXPIRED"):
                self.registry.promote_bounded_review(
                    "TASK-2", expected_revision=self.registry.dispatch_control()["revision"],
                    expected_run_id="stage-a-fixture",
                    expected_contract_sha256=queue_contract_digest(self.review),
                    changed_at=(self.now + timedelta(seconds=3)).isoformat(),
                )
        package = next(item for item in self.registry.dispatch_snapshot(
            observed_at=self.now.isoformat()).work_packages
                       if item["id"] == "TASK-2")
        self.assertEqual(package["status"], "ON_DECK")

    def test_unavailable_contract_check_does_not_block_other_review(self):
        second = self.contract(3, kind="PARENT", paths=[
            "src/second.py", "tests/test_second.py",
        ], dependencies=[])
        second_review = self.contract(4, kind="REVIEW", paths=["docs/SECOND_REVIEW.md"],
                                      dependencies=[3])
        self.register("TASK-3", second, TaskStatus.READY, PackageKind.PARENT,
                      Lane.PLATFORM, ("code",), ())
        self.register("TASK-4", second_review, TaskStatus.ON_DECK, PackageKind.REVIEW,
                      Lane.ASSURANCE, ("independent-review",), ("TASK-3",))
        self.activate(("TASK-1", "TASK-2", "TASK-3", "TASK-4"))
        self.finish_parent()

        def check_with_first_unavailable(contract, **kwargs):
            if contract["task"] == "TASK-2":
                raise OSError("Git unavailable")
            return check_packet(contract, **kwargs)

        with patch("registry_control.check_packet", side_effect=check_with_first_unavailable):
            result = self.control.advance_bounded_reviews(
                ({"number": 2, "body": self.review},
                 {"number": 4, "body": second_review}),
                normalize_contract=lambda issue: issue["body"],
                source_is_green=lambda _input: True,
            )
        self.assertEqual(result[0]["reasons"], ("QUEUE_CONTRACT_UNAVAILABLE",))
        self.assertEqual(result[1]["state"], "WAITING")
        self.assertNotIn("QUEUE_CONTRACT_UNAVAILABLE", result[1]["reasons"])
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")

    def test_failed_first_root_does_not_stop_second_independent_root(self):
        second = self.contract(3, kind="PARENT", paths=[
            "src/second.py", "tests/test_second.py",
        ], dependencies=[])
        second_review = self.contract(4, kind="REVIEW", paths=["docs/SECOND_REVIEW.md"],
                                      dependencies=[3])
        self.register("TASK-3", second, TaskStatus.READY, PackageKind.PARENT,
                      Lane.PLATFORM, ("code",), ())
        self.register("TASK-4", second_review, TaskStatus.ON_DECK, PackageKind.REVIEW,
                      Lane.ASSURANCE, ("independent-review",), ("TASK-3",))
        self.activate(("TASK-1", "TASK-2", "TASK-3", "TASK-4"))
        acquired = self.now + timedelta(seconds=1)
        self.registry.acquire_lease(
            "TASK-1", "builder", acquired_at=acquired.isoformat(),
            expires_at=(acquired + timedelta(minutes=5)).isoformat(),
            expected_dispatch_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.begin_attempt_runtime(
            "failed-first", package_id="TASK-1", worker_id="builder",
            runner_pid=1, started_at=acquired.isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "failed-first", ended_at=(self.now + timedelta(seconds=2)).isoformat(),
            outcome="FAILED", next_status=TaskStatus.BLOCKED,
            reason="first root failed", failure_detail="isolated failure",
        )
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")
        self.assertEqual(self.control.proposed_worker("TASK-3"), "builder")
        self.assertEqual(self.advance()[0]["state"], "WAITING")
        self.assertTrue(self.control.claim_package(
            "TASK-3", worker_id="builder",
            expected_revision=self.control.pre_claim(
                "TASK-3", "builder", task_contract=second, github_issue=3,
            ), lease_seconds=60,
        ))
