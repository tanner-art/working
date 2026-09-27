"""Adversarial coverage for the small Registry-owned pilot envelope."""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from scripts.factory_registry.models import Feature, Lane, TaskStatus, Worker, WorkPackage
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

    def test_builder_wip_counts_submitted_review_provenance_and_frees_after_review(self) -> None:
        self.registry.register_worker(Worker(
            "reviewer", "reviewer", ("code",), (Lane.PLATFORM,), usage_state="GREEN"
        ))
        for package_id in ("A-1", "A-2", "A-3", "B-1"):
            self.registry.register_work_package(WorkPackage(
                package_id, "F", package_id, "test", Lane.PLATFORM, ("code",), 1,
                ("works",), status=TaskStatus.READY,
            ))
        self.enable(("A-1", "A-2", "A-3", "B-1"), parent_limit=3)

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
        # Releasing A-2 frees its active slot while A-1 remains durably
        # attributed to A through its submitted-review attempt.
        self.registry.release_lease(
            next(item["id"] for item in self.registry.dispatch_snapshot(observed_at=(self.now + timedelta(seconds=3)).isoformat()).active_leases if item["package_id"] == "A-2"),
            released_at=(self.now + timedelta(seconds=4)).isoformat(),
            reason="builder slot released", next_status=TaskStatus.READY,
        )
        restarted = SQLiteRegistry(self.registry.database)
        lease = restarted.acquire_lease(
            "A-3", "builder-a", acquired_at=(self.now + timedelta(seconds=5)).isoformat(),
            expires_at=(self.now + timedelta(minutes=2)).isoformat(),
        )
        self.assertEqual(lease.package_id, "A-3")
