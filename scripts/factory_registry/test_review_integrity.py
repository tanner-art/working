from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.factory_registry import (
    Evidence,
    Feature,
    Lane,
    PackageKind,
    RegistryConflict,
    ReviewOutcome,
    ReviewOutcomeState,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
)


def contract_digest(value):
    encoded = json.dumps(
        value, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ReviewIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.registry = SQLiteRegistry(Path(self.temporary.name) / "registry.sqlite3")
        self.registry.initialize()
        self.registry.register_feature(Feature("F", "Feature", 10, TaskStatus.READY))
        self.registry.register_worker(Worker(
            "implementer", "Implementer", ("code",), (Lane.PLATFORM,),
            usage_state="GREEN",
        ))
        self.registry.register_worker(Worker(
            "reviewer", "Reviewer", ("review",), (Lane.ASSURANCE,),
            usage_state="GREEN",
        ))
        self.registry.register_work_package(WorkPackage(
            "IMPLEMENT", "F", "Implement", "PLATFORM", Lane.PLATFORM,
            ("code",), 10, ("Implement it",), status=TaskStatus.READY,
        ))
        self.registry.register_work_package(WorkPackage(
            "REVIEW", "F", "Review", "ASSURANCE", Lane.ASSURANCE,
            ("review",), 9, ("Review it",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("IMPLEMENT",),
        ))
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="review integrity test",
        )
        self.contract = {
            "task": "IMPLEMENT", "paths": ["src/example.ts"],
            "instructions": "Implement the exact contract.",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def complete_implementation(self, *, with_contract=True):
        revision = self.registry.dispatch_control()["revision"]
        lease = self.registry.acquire_lease(
            "IMPLEMENT", "implementer", acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T11:01:00Z",
            expected_dispatch_revision=revision,
        )
        diagnostics = {}
        if with_contract:
            diagnostics = {
                "task_contract": self.contract,
                "task_contract_sha256": contract_digest(self.contract),
            }
        revision = self.registry.dispatch_control()["revision"]
        self.registry.begin_attempt_runtime(
            "impl-attempt", package_id="IMPLEMENT", worker_id="implementer",
            runner_pid=101, started_at="2026-09-25T10:02:00Z",
            expected_revision=revision, provider_diagnostics=diagnostics,
        )
        self.registry.record_attempt_delivery(
            "impl-attempt", branch="runner/implement",
            base_commit="b" * 40, implementation_commit="a" * 40,
            pr_url="https://github.com/tanner-art/working/pull/999",
            validation_evidence=Evidence(
                "validation:impl-attempt", "IMPLEMENT", "validation", None,
                "Validation passed", "2026-09-25T10:10:00Z",
                {"attempt_id": "impl-attempt"},
            ),
        )
        self.registry.finish_attempt_runtime(
            "impl-attempt", ended_at="2026-09-25T10:11:00Z",
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="implementation delivered",
        )
        return lease

    def begin_review(self, reviewer="reviewer"):
        revision = self.registry.dispatch_control()["revision"]
        self.registry.acquire_lease(
            "REVIEW", reviewer, acquired_at="2026-09-25T10:12:00Z",
            expires_at="2026-09-25T11:12:00Z",
            expected_dispatch_revision=revision,
        )
        revision = self.registry.dispatch_control()["revision"]
        self.registry.begin_attempt_runtime(
            "review-attempt", package_id="REVIEW", worker_id=reviewer,
            runner_pid=102, started_at="2026-09-25T10:13:00Z",
            expected_revision=revision,
        )

    def test_exact_review_input_and_structured_approval_complete_both_packages(self):
        self.complete_implementation()
        self.begin_review()
        review_input = self.registry.prepare_review_input(
            "REVIEW", reviewer_worker_id="reviewer",
            review_attempt_id="review-attempt", requested_at="2026-09-25T10:14:00Z",
        )
        self.assertEqual(review_input.implementation_commit, "a" * 40)
        self.assertEqual(review_input.base_commit, "b" * 40)
        self.assertEqual(review_input.contract_content, self.contract)
        self.assertEqual(review_input.validation_evidence_ids, ("validation:impl-attempt",))
        replayed = self.registry.prepare_review_input(
            "REVIEW", reviewer_worker_id="reviewer",
            review_attempt_id="review-attempt", requested_at="2026-09-25T10:15:00Z",
        )
        self.assertEqual(replayed, review_input)
        self.registry.finish_attempt_runtime(
            "review-attempt", ended_at="2026-09-25T10:20:00Z",
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="structured verdict returned",
        )
        verdict = Evidence(
            "review-verdict", "REVIEW", "review", None, "Approved",
            "2026-09-25T10:20:00Z", {
                "schema_version": 1,
                "attempt_id": "review-attempt",
                "decision": "APPROVED",
                "review_input_evidence_id": review_input.evidence_id,
                "reviewed_commit": "a" * 40,
            },
        )
        self.registry.record_review_outcome(
            ReviewOutcome(
                "review-outcome", "REVIEW", "IMPLEMENT", "implementer", "reviewer",
                review_input.requested_at, "2026-09-25T10:20:00Z",
                ReviewOutcomeState.APPROVED, findings=("Contract satisfied",),
                approval_evidence_ids=(verdict.id,),
            ),
            evidence=verdict,
        )
        states = {
            item["id"]: item["status"]
            for item in self.registry.control_center_snapshot(
                observed_at="2026-09-25T10:21:00Z"
            ).work_packages
        }
        self.assertEqual(states, {"IMPLEMENT": "DONE", "REVIEW": "DONE"})

    def test_missing_contract_cannot_produce_review_input(self):
        self.complete_implementation(with_contract=False)
        self.begin_review()
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_CONTRACT_MISSING"):
            self.registry.prepare_review_input(
                "REVIEW", reviewer_worker_id="reviewer",
                review_attempt_id="review-attempt",
                requested_at="2026-09-25T10:14:00Z",
            )

    def test_verdict_for_wrong_commit_or_another_attempt_is_not_approval(self):
        self.complete_implementation()
        self.begin_review()
        review_input = self.registry.prepare_review_input(
            "REVIEW", reviewer_worker_id="reviewer",
            review_attempt_id="review-attempt", requested_at="2026-09-25T10:14:00Z",
        )
        self.registry.finish_attempt_runtime(
            "review-attempt", ended_at="2026-09-25T10:20:00Z",
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="structured verdict returned",
        )
        for evidence_id, metadata in (
            ("wrong-commit", {
                "schema_version": 1, "attempt_id": "review-attempt",
                "decision": "APPROVED",
                "review_input_evidence_id": review_input.evidence_id,
                "reviewed_commit": "c" * 40,
            }),
            ("wrong-attempt", {
                "schema_version": 1, "attempt_id": "some-other-attempt",
                "decision": "APPROVED",
                "review_input_evidence_id": review_input.evidence_id,
                "reviewed_commit": "a" * 40,
            }),
        ):
            with self.subTest(evidence_id=evidence_id):
                with self.assertRaisesRegex(
                    RegistryConflict,
                    "STRUCTURED_REVIEW_VERDICT_REQUIRED|REVIEW_EVIDENCE_MISMATCH",
                ):
                    self.registry.record_review_outcome(
                        ReviewOutcome(
                            f"outcome-{evidence_id}", "REVIEW", "IMPLEMENT",
                            "implementer", "reviewer", review_input.requested_at,
                            "2026-09-25T10:20:00Z", ReviewOutcomeState.APPROVED,
                            approval_evidence_ids=(evidence_id,),
                        ),
                        evidence=Evidence(
                            evidence_id, "REVIEW", "review", None, "Forged",
                            "2026-09-25T10:20:00Z", metadata,
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
