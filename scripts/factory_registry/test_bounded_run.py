"""Adversarial coverage for the small Registry-owned pilot envelope."""

from __future__ import annotations

import pathlib
import tempfile
import unittest
import hashlib
import json
from datetime import datetime, timedelta, timezone

from scripts.factory_registry.models import (
    Evidence, Feature, Lane, PackageKind, ReviewInput, ReviewOutcome,
    ReviewOutcomeState, TaskStatus, Worker, WorkPackage,
)
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.sqlite_registry import SQLiteRegistry


class BoundedRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.registry = SQLiteRegistry(pathlib.Path(self.temp.name) / "registry.sqlite")
        self.registry.initialize()
        self.now = datetime.now(timezone.utc)
        self.registry.register_feature(Feature("F", "Feature", 1, TaskStatus.READY))
        for worker_id in ("builder-a", "builder-b", "builder-c"):
            self.registry.register_worker(Worker(
                worker_id, worker_id, ("code",), (Lane.PLATFORM,), usage_state="GREEN"
            ))
        for package_id in ("TASK-1", "TASK-2", "TASK-3"):
            self.registry.register_work_package(WorkPackage(
                package_id, "F", package_id, "test", Lane.PLATFORM, ("code",), 1,
                ("works",), status=TaskStatus.READY,
            ))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def enable(self, package_ids=("TASK-1", "TASK-2"), *, run_id="pilot-new", deadline=None,
               parent_limit=2) -> None:
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE",
            kill_switch_engaged=False, changed_at=self.now.isoformat(), reason="test pilot",
            bounded_run={
                "run_id": run_id, "package_ids": list(package_ids), "base_ref": "main",
                "deadline": (deadline or self.now + timedelta(minutes=5)).isoformat(), "parent_limit": parent_limit,
            },
        )

    def test_two_independent_allowlisted_claims_and_rejects_another_ready_package(self) -> None:
        self.enable()
        for package_id, worker_id in (("TASK-1", "builder-a"), ("TASK-2", "builder-b")):
            self.registry.acquire_lease(
                package_id, worker_id, acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=1)).isoformat(),
                expected_dispatch_revision=self.registry.dispatch_control()["revision"],
            )
        with self.assertRaisesRegex(RegistryConflict, "RUN_PACKAGE_NOT_ALLOWLISTED"):
            self.registry.acquire_lease(
                "TASK-3", "builder-c", acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=1)).isoformat(),
                expected_dispatch_revision=self.registry.dispatch_control()["revision"],
            )

    def test_long_allowlist_is_bounded_by_wip_not_registered_queue_size(self) -> None:
        self.enable(("TASK-1", "TASK-2", "TASK-3"), parent_limit=3)
        for package_id, worker_id in (("TASK-1", "builder-a"), ("TASK-2", "builder-b"),
                                      ("TASK-3", "builder-c")):
            self.registry.acquire_lease(
                package_id, worker_id, acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=1)).isoformat(),
                expected_dispatch_revision=self.registry.dispatch_control()["revision"],
            )
        self.assertEqual(
            sum(item["package_id"] in {"TASK-1", "TASK-2", "TASK-3"}
                for item in self.registry.dispatch_snapshot(observed_at=self.now.isoformat()).active_leases),
            3,
        )

    def test_direct_lease_cannot_claim_retained_scope_after_kill(self) -> None:
        self.enable()
        self.registry.engage_dispatch_kill_switch(
            changed_at=self.now.isoformat(), reason="stop before direct claim"
        )
        self.assertEqual("STOPPING", self.registry.dispatch_control()["dispatch_mode"])
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_NOT_AUTHORIZED"):
            self.registry.acquire_lease(
                "TASK-1", "builder-a", acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=1)).isoformat(),
            )

    def test_expired_run_cannot_claim_and_old_timer_cannot_stop_successor(self) -> None:
        self.enable(deadline=self.now - timedelta(seconds=1))
        with self.assertRaisesRegex(RegistryConflict, "RUN_DEADLINE_EXPIRED"):
            self.registry.acquire_lease(
                "TASK-1", "builder-a", acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=1)).isoformat(),
                expected_dispatch_revision=self.registry.dispatch_control()["revision"],
            )
        # An unconditional operator stop ends the old run; a fresh activation
        # follows only after its normal drained PAUSED transition.
        self.registry.engage_dispatch_kill_switch(changed_at=self.now.isoformat(), reason="expired")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="STOPPING", new_mode="PAUSED",
            kill_switch_engaged=True, changed_at=self.now.isoformat(), reason="drained",
        )
        self.enable(("TASK-2",), run_id="pilot-successor")
        before = self.registry.dispatch_control()["revision"]
        self.assertEqual(
            before,
            self.registry.engage_dispatch_kill_switch(
                changed_at=self.now.isoformat(), reason="old timer", expected_run_id="pilot-new"
            ),
        )
        self.assertEqual("LIVE", self.registry.dispatch_control()["dispatch_mode"])

    def test_builder_wip_counts_only_current_lineage_and_frees_after_real_review(self) -> None:
        self.registry.register_worker(Worker(
            "reviewer", "reviewer", ("review",), (Lane.ASSURANCE,), usage_state="GREEN"
        ))
        for package_id in ("A-1", "A-2", "A-3", "B-1", "HISTORICAL-A"):
            self.registry.register_work_package(WorkPackage(
                package_id, "F", package_id, "test", Lane.PLATFORM, ("code",), 1,
                ("works",), status=TaskStatus.READY,
            ))
        self.registry.register_work_package(WorkPackage(
            "REVIEW-A-1", "F", "review A-1", "test", Lane.ASSURANCE, ("review",), 1,
            ("reviews",), status=TaskStatus.READY, kind=PackageKind.REVIEW,
            dependency_ids=("A-1",),
        ))

        # Preserve an old submitted parent outside the new envelope.  It has
        # real successful-attempt provenance but must not consume a new run's
        # WIP capacity.
        self.enable(("HISTORICAL-A",), run_id="historical-run", parent_limit=1)
        historical = self.registry.acquire_lease(
            "HISTORICAL-A", "builder-a", acquired_at=self.now.isoformat(),
            expires_at=(self.now + timedelta(minutes=1)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "historical-attempt", package_id="HISTORICAL-A", worker_id="builder-a",
            runner_pid=1, started_at=self.now.isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "historical-attempt", ended_at=(self.now + timedelta(seconds=1)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="preserved historical submission",
        )
        self.assertTrue(historical.id)
        self.registry.engage_dispatch_kill_switch(
            changed_at=(self.now + timedelta(seconds=2)).isoformat(), reason="historical run ended"
        )
        stopped = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=stopped["revision"], expected_mode="STOPPING", new_mode="PAUSED",
            kill_switch_engaged=True, changed_at=(self.now + timedelta(seconds=2)).isoformat(),
            reason="historical ownership drained",
        )
        self.enable(("A-1", "REVIEW-A-1", "A-2", "A-3", "B-1"), parent_limit=3)

        first = self.registry.acquire_lease(
            "A-1", "builder-a", acquired_at=self.now.isoformat(),
            expires_at=(self.now + timedelta(minutes=1)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "attempt-a-1", package_id="A-1", worker_id="builder-a", runner_pid=1,
            started_at=self.now.isoformat(), expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "attempt-a-1", ended_at=(self.now + timedelta(seconds=1)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="submitted for independent review",
        )
        self.assertTrue(first.id)
        self.registry.acquire_lease(
            "A-2", "builder-a", acquired_at=(self.now + timedelta(seconds=2)).isoformat(),
            expires_at=(self.now + timedelta(minutes=2)).isoformat(),
        )
        self.registry.acquire_lease(
            "B-1", "builder-b", acquired_at=(self.now + timedelta(seconds=2)).isoformat(),
            expires_at=(self.now + timedelta(minutes=2)).isoformat(),
        )
        with self.assertRaisesRegex(RegistryConflict, "BUILDER_WIP_LIMIT"):
            self.registry.acquire_lease(
                "A-3", "builder-a", acquired_at=(self.now + timedelta(seconds=3)).isoformat(),
                expires_at=(self.now + timedelta(minutes=2)).isoformat(),
            )
        contract = {"task": "A-1", "paths": ["scripts/factory_registry/test_bounded_run.py"]}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        review_input = ReviewInput(
            "review-input-a-1", "REVIEW-A-1", "A-1", "attempt-a-1", "a" * 40,
            "b" * 40, "https://example.test/a-1", digest, contract,
            {"validation": "passed"}, (self.now + timedelta(seconds=2)).isoformat(),
        )
        self.registry.record_review_input(review_input)
        self.registry.acquire_lease(
            "REVIEW-A-1", "reviewer", acquired_at=(self.now + timedelta(seconds=4)).isoformat(),
            expires_at=(self.now + timedelta(minutes=2)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "review-attempt-a-1", package_id="REVIEW-A-1", worker_id="reviewer", runner_pid=2,
            started_at=(self.now + timedelta(seconds=4)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "review-attempt-a-1", ended_at=(self.now + timedelta(seconds=5)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="independent review complete",
        )
        evidence = Evidence(
            "review-evidence-a-1", "REVIEW-A-1", "review", None, "Approved",
            (self.now + timedelta(seconds=6)).isoformat(),
            {"attempt_id": "review-attempt-a-1", "reviewed_commit": "a" * 40,
             "reviewed_base_commit": "b" * 40, "contract_sha256": digest,
             "review_input_evidence_id": "review-input-a-1"},
        )
        self.registry.record_review_outcome(ReviewOutcome(
            "outcome-a-1", "REVIEW-A-1", "A-1", "builder-a", "reviewer",
            (self.now + timedelta(seconds=3)).isoformat(), (self.now + timedelta(seconds=6)).isoformat(),
            ReviewOutcomeState.APPROVED, findings=("approved",), approval_evidence_ids=("review-evidence-a-1",),
            reviewed_commit="a" * 40, reviewed_base_commit="b" * 40, contract_sha256=digest,
            review_input_evidence_id="review-input-a-1", reviewer_attempt_id="review-attempt-a-1",
        ), evidence=evidence, expected_revision=self.registry.dispatch_control()["revision"])
        # A-1's real review outcome frees the waiting-review slot.  A-2 still
        # owns the worker's sole live lease, so release that active lease only
        # after asserting the outcome; the old test incorrectly used this
        # release itself as proof that WIP was freed.
        active_a2 = next(item["id"] for item in self.registry.dispatch_snapshot(
            observed_at=(self.now + timedelta(seconds=6)).isoformat()
        ).active_leases if item["package_id"] == "A-2")
        self.registry.release_lease(
            active_a2, released_at=(self.now + timedelta(seconds=7)).isoformat(),
            reason="next bounded parent", next_status=TaskStatus.READY,
        )
        lease = self.registry.acquire_lease(
            "A-3", "builder-a", acquired_at=(self.now + timedelta(seconds=8)).isoformat(),
            expires_at=(self.now + timedelta(minutes=2)).isoformat(),
        )
        self.assertEqual(lease.package_id, "A-3")
        statuses = {item["id"]: item["status"] for item in self.registry.dispatch_snapshot(
            observed_at=(self.now + timedelta(seconds=8)).isoformat()
        ).work_packages}
        self.assertEqual(statuses["A-1"], TaskStatus.DONE.value)
        self.assertEqual(statuses["REVIEW-A-1"], TaskStatus.DONE.value)

    def test_three_registered_pairs_keep_dependency_waiting_work_unclaimable(self) -> None:
        """Exercise actual package/dependency rows, not parser-only blocking."""
        self.registry.register_worker(Worker(
            "builder-d", "builder-d", ("code",), (Lane.PLATFORM,), usage_state="GREEN"
        ))
        pairs = tuple((f"IMPL-{index}", f"REVIEW-{index}") for index in range(1, 4))
        for implementation, review in pairs:
            self.registry.register_work_package(WorkPackage(
                implementation, "F", implementation, "test", Lane.PLATFORM, ("code",), 1,
                ("implements",), status=TaskStatus.READY,
            ))
            self.registry.register_work_package(WorkPackage(
                review, "F", review, "test", Lane.ASSURANCE, ("review",), 1,
                ("reviews",), status=TaskStatus.READY, kind=PackageKind.REVIEW,
                dependency_ids=(implementation,),
            ))
        self.registry.register_work_package(WorkPackage(
            "WAITING", "F", "waits for implementation", "test", Lane.PLATFORM, ("code",), 1,
            ("waits",), status=TaskStatus.READY, dependency_ids=("IMPL-1",),
        ))
        self.registry.register_work_package(WorkPackage(
            "UNRELATED", "F", "independent implementation", "test", Lane.PLATFORM, ("code",), 1,
            ("runs",), status=TaskStatus.READY,
        ))
        allowlist = tuple(item for pair in pairs for item in pair) + ("WAITING", "UNRELATED")
        self.enable(allowlist, parent_limit=3)
        for package_id, worker_id in (("IMPL-1", "builder-a"), ("IMPL-2", "builder-b")):
            self.registry.acquire_lease(
                package_id, worker_id, acquired_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=2)).isoformat(),
            )
        self.registry.begin_attempt_runtime(
            "impl-1-attempt", package_id="IMPL-1", worker_id="builder-a", runner_pid=1,
            started_at=self.now.isoformat(), expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "impl-1-attempt", ended_at=(self.now + timedelta(seconds=1)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="review pair one ready",
        )
        self.registry.acquire_lease(
            "IMPL-3", "builder-c", acquired_at=(self.now + timedelta(seconds=2)).isoformat(),
            expires_at=(self.now + timedelta(minutes=2)).isoformat(),
        )
        with self.assertRaisesRegex(RegistryConflict, "DEPENDENCY_BLOCKED"):
            self.registry.acquire_lease(
                "WAITING", "builder-d", acquired_at=(self.now + timedelta(seconds=3)).isoformat(),
                expires_at=(self.now + timedelta(minutes=2)).isoformat(),
            )
        unrelated = self.registry.acquire_lease(
            "UNRELATED", "builder-d", acquired_at=(self.now + timedelta(seconds=3)).isoformat(),
            expires_at=(self.now + timedelta(minutes=2)).isoformat(),
        )
        self.assertEqual(unrelated.package_id, "UNRELATED")
