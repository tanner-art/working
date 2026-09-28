"""Integration proof for an opt-in, evidence-bound failed-review correction."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.factory_registry import (
    Evidence, Feature, Lane, PackageKind, RegistryConflict, SQLiteRegistry,
    TaskStatus, Worker, WorkPackage,
)
from scripts.factory_registry.models import ReviewInput, ReviewOutcome, ReviewOutcomeState
from scripts.runner.registry_control import RunnerRegistryControl


def stamp(start: datetime, seconds: int) -> str:
    return (start + timedelta(seconds=seconds)).isoformat()


def digest(contract: dict) -> str:
    return hashlib.sha256(json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


class ReviewCorrectionLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.registry = SQLiteRegistry(Path(self.temporary.name) / "registry.sqlite3")
        self.registry.initialize()
        self.start = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.root_contract = {"task": "TASK-701", "paths": ["docs/factory/correction.md"], "depends_on": []}
        self.registry.register_feature(Feature("F", "Correction", 10, TaskStatus.READY))
        for worker_id, lane, capabilities in (
            ("agent-a", Lane.PLATFORM, ("code",)),
            ("agent-b", Lane.PLATFORM, ("code",)),
            ("claude", Lane.ASSURANCE, ("review",)),
        ):
            self.registry.register_worker(Worker(
                worker_id, worker_id, capabilities, (lane,), usage_state="GREEN",
            ))
        self.registry.register_work_package(WorkPackage(
            "TASK-701", "F", "original", "PLATFORM", Lane.PLATFORM,
            ("code",), 10, ("same acceptance",), status=TaskStatus.READY,
            provider_diagnostics={"queue_contract_sha256": digest(self.root_contract),
                                  "github_source_ref": "701"},
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK-702", "F", "review", "ASSURANCE", Lane.ASSURANCE,
            ("review",), 10, ("independent",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-701",),
            provider_diagnostics={"queue_contract_sha256": digest({"task": "TASK-702"}),
                                  "github_source_ref": "702"},
        ))
        for package_id, issue, contract in (
            ("TASK-701", 701, self.root_contract),
            ("TASK-702", 702, {"task": "TASK-702"}),
        ):
            self.registry.bind_legacy_package_source(
                package_id, github_issue=issue, queue_contract=contract,
                expected_revision=self.registry.dispatch_control()["revision"],
                recorded_at=stamp(self.start, 0),
            )
        self._live(1)
        self._attempt("TASK-701", "agent-a", "initial", 2)
        self._paused(6)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _live(self, second: int, scope: dict | None = None) -> None:
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=stamp(self.start, second),
            reason="correction fixture", bounded_run=scope,
            continuous_queue=scope is None,
        )

    def _paused(self, second: int) -> None:
        self.registry.engage_dispatch_kill_switch(
            changed_at=stamp(self.start, second), reason="register slots",
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="STOPPING",
            new_mode="PAUSED", kill_switch_engaged=True,
            changed_at=stamp(self.start, second + 1), reason="drained",
        )

    def _attempt(self, package_id: str, worker: str, attempt_id: str, second: int) -> None:
        self.registry.acquire_lease(
            package_id, worker, acquired_at=stamp(self.start, second),
            expires_at=stamp(self.start, second + 60),
            expected_dispatch_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.begin_attempt_runtime(
            attempt_id, package_id=package_id, worker_id=worker,
            runner_pid=os.getpid(), started_at=stamp(self.start, second + 1),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            attempt_id, ended_at=stamp(self.start, second + 2), outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW, reason="fixture completed",
        )

    def _slots(self):
        slots = []
        for ordinal, parent_id, review_id in ((1, "TASK-703", "TASK-704"),
                                               (2, "TASK-705", "TASK-706")):
            implementation_contract = {
                "task": parent_id, "paths": self.root_contract["paths"], "depends_on": [],
            }
            review_contract = {"task": review_id, "depends_on": [int(parent_id[5:])],
                               "paths": self.root_contract["paths"]}
            parent = WorkPackage(
                parent_id, "F", f"draft {ordinal + 1}", "PLATFORM", Lane.PLATFORM,
                ("code",), 10, ("same acceptance",), status=TaskStatus.ON_DECK,
                provider_diagnostics={"queue_contract_sha256": digest(implementation_contract),
                                      "github_source_ref": parent_id[5:]},
            )
            review = WorkPackage(
                review_id, "F", f"review {ordinal + 1}", "ASSURANCE", Lane.ASSURANCE,
                ("review",), 10, ("independent",), status=TaskStatus.ON_DECK,
                kind=PackageKind.REVIEW, dependency_ids=(parent_id,),
                provider_diagnostics={"queue_contract_sha256": digest(review_contract),
                                      "github_source_ref": review_id[5:]},
            )
            slots.append((parent, review, implementation_contract, review_contract))
        return tuple(slots)

    def _verdict(self, target: str, review: str, implementation_attempt: str,
                 review_attempt: str, second: int, state: ReviewOutcomeState) -> int:
        contract = self.root_contract if target == "TASK-701" else next(
            slot[2] for slot in self._slots() if slot[0].id == target
        )
        input_id = f"input-{review}"
        commit = f"{int(target[5:]):040x}"
        self.registry.record_review_input(ReviewInput(
            input_id, review, target, implementation_attempt, commit, "b" * 40,
            f"https://example.test/pull/{target[5:]}", digest(contract), contract,
            {"tests": "passed"}, stamp(self.start, second - 1),
        ))
        self._attempt(review, "claude", review_attempt, second)
        evidence_id = f"evidence-{review}"
        return self.registry.record_review_outcome(ReviewOutcome(
            id=f"outcome-{review}", review_package_id=review, target_package_id=target,
            implementer_worker_id="agent-a", reviewer_worker_id="claude",
            requested_at=stamp(self.start, second - 1), decided_at=stamp(self.start, second + 3),
            state=state, findings=("specific finding",),
            changes_requested=("repair finding",) if state is ReviewOutcomeState.CHANGES_REQUESTED else (),
            approval_evidence_ids=(evidence_id,) if state is ReviewOutcomeState.APPROVED else (),
            reviewed_commit=commit, reviewed_base_commit="b" * 40,
            contract_sha256=digest(contract), review_input_evidence_id=input_id,
            reviewer_attempt_id=review_attempt,
        ), evidence=Evidence(
            evidence_id, review, "review", f"https://example.test/review/{review}",
            "structured verdict", stamp(self.start, second + 2),
            {"attempt_id": review_attempt, "reviewed_commit": commit,
             "reviewed_base_commit": "b" * 40, "contract_sha256": digest(contract),
             "review_input_evidence_id": input_id},
        ), expected_revision=self.registry.dispatch_control()["revision"])

    def _states(self):
        snapshot = self.registry.dispatch_snapshot(observed_at=stamp(self.start, 100))
        return {item["id"]: item["status"] for item in snapshot.work_packages}

    def test_failed_review_activates_only_same_author_next_pair(self):
        slots = self._slots()
        self.registry.register_review_correction_slots(
            "TASK-701", self.root_contract, slots,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=stamp(self.start, 8),
        )
        scope = {"run_id": "correction-proof", "package_ids": ["TASK-701", "TASK-702",
                 "TASK-703", "TASK-704", "TASK-705", "TASK-706"],
                 "deadline": stamp(self.start, 180), "base_ref": "main", "parent_limit": 2}
        self._live(9, scope)
        first_revision = self._verdict("TASK-701", "TASK-702", "initial", "review-1", 10,
                                       ReviewOutcomeState.CHANGES_REQUESTED)
        self.assertEqual(self._states()["TASK-701"], "BLOCKED")
        self.assertEqual(self._states()["TASK-703"], "READY")
        self.assertEqual(self._states()["TASK-704"], "READY")
        self.assertEqual(self._states()["TASK-705"], "ON_DECK")
        self.assertEqual(self._states()["TASK-706"], "ON_DECK")
        with self.assertRaisesRegex(RegistryConflict, "CORRECTION_AUTHOR_MISMATCH"):
            self.registry.acquire_lease("TASK-703", "agent-b", acquired_at=stamp(self.start, 15),
                                        expires_at=stamp(self.start, 80),
                                        expected_dispatch_revision=first_revision)
        context = self.registry.review_correction_context("TASK-703")
        self.assertEqual(context["reviewed_commit"], f"{701:040x}")
        self.assertEqual(context["changes_requested"], ["repair finding"])
        self._attempt("TASK-703", "agent-a", "correction-1", 16)
        inputs = RunnerRegistryControl(self.registry.database).implementation_review_inputs(
            target_package_id="TASK-703", implementation_attempt_id="correction-1",
            implementation_commit=f"{703:040x}", base_commit="b" * 40,
            pr_url="https://example.test/pull/703", contract=slots[0][2],
            validation_evidence={"tests": "passed"}, recorded_at=stamp(self.start, 19),
        )
        self.assertEqual([item.review_package_id for item in inputs], ["TASK-704"])
        self._verdict("TASK-703", "TASK-704", "correction-1", "review-2", 20,
                      ReviewOutcomeState.APPROVED)
        self.assertEqual(self._states()["TASK-703"], "DONE")
        self.assertEqual(self._states()["TASK-705"], "ON_DECK")
        feature = next(item for item in self.registry.dispatch_snapshot(
            observed_at=stamp(self.start, 100)).features if item["id"] == "F")
        self.assertEqual(feature["status"], "DONE")

    def test_incomplete_allowlist_fails_closed(self):
        self.registry.register_review_correction_slots(
            "TASK-701", self.root_contract, self._slots(),
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=stamp(self.start, 8),
        )
        incomplete = {"run_id": "missing-correction-review", "package_ids": [
            "TASK-701", "TASK-702", "TASK-703", "TASK-705", "TASK-706"],
            "deadline": stamp(self.start, 180), "base_ref": "main", "parent_limit": 2}
        with self.assertRaisesRegex(RegistryConflict, "RUN_CORRECTION_SCOPE_INVALID"):
            self._live(9, incomplete)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_three_rejected_drafts_exhaust_without_requeueing(self):
        self.registry.register_review_correction_slots(
            "TASK-701", self.root_contract, self._slots(),
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=stamp(self.start, 8),
        )
        self._live(9, {"run_id": "three-drafts", "package_ids": [
            "TASK-701", "TASK-702", "TASK-703", "TASK-704", "TASK-705", "TASK-706"],
            "deadline": stamp(self.start, 180), "base_ref": "main", "parent_limit": 2})
        self._verdict("TASK-701", "TASK-702", "initial", "review-1", 10,
                      ReviewOutcomeState.CHANGES_REQUESTED)
        self._attempt("TASK-703", "agent-a", "correction-1", 16)
        self._verdict("TASK-703", "TASK-704", "correction-1", "review-2", 20,
                      ReviewOutcomeState.CHANGES_REQUESTED)
        self.assertEqual(self._states()["TASK-705"], "READY")
        self._attempt("TASK-705", "agent-a", "correction-2", 26)
        self._verdict("TASK-705", "TASK-706", "correction-2", "review-3", 30,
                      ReviewOutcomeState.CHANGES_REQUESTED)
        self.assertEqual(self._states()["TASK-705"], "BLOCKED")
        self.assertFalse(any(state == "READY" for state in self._states().values()))
        snapshot = self.registry.dispatch_snapshot(observed_at=stamp(self.start, 100))
        self.assertEqual(next(item for item in snapshot.features if item["id"] == "F")["status"], "BLOCKED")
        outcomes = self.registry.control_center_snapshot(observed_at=stamp(self.start, 100)).review_outcomes
        self.assertEqual([item["state"] for item in outcomes], ["CHANGES_REQUESTED"] * 3)

    def test_scope_mismatch_rejects_registration_without_partial_slots(self):
        slots = list(self._slots())
        wrong_contract = {**slots[0][2], "paths": ["docs/factory/unrelated.md"]}
        parent, review, _, review_contract = slots[0]
        from dataclasses import replace
        parent = replace(parent, provider_diagnostics={
            **parent.provider_diagnostics, "queue_contract_sha256": digest(wrong_contract),
        })
        slots[0] = (parent, review, wrong_contract, review_contract)
        before = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "CORRECTION_SLOT_SCOPE_MISMATCH"):
            self.registry.register_review_correction_slots(
                "TASK-701", self.root_contract, slots, expected_revision=before,
                recorded_at=stamp(self.start, 8),
            )
        self.assertEqual(self.registry.dispatch_control()["revision"], before)
        self.assertNotIn("TASK-703", self._states())

    def test_downstream_does_not_consume_rejected_review_as_success(self):
        self.registry.register_feature(Feature("G", "Downstream", 1, TaskStatus.READY))
        downstream_contract = {"task": "TASK-707", "depends_on": [702],
                               "paths": ["docs/factory/downstream.md"]}
        self.registry.register_work_package(WorkPackage(
            "TASK-707", "G", "downstream", "PLATFORM", Lane.PLATFORM,
            ("code",), 1, ("wait for review",), status=TaskStatus.READY,
            dependency_ids=("TASK-702",),
            provider_diagnostics={"queue_contract_sha256": digest(downstream_contract),
                                  "github_source_ref": "707"},
        ))
        self.registry.bind_legacy_package_source(
            "TASK-707", github_issue=707, queue_contract=downstream_contract,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=stamp(self.start, 8),
        )
        self.registry.register_review_correction_slots(
            "TASK-701", self.root_contract, self._slots(),
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=stamp(self.start, 8),
        )
        self._live(9, {"run_id": "dependency-proof", "package_ids": [
            "TASK-701", "TASK-702", "TASK-703", "TASK-704", "TASK-705", "TASK-706", "TASK-707"],
            "deadline": stamp(self.start, 180), "base_ref": "main", "parent_limit": 2})
        self._verdict("TASK-701", "TASK-702", "initial", "review-1", 10,
                      ReviewOutcomeState.CHANGES_REQUESTED)
        snapshot = self.registry.dispatch_snapshot(observed_at=stamp(self.start, 15))
        review = next(item for item in snapshot.work_packages if item["id"] == "TASK-702")
        self.assertTrue(review["review_changes_pending"])
        with self.assertRaisesRegex(RegistryConflict, "DEPENDENCY_REVIEW_CHANGES_PENDING"):
            self.registry.acquire_lease(
                "TASK-707", "agent-b", acquired_at=stamp(self.start, 15),
                expires_at=stamp(self.start, 80),
                expected_dispatch_revision=self.registry.dispatch_control()["revision"],
            )


if __name__ == "__main__":
    unittest.main()
