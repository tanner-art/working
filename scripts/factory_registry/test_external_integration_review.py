"""End-to-end Registry proof for review of an externally integrated commit."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.factory_registry.models import (
    Evidence, Feature, Lane, PackageKind, ReviewInput, ReviewOutcome,
    ReviewOutcomeState, TaskStatus, Worker, WorkPackage,
)
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.operator import OperatorError, record_external_integration_review_input
from scripts.factory_registry.control_center_projection import (
    ControlCenterProjectionError, project_control_center,
)
from scripts.factory_registry.sqlite_registry import SQLiteRegistry, _review_contract_sha256
from scripts.runner.registry_control import RunnerRegistryControl


class ExternalIntegrationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = SQLiteRegistry(self.root / "registry.sqlite3")
        self.registry.initialize()
        self.now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=10)
        self.contract = {"task": "TASK-231", "paths": ["scripts/factory_registry/sqlite_registry.py"],
                         "instructions": "Prove CP-02 review integrity.", "depends_on": []}
        self.review_contract = {"task": "TASK-232", "paths": ["docs/factory/CP_02_FINAL_PROOF_REVIEW.md"],
                                "instructions": "Independently review CP-02.", "depends_on": [231]}
        self.commit, self.base, self.merge, self.head = "a" * 40, "b" * 40, "c" * 40, "d" * 40
        self.pr = "https://github.com/tanner-art/working/pull/352"
        self.registry.register_feature(Feature("CP-02", "CP-02", 10, TaskStatus.READY))
        self.registry.register_work_package(WorkPackage(
            "TASK-231", "CP-02", "Implementation", "CONTROL_PLANE", Lane.PLATFORM,
            ("implementation",), 10, ("proof",), status=TaskStatus.READY,
            provider_diagnostics={"queue_contract_sha256": _review_contract_sha256(self.contract)},
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK-232", "CP-02", "Independent review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 9, ("strict verdict",), status=TaskStatus.ON_DECK,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-231",),
            provider_diagnostics={"queue_contract_sha256": _review_contract_sha256(self.review_contract)},
        ))
        self.registry.bind_legacy_package_source(
            "TASK-232", github_issue=232, queue_contract=self.review_contract,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=self.stamp(0),
        )
        for worker, capabilities, lanes in (
            ("codex-a", ("implementation", "independent-review"),
             (Lane.PLATFORM, Lane.ASSURANCE)),
            ("claude", ("independent-review",), (Lane.ASSURANCE,)),
        ):
            self.registry.register_worker(Worker(worker, worker, capabilities, lanes,
                                                 last_heartbeat_at=self.stamp(0), usage_state="NORMAL"))
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE",
            kill_switch_engaged=False, changed_at=self.stamp(1), reason="fixture failed attempt",
        )
        self.registry.acquire_lease("TASK-231", "codex-a", acquired_at=self.stamp(2),
                                    expires_at=self.stamp(120))
        self.registry.begin_attempt_runtime(
            "old-failed-attempt", package_id="TASK-231", worker_id="codex-a",
            runner_pid=os.getpid(), started_at=self.stamp(3),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "old-failed-attempt", ended_at=self.stamp(4), outcome="FAILED",
            next_status=TaskStatus.BLOCKED, reason="original runner failed",
            failure_detail="blank line at EOF",
        )
        self.registry.engage_dispatch_kill_switch(changed_at=self.stamp(5), reason="fixture drained")
        RunnerRegistryControl(self.root / "registry.sqlite3").finalize_paused(reason="fixture drained")

    def stamp(self, seconds):
        return (self.now + timedelta(seconds=seconds)).isoformat()

    def add_older_failed_author(self):
        with self.registry._connection() as connection:
            connection.execute(
                "INSERT INTO attempts (id, package_id, worker_id, started_at, ended_at, outcome, "
                "provider_diagnostics_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("older-failed-attempt", "TASK-231", "claude", self.stamp(0),
                 self.stamp(1), "FAILED", "{}"),
            )

    def review_input(self):
        packet = self.root / "packet"
        packet.mkdir()
        contents = {
            "base-to-implementation.diff": b"diff --git a/x b/x\n",
            "changed-files.txt": b"scripts/factory_registry/sqlite_registry.py\n",
            "contract.json": json.dumps(self.contract, sort_keys=True).encode(),
            "validation-evidence.json": b'{"containing_merge_ci":"success"}',
        }
        files = {}
        for name, content in contents.items():
            (packet / name).write_bytes(content)
            files[name] = hashlib.sha256(content).hexdigest()
        manifest = {"schema_version": 1, "implementation_attempt_id": "external-integration:bridge-1",
                    "implementation_commit": self.commit, "base_commit": self.base, "files": files}
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        (packet / "manifest.json").write_bytes(manifest_bytes)
        return ReviewInput(
            id="external-review-input", review_package_id="TASK-232", target_package_id="TASK-231",
            implementation_attempt_id="external-integration:bridge-1",
            implementation_commit=self.commit, base_commit=self.base, pr_url=self.pr,
            contract_sha256=_review_contract_sha256(self.contract), contract=self.contract,
            validation_evidence={
                "ci": {"state": "SUCCESS", "validated_commit": self.merge,
                       "contains_implementation_commit": self.commit, "pr_url": self.pr,
                       "run_url": "https://github.com/tanner-art/working/actions/runs/123"},
                "review_packet": {"path": str(packet),
                                  "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                                  "files": files},
            }, recorded_at=self.stamp(6),
            external_integration={"id": "bridge-1", "historical_commit": self.commit,
                                  "integration_commit": self.merge, "repository_head": self.head,
                                  "implementer_worker_id": "codex-a"},
        )

    def test_bridge_preserves_failure_and_requires_independent_structured_outcome(self):
        review_input = self.review_input()
        before = self.registry.control_center_snapshot(observed_at=self.stamp(6))
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "REGISTRY_REVISION_CHANGED"):
            self.registry.record_external_integration_review_input(review_input, expected_revision=revision - 1)
        revision = self.registry.dispatch_control()["revision"]
        accepted_revision = self.registry.record_external_integration_review_input(
            review_input, expected_revision=revision,
        )
        self.assertEqual(self.registry.record_external_integration_review_input(
            review_input, expected_revision=revision,
        ), accepted_revision)
        self.assertEqual(self.registry.dispatch_control()["revision"], accepted_revision)
        after = self.registry.control_center_snapshot(observed_at=self.stamp(7))
        self.assertEqual(before.attempts, after.attempts)
        self.assertEqual(after.attempts[-1]["outcome"], "FAILED")
        self.assertEqual(self.registry.review_implementer_worker("TASK-232"), "codex-a")
        statuses = {item["id"]: item["status"] for item in after.work_packages}
        self.assertEqual((statuses["TASK-231"], statuses["TASK-232"]), ("VERIFY_REVIEW", "READY"))
        self.assertEqual(len([item for item in after.evidence if item["package_id"] == "TASK-232"]), 1)
        self.assertFalse([item for item in after.review_outcomes if item["target_package_id"] == "TASK-231"])
        self.registry.set_dispatch_control(
            expected_revision=self.registry.dispatch_control()["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=self.stamp(8), reason="review fixture",
        )
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"):
            self.registry.acquire_lease("TASK-232", "codex-a", acquired_at=self.stamp(9),
                                        expires_at=self.stamp(120))
        self.registry.acquire_lease("TASK-232", "claude", acquired_at=self.stamp(9),
                                    expires_at=self.stamp(120))
        self.registry.begin_attempt_runtime(
            "review-attempt", package_id="TASK-232", worker_id="claude", runner_pid=os.getpid(),
            started_at=self.stamp(10), expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "review-attempt", ended_at=self.stamp(11), outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW, reason="review finished",
        )
        outcome = ReviewOutcome(
            id="external-verdict", review_package_id="TASK-232", target_package_id="TASK-231",
            implementer_worker_id="codex-a", reviewer_worker_id="claude",
            requested_at=review_input.recorded_at, decided_at=self.stamp(12),
            state=ReviewOutcomeState.APPROVED, findings=("Exact CP-02 proof accepted.",),
            approval_evidence_ids=("external-verdict-evidence",), reviewed_commit=self.commit,
            reviewed_base_commit=self.base, contract_sha256=review_input.contract_sha256,
            review_input_evidence_id=review_input.id, reviewer_attempt_id="review-attempt",
        )
        evidence = Evidence("external-verdict-evidence", "TASK-232", "review", self.pr,
                            "Structured independent review", self.stamp(11),
                            {"attempt_id": "review-attempt", "reviewed_commit": self.commit,
                             "reviewed_base_commit": self.base,
                             "contract_sha256": review_input.contract_sha256,
                             "review_input_evidence_id": review_input.id})
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_REQUEST_TIME_MISMATCH"):
            self.registry.record_review_outcome(
                replace(outcome, id="forged-request-time", requested_at=self.stamp(9)),
                evidence=evidence, expected_revision=self.registry.dispatch_control()["revision"],
            )
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"):
            self.registry.record_review_outcome(replace(outcome, implementer_worker_id="claude"),
                                                evidence=evidence, expected_revision=self.registry.dispatch_control()["revision"])
        self.registry.record_review_outcome(outcome, evidence=evidence,
                                            expected_revision=self.registry.dispatch_control()["revision"])
        final = self.registry.control_center_snapshot(observed_at=self.stamp(13))
        self.assertEqual({item["id"]: item["status"] for item in final.work_packages}["TASK-231"], "DONE")
        self.assertEqual(final.attempts[0]["outcome"], "FAILED")
        self.assertEqual(final.review_outcomes[-1]["state"], "APPROVED")
        projection = project_control_center(final)
        self.assertEqual(next(item for item in projection["reviews"]
                              if item["id"] == "external-verdict")["state"], "approved")
        forged_history = tuple(
            {**item, "integration_commit": "0" * 40} if item["id"] == "bridge-1" else item
            for item in final.historical_reconciliations
        )
        with self.assertRaisesRegex(ControlCenterProjectionError, "external review provenance"):
            project_control_center(replace(final, historical_reconciliations=forged_history))
        forged_evidence = tuple(
            {**item, "metadata": {**item["metadata"], "reviewed_commit": "0" * 40}}
            if item["id"] == "external-verdict-evidence" else item
            for item in final.evidence
        )
        with self.assertRaisesRegex(ControlCenterProjectionError, "external review evidence"):
            project_control_center(replace(final, evidence=forged_evidence))

    def test_bridge_rejects_mismatched_contract_and_packet_without_mutation(self):
        review_input = self.review_input()
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_PACKET_CONTRACT_MISMATCH"):
            changed = {**self.contract, "instructions": "different"}
            self.registry.record_external_integration_review_input(
                replace(review_input, contract=changed,
                        contract_sha256=_review_contract_sha256(changed)), expected_revision=revision,
            )
        (Path(review_input.validation_evidence["review_packet"]["path"]) / "contract.json").write_text("{}")
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_PACKET_FILE_MISMATCH"):
            self.registry.record_external_integration_review_input(review_input, expected_revision=revision)
        after = self.registry.control_center_snapshot(observed_at=self.stamp(7))
        self.assertEqual(after.revision, revision)
        self.assertEqual(after.attempts[0]["outcome"], "FAILED")

    def test_bounded_external_review_activation_preserves_unrelated_ready_work(self):
        review_input = self.review_input()
        self.registry.record_external_integration_review_input(
            review_input, expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.register_feature(Feature("OTHER", "Other work", 1, TaskStatus.READY))
        self.registry.register_work_package(WorkPackage(
            "TASK-999", "OTHER", "Unrelated", "CONTROL_PLANE", Lane.PLATFORM,
            ("implementation",), 1, ("preserve",), status=TaskStatus.READY,
        ))
        scope = {"run_id": "cp02-review-only", "package_ids": ["TASK-232"],
                 "deadline": self.stamp(3600), "base_ref": "main", "parent_limit": 1}
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_CONTROL_COMPARE_AND_SWAP_FAILED"):
            self.registry.set_dispatch_control(
                expected_revision=revision - 1, expected_mode="PAUSED", new_mode="LIVE",
                kill_switch_engaged=False, changed_at=self.stamp(8), reason="stale review run",
                bounded_run=scope,
            )
        live_revision = self.registry.set_dispatch_control(
            expected_revision=revision, expected_mode="PAUSED", new_mode="LIVE",
            kill_switch_engaged=False, changed_at=self.stamp(8), reason="bounded review run",
            bounded_run=scope,
        )
        self.assertEqual(self.registry.dispatch_control()["bounded_run"]["package_ids"], ["TASK-232"])
        with self.assertRaisesRegex(RegistryConflict, "RUN_PACKAGE_NOT_ALLOWLISTED"):
            self.registry.acquire_lease("TASK-999", "codex-a", acquired_at=self.stamp(9),
                                        expires_at=self.stamp(120), expected_dispatch_revision=live_revision)
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"):
            self.registry.acquire_lease("TASK-232", "codex-a", acquired_at=self.stamp(9),
                                        expires_at=self.stamp(120), expected_dispatch_revision=live_revision)
        self.registry.acquire_lease("TASK-232", "claude", acquired_at=self.stamp(9),
                                    expires_at=self.stamp(120), expected_dispatch_revision=live_revision)
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(10))
        self.assertEqual({item["id"]: item["status"] for item in snapshot.work_packages}["TASK-999"], "READY")
        self.assertEqual(snapshot.attempts[0]["outcome"], "FAILED")

    def test_bounded_external_review_activation_rejects_tampered_history(self):
        review_input = self.review_input()
        self.registry.record_external_integration_review_input(
            review_input, expected_revision=self.registry.dispatch_control()["revision"],
        )
        scope = {"run_id": "cp02-tamper", "package_ids": ["TASK-232"],
                 "deadline": self.stamp(3600), "base_ref": "main", "parent_limit": 1}
        revision = self.registry.dispatch_control()["revision"]
        with self.registry._connection() as connection:
            # Simulate corrupted persisted provenance; normal writes are append-only.
            connection.execute("DROP TRIGGER historical_package_reconciliations_are_append_only_update")
            connection.execute(
                "UPDATE historical_package_reconciliations SET historical_commit=? WHERE id=?",
                ("f" * 40, "bridge-1"),
            )
        with self.assertRaisesRegex(RegistryConflict, "EXTERNAL_INTEGRATION_PROVENANCE_INVALID"):
            self.registry.set_dispatch_control(
                expected_revision=revision, expected_mode="PAUSED", new_mode="LIVE",
                kill_switch_engaged=False, changed_at=self.stamp(8), reason="tampered review run",
                bounded_run=scope,
            )
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)

    def test_bounded_external_review_activation_rejects_multiple_failed_authors(self):
        review_input = self.review_input()
        self.registry.record_external_integration_review_input(
            review_input, expected_revision=self.registry.dispatch_control()["revision"],
        )
        # The older attempt is by a different worker, so the latest failed
        # attempt still matches the bridge but does not prove unique authorship.
        self.add_older_failed_author()
        revision = self.registry.dispatch_control()["revision"]
        scope = {"run_id": "cp02-multiple-authors", "package_ids": ["TASK-232"],
                 "deadline": self.stamp(3600), "base_ref": "main", "parent_limit": 1}
        with self.assertRaisesRegex(RegistryConflict, "EXTERNAL_INTEGRATION_PROVENANCE_INVALID"):
            self.registry.set_dispatch_control(
                expected_revision=revision, expected_mode="PAUSED", new_mode="LIVE",
                kill_switch_engaged=False, changed_at=self.stamp(8), reason="ambiguous authorship",
                bounded_run=scope,
            )
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_bridge_refuses_multiple_failed_authors_before_recording(self):
        self.add_older_failed_author()
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "HISTORICAL_FAILED_ATTEMPT_REQUIRED"):
            self.registry.record_external_integration_review_input(
                self.review_input(), expected_revision=revision,
            )
        self.assertEqual(self.registry.dispatch_control()["revision"], revision + 1)
        self.assertEqual({item["id"]: item["status"] for item in
                          self.registry.control_center_snapshot(observed_at=self.stamp(6)).work_packages}["TASK-232"],
                         "ON_DECK")

    def test_mixed_scope_cannot_lease_review_after_ambiguous_history(self):
        self.registry.record_external_integration_review_input(
            self.review_input(), expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.add_older_failed_author()
        self.registry.register_feature(Feature("OTHER", "Other work", 1, TaskStatus.READY))
        self.registry.register_worker(Worker(
            "reviewer2", "reviewer2", ("independent-review",), (Lane.ASSURANCE,),
            last_heartbeat_at=self.stamp(7), usage_state="NORMAL",
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK-999", "OTHER", "Unrelated", "CONTROL_PLANE", Lane.PLATFORM,
            ("implementation",), 1, ("preserve",), status=TaskStatus.READY,
        ))
        scope = {"run_id": "cp02-mixed", "package_ids": ["TASK-232", "TASK-999"],
                 "deadline": self.stamp(3600), "base_ref": "main", "parent_limit": 1}
        live_revision = self.registry.set_dispatch_control(
            expected_revision=self.registry.dispatch_control()["revision"],
            expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.stamp(8), reason="mixed review run", bounded_run=scope,
        )
        with self.assertRaisesRegex(RegistryConflict, "EXTERNAL_INTEGRATION_PROVENANCE_INVALID"):
            self.registry.review_implementer_worker("TASK-232")
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_IMPLEMENTER_PROVENANCE_REQUIRED"):
            self.registry.acquire_lease(
                "TASK-232", "reviewer2", acquired_at=self.stamp(9),
                expires_at=self.stamp(120), expected_dispatch_revision=live_revision,
            )

    def test_external_approval_rejects_new_target_attempt_after_review_lease(self):
        review_input = self.review_input()
        self.registry.record_external_integration_review_input(
            review_input, expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.register_worker(Worker(
            "w3", "w3", ("implementation",), (Lane.PLATFORM,),
            last_heartbeat_at=self.stamp(7), usage_state="NORMAL",
        ))
        self.registry.set_dispatch_control(
            expected_revision=self.registry.dispatch_control()["revision"],
            expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.stamp(8), reason="unscoped review fixture",
        )
        self.registry.acquire_lease("TASK-232", "claude", acquired_at=self.stamp(9),
                                    expires_at=self.stamp(120))
        self.registry.transition_work_package(
            "TASK-231", expected_status=TaskStatus.VERIFY_REVIEW,
            new_status=TaskStatus.READY, changed_at=self.stamp(10),
        )
        first = self.registry.acquire_lease("TASK-231", "w3", acquired_at=self.stamp(11),
                                            expires_at=self.stamp(120))
        self.registry.begin_attempt_runtime(
            "w3-cancelled", package_id="TASK-231", worker_id="w3", runner_pid=os.getpid(),
            started_at=self.stamp(12), expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "w3-cancelled", ended_at=self.stamp(13), outcome="CANCELLED",
            next_status=TaskStatus.READY, reason="cancelled fixture",
        )
        self.assertIsNotNone(first.id)
        second = self.registry.acquire_lease("TASK-231", "w3", acquired_at=self.stamp(14),
                                             expires_at=self.stamp(120))
        self.registry.release_lease(
            second.id, released_at=self.stamp(15), reason="return to review",
            next_status=TaskStatus.VERIFY_REVIEW,
        )
        self.registry.begin_attempt_runtime(
            "review-after-change", package_id="TASK-232", worker_id="claude",
            runner_pid=os.getpid(), started_at=self.stamp(17),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "review-after-change", ended_at=self.stamp(18), outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW, reason="review fixture",
        )
        outcome = ReviewOutcome(
            id="forged-review-verdict", review_package_id="TASK-232", target_package_id="TASK-231",
            implementer_worker_id="codex-a", reviewer_worker_id="claude",
            requested_at=self.stamp(16), decided_at=self.stamp(19),
            state=ReviewOutcomeState.APPROVED, findings=("claimed exact proof",),
            approval_evidence_ids=("forged-review-evidence",), reviewed_commit=self.commit,
            reviewed_base_commit=self.base, contract_sha256=review_input.contract_sha256,
            review_input_evidence_id=review_input.id, reviewer_attempt_id="review-after-change",
        )
        evidence = Evidence(
            "forged-review-evidence", "TASK-232", "review", self.pr, "Review fixture",
            self.stamp(18), {"attempt_id": "review-after-change", "reviewed_commit": self.commit,
                             "reviewed_base_commit": self.base,
                             "contract_sha256": review_input.contract_sha256,
                             "review_input_evidence_id": review_input.id},
        )
        with self.assertRaisesRegex(RegistryConflict, "EXTERNAL_INTEGRATION_PROVENANCE_INVALID"):
            self.registry.record_review_outcome(
                outcome, evidence=evidence,
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(20))
        self.assertEqual({item["id"]: item["status"] for item in snapshot.work_packages}["TASK-231"],
                         "VERIFY_REVIEW")
        self.assertFalse(snapshot.review_outcomes)

    def test_operator_checks_actual_git_ancestry_pr_and_merge_ci(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Factory Test")
        git("config", "user.email", "factory@example.test")
        source = repo / "source.txt"
        source.write_text("base\n")
        git("add", "source.txt")
        git("commit", "-q", "-m", "base")
        self.base = git("rev-parse", "HEAD")
        source.write_text("implementation\n")
        git("commit", "-qam", "implementation")
        self.commit = git("rev-parse", "HEAD")
        source.write_text("integrated\n")
        git("commit", "-qam", "merge-equivalent")
        self.merge = git("rev-parse", "HEAD")
        source.write_text("head\n")
        git("commit", "-qam", "head")
        self.head = git("rev-parse", "HEAD")
        review_input = self.review_input()
        raw_input = asdict(review_input)
        external = raw_input.pop("external_integration")
        raw_input.pop("contract_sha256")
        spec = {"repository": str(repo), "review_input": raw_input,
                "external_integration": external}
        pr = {"merged": True, "merge_commit_sha": self.merge, "html_url": self.pr}
        run = {"head_sha": self.merge, "name": "Validate app", "head_branch": "main",
               "status": "completed", "conclusion": "success",
               "html_url": "https://github.com/tanner-art/working/actions/runs/123"}
        revision = self.registry.dispatch_control()["revision"]
        args = (self.root / "registry.sqlite3", self.root / "config.json",
                self.root / "release", self.root / "preservation.json", self.head,
                revision, spec)
        with patch("scripts.factory_registry.operator.preflight"), \
                patch("scripts.factory_registry.operator._github_public_json",
                      side_effect=(pr, {**run, "conclusion": "failure"})):
            with self.assertRaisesRegex(OperatorError, "CI does not validate"):
                record_external_integration_review_input(*args)
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)
        with patch("scripts.factory_registry.operator.preflight"), \
                patch("scripts.factory_registry.operator._github_public_json",
                      side_effect=(pr, run)):
            result = record_external_integration_review_input(*args)
        self.assertFalse(result["review_passed"])
        self.assertEqual(self.registry.review_input("TASK-232")["implementation_commit"], self.commit)
        wrong = {**spec, "external_integration": {**external, "integration_commit": "f" * 40}}
        with self.assertRaises(OperatorError):
            record_external_integration_review_input(*args[:-1], wrong)
