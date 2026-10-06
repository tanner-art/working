"""A rejected verdict must leave the reviewer attempt available to fail closed."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import datetime

from scripts.factory_registry.models import Evidence, ReviewOutcome, ReviewOutcomeState
from scripts.factory_registry.repository import RegistryConflict


class AtomicReviewOutcomeTests(unittest.TestCase):
    # Reuse the public-API fixture for a historical implementation and its
    # immutable review input; this test never edits SQLite tables directly.
    def stamp(self, seconds):
        return self.fixture.stamp(self, seconds)

    def review_input(self):
        return self.fixture.review_input(self)

    def setUp(self):
        from scripts.factory_registry.test_external_integration_review import ExternalIntegrationReviewTests
        self.fixture = ExternalIntegrationReviewTests
        self.fixture.setUp(self)

    def test_failed_verdict_rolls_back_review_attempt_then_valid_verdict_commits_both(self):
        review_input = self.review_input()
        self.registry.record_external_integration_review_input(
            review_input, expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.set_dispatch_control(
            expected_revision=self.registry.dispatch_control()["revision"],
            expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.stamp(8), reason="atomic review fixture",
        )
        self.registry.acquire_lease(
            "TASK-232", "claude", acquired_at=self.stamp(9), expires_at=self.stamp(120),
        )
        self.registry.begin_attempt_runtime(
            "review-attempt", package_id="TASK-232", worker_id="claude",
            runner_pid=os.getpid(), started_at=self.stamp(10),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        outcome = ReviewOutcome(
            id="atomic-verdict", review_package_id="TASK-232", target_package_id="TASK-231",
            implementer_worker_id="codex-a", reviewer_worker_id="claude",
            requested_at=review_input.recorded_at, decided_at=self.stamp(11),
            state=ReviewOutcomeState.APPROVED, findings=("Exact CP-02 proof accepted.",),
            approval_evidence_ids=("atomic-verdict-evidence",), reviewed_commit=self.commit,
            reviewed_base_commit=self.base, contract_sha256=review_input.contract_sha256,
            review_input_evidence_id=review_input.id, reviewer_attempt_id="review-attempt",
        )
        evidence = Evidence(
            "atomic-verdict-evidence", "TASK-232", "review", self.pr,
            "Structured independent review", self.stamp(11),
            {"attempt_id": "review-attempt", "reviewed_commit": self.commit,
             "reviewed_base_commit": self.base,
             "contract_sha256": review_input.contract_sha256,
             "review_input_evidence_id": review_input.id},
        )
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_MISMATCH"):
            self.registry.record_review_outcome(
                replace(outcome, contract_sha256="0" * 64), evidence=evidence,
                review_attempt_id="review-attempt",
                expected_revision=self.registry.dispatch_control()["revision"],
                operation_id="review-outcome:invalid-proof",
            )
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(12))
        attempt = next(item for item in snapshot.attempts if item["id"] == "review-attempt")
        package = next(item for item in snapshot.work_packages if item["id"] == "TASK-232")
        self.assertIsNone(attempt["ended_at"])
        self.assertIsNone(attempt["outcome"])
        self.assertEqual(package["status"], "ACTIVE")
        self.assertFalse([item for item in snapshot.review_outcomes if item["id"] == outcome.id])
        self.assertFalse([item for item in snapshot.evidence if item["id"] == evidence.id])
        self.assertTrue(any(
            item["package_id"] == "TASK-232"
            for item in self.registry.dispatch_snapshot(observed_at=self.stamp(12)).active_leases
        ))

        self.registry.record_review_outcome(
            outcome, evidence=evidence, review_attempt_id="review-attempt",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        final = self.registry.control_center_snapshot(observed_at=self.stamp(12))
        attempt = next(item for item in final.attempts if item["id"] == "review-attempt")
        self.assertEqual(attempt["outcome"], "SUCCEEDED")
        self.assertEqual(
            datetime.fromisoformat(attempt["ended_at"].replace("Z", "+00:00")),
            datetime.fromisoformat(self.stamp(11)),
        )
        self.assertFalse([
            item for item in self.registry.dispatch_snapshot(observed_at=self.stamp(12)).active_leases
            if item["package_id"] == "TASK-232"
        ])
        self.assertEqual([item["state"] for item in final.review_outcomes if item["id"] == outcome.id],
                         ["APPROVED"])
        self.assertEqual([item["id"] for item in final.evidence if item["id"] == evidence.id],
                         [evidence.id])


if __name__ == "__main__":
    unittest.main()
