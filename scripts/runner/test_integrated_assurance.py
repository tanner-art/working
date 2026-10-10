"""Adversarial exact-artifact assurance tests; no live Registry is touched."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from integrated_assurance import parse_assurance_input, verify_integrated_source
from registry_control import queue_contract_digest
from runner import materialize_review_packet
from task_readiness import registration_proof
from scripts.factory_registry.models import (
    Evidence, Feature, Lane, PackageKind, ReviewOutcomeState, ReviewVerdict,
    TaskStatus, Worker, WorkPackage,
)
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.sqlite_registry import SQLiteRegistry


class IntegratedAssuranceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write("docs/PLAN.md", "plan")
        self.write("src/feature.py", "before")
        self.write("tests/test_feature.py", "test")
        self.commit("base")
        subprocess.run(["git", "-C", str(self.repo), "branch", "-M", "main"], check=True)
        self.base = self.git("rev-parse", "HEAD")
        self.write("src/feature.py", "after")
        self.commit("integrated feature")
        self.integrated = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.registry = SQLiteRegistry(self.root / "registry.sqlite")
        self.registry.initialize()
        self.registry.register_feature(Feature("F", "Feature", 10, TaskStatus.READY))
        for worker in (
            Worker("builder", "Builder", ("code",), (Lane.FEATURE,)),
            Worker("claude", "Claude", ("independent-review",), (Lane.ASSURANCE,)),
        ):
            self.registry.register_worker(worker)
        self.registry.register_work_package(WorkPackage(
            "TASK-1", "F", "Feature", "PRODUCT", Lane.FEATURE, ("code",), 10,
            ("feature works",), status=TaskStatus.DONE,
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK-2", "F", "Review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 10, ("reviewed",), status=TaskStatus.DONE,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-1",),
        ))
        # Test-only fixture: earlier independent review completed through the
        # standard path in production. Seed its terminal rows, not a fake
        # runtime or a production Registry, to isolate assurance constraints.
        with self.registry._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("review-evidence", "TASK-2", "review", "https://github.com/o/r/pull/1",
                 "approved", self.now.isoformat(),
                 json.dumps({"reviewed_commit": self.integrated})),
            )
            connection.execute(
                "INSERT INTO review_outcomes(id,review_package_id,target_package_id,"
                "implementer_worker_id,reviewer_worker_id,requested_at,decided_at,state,"
                "findings_json,changes_requested_json,approval_evidence_ids_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("review-outcome", "TASK-2", "TASK-1", "builder", "claude",
                 self.now.isoformat(), self.now.isoformat(), "APPROVED", "[]", "[]",
                 '["review-evidence"]'),
            )
            connection.commit()
        self.contract = {
            "schema_version": 2, "task": "TASK-3", "kind": "EVALUATION",
            "lane": "ASSURANCE", "instructions": "Review one integrated SHA.",
            "paths": ["docs/PLAN.md"], "depends_on": [1],
            "readiness": {
                "base_commit": self.integrated,
                "planning_paths": ["docs/PLAN.md"],
                "existing_paths": ["docs/PLAN.md"], "new_paths": [],
                "integration_paths": ["docs/PLAN.md"],
                "test_paths": ["docs/PLAN.md"],
                "dependency_kinds": {"TASK-1": "integration"},
            },
        }
        proof = registration_proof(
            self.contract, repository=self.repo, target_ref="main",
            acceptance_criteria=("visible feature works",),
        )
        self.registry.register_work_package(WorkPackage(
            "TASK-3", "F", "Integrated assurance", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 10, ("visible feature works",),
            status=TaskStatus.ON_DECK, kind=PackageKind.EVALUATION,
            dependency_ids=("TASK-1",), provider_diagnostics={
                "readiness_schema_version": 2,
                "queue_contract_sha256": queue_contract_digest(self.contract),
                "readiness_proof": proof, "exclusive_paths": ["docs/PLAN.md"],
            },
        ))
        self.registry.bind_legacy_package_source(
            "TASK-3", github_issue=3, queue_contract=self.contract,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=self.now.isoformat(),
        )
        self.registry.record_evidence(Evidence(
            "integration-receipt", "TASK-1", "integration-acceptance",
            "https://github.com/o/r/pull/1", "Integrated on main", self.now.isoformat(),
            {"implementation_commit": self.integrated,
             "pr_url": "https://github.com/o/r/pull/1",
             "review_outcome_id": "review-outcome", "review_evidence_id": "review-evidence",
             "merged_main_commit": self.integrated, "merged_main_tree": self.tree,
             "inclusion_mode": "ancestry", "changed_paths": ["src/feature.py"]},
        ))
        self.registry.record_evidence(Evidence(
            "matrix-proof", "TASK-3", "assurance-matrix", None,
            "Observed feature", self.now.isoformat(),
            {"criterion": "visible feature works", "integrated_commit": self.integrated,
             "result": "PASS"},
        ))
        packet = materialize_review_packet(
            self.root, implementation_attempt_id=f"integrated:{self.integrated}",
            base_commit=self.base, implementation_commit=self.integrated,
            contract=self.contract, validation_evidence={"ci": "fixture"},
            diff=self.git("diff", self.base, self.integrated),
            changed_files=["src/feature.py"],
        )
        self.meta = {
            "schema_version": 1, "package_id": "TASK-3",
            "integrated_commit": self.integrated, "integrated_tree": self.tree,
            "base_commit": self.base, "target_ref": "main",
            "ordered_parent_shas": [self.integrated],
            "included_packages": [{
                "package_id": "TASK-1", "implementation_commit": self.integrated,
                "pr_url": "https://github.com/o/r/pull/1",
                "review_package_id": "TASK-2", "review_outcome_id": "review-outcome",
                "review_evidence_id": "review-evidence",
                "integration_receipt_id": "integration-receipt",
            }],
            "acceptance_matrix": [{"criterion": "visible feature works",
                                   "result": "PASS", "evidence_id": "matrix-proof"}],
            "ci": {"commit": self.integrated, "state": "SUCCESS",
                   "run_url": "https://github.com/o/r/actions/runs/123"},
            "contract_sha256": queue_contract_digest(self.contract),
            "review_packet": packet,
        }

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def commit(self, message):
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", message], check=True)

    def evidence(self, meta=None):
        return Evidence("assurance-input", "TASK-3", "integrated-assurance-input",
                        self.meta["ci"]["run_url"], "Exact integrated input",
                        self.now.isoformat(), meta or self.meta)

    def test_input_requires_pinned_approved_ancestors_and_matrix(self):
        before = self.registry.dispatch_control()["revision"]
        self.assertEqual(self.registry.record_integrated_assurance_input(
            self.evidence(), expected_revision=before,
        ), before + 1)
        self.assertEqual(self.registry.integrated_assurance_input("TASK-3").integrated_commit,
                         self.integrated)
        with self.assertRaisesRegex(RegistryConflict, "OPERATION_ID_REUSED"):
            self.registry.record_integrated_assurance_input(
                self.evidence({**self.meta, "integrated_commit": "a" * 40}),
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        self.registry.transition_work_package(
            "TASK-3", expected_status=TaskStatus.ON_DECK, new_status=TaskStatus.READY,
            changed_at=self.now.isoformat(),
        )

    def test_missing_or_changes_requested_ancestor_blocks(self):
        package = {"id": "TASK-3", "kind": "EVALUATION", "lane": "ASSURANCE",
                   "acceptance_criteria": ["visible feature works"],
                   "provider_diagnostics": {"queue_contract_sha256": queue_contract_digest(self.contract)}}
        evidence = {"id": "assurance-input", "package_id": "TASK-3",
                    "kind": "integrated-assurance-input", "recorded_at": self.now.isoformat(),
                    "metadata": self.meta}
        review_facts = {"TASK-1": {"id": "review-outcome", "state": "CHANGES_REQUESTED",
                                   "review_package_id": "TASK-2", "implementer_worker_id": "builder",
                                   "reviewer_worker_id": "claude",
                                   "approval_evidence_ids": ["review-evidence"],
                                   "reviewed_commit": self.integrated,
                                   "review_pr_url": "https://github.com/o/r/pull/1"}}
        receipts = {"TASK-1": {"id": "integration-receipt", "package_id": "TASK-1",
                               "kind": "integration-acceptance", "metadata": {
                                   "implementation_commit": self.integrated,
                                   "pr_url": "https://github.com/o/r/pull/1",
                                   "review_outcome_id": "review-outcome",
                                   "review_evidence_id": "review-evidence",
                                   "merged_main_commit": self.integrated,
                                   "merged_main_tree": self.tree,
                                   "inclusion_mode": "ancestry", "changed_paths": ["src/feature.py"]}}}
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_ANCESTOR_NOT_APPROVED"):
            parse_assurance_input(
                evidence, package=package, dependencies=("TASK-1",),
                review_facts=review_facts, receipts=receipts,
            )

    def test_bad_receipt_and_matrix_are_rejected(self):
        bad = {**self.meta, "included_packages": [{**self.meta["included_packages"][0],
                                                   "integration_receipt_id": "missing"}]}
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_ANCESTOR_NOT_APPROVED"):
            self.registry.record_integrated_assurance_input(
                self.evidence(bad), expected_revision=self.registry.dispatch_control()["revision"],
            )
        bad = {**self.meta, "acceptance_matrix": [{**self.meta["acceptance_matrix"][0],
                                                  "evidence_id": "missing"}]}
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_MATRIX_EVIDENCE_INVALID"):
            self.registry.record_integrated_assurance_input(
                replace(self.evidence(bad), id="assurance-input-2"),
                expected_revision=self.registry.dispatch_control()["revision"],
            )

    def test_review_approval_must_bind_the_included_pr(self):
        with self.registry._connection() as connection:
            connection.execute("UPDATE evidence SET uri=? WHERE id='review-evidence'",
                               ("https://github.com/o/r/pull/9",))
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_ANCESTOR_NOT_APPROVED"):
            self.registry.validate_integrated_assurance_candidate(self.evidence())

    def test_source_requires_exact_main_pr_tree_ci_and_diff(self):
        value = self.registry.validate_integrated_assurance_candidate(self.evidence())

        def github(*args):
            if args[0] == "api":
                return json.dumps({"object": {"sha": self.integrated}})
            if args[0] == "pr":
                return json.dumps({"state": "MERGED", "headRefOid": self.integrated,
                                   "mergeCommit": {"oid": self.integrated}})
            if args[0] == "run":
                return json.dumps({"headSha": self.integrated, "status": "completed",
                                   "conclusion": "success", "workflowName": "Validate app",
                                   "url": self.meta["ci"]["run_url"]})
            raise AssertionError(args)

        self.assertTrue(verify_integrated_source(
            value, repository=self.repo, github=github, repository_name="o/r",
        ))
        changed = replace(value, integrated_tree="a" * 40)
        self.assertFalse(verify_integrated_source(
            changed, repository=self.repo, github=github, repository_name="o/r",
        ))
        wrong_step_paths = replace(value, integration_receipts=({**value.integration_receipts[0],
                                                                  "changed_paths": ["docs/PLAN.md"]},))
        self.assertFalse(verify_integrated_source(
            wrong_step_paths, repository=self.repo, github=github, repository_name="o/r",
        ))
        self.assertFalse(verify_integrated_source(
            value, repository=self.repo,
            github=lambda *args: json.dumps({"object": {"sha": self.base}}),
            repository_name="o/r",
        ))

    def begin_assurance_attempt(self):
        self.registry.record_integrated_assurance_input(
            self.evidence(), expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.transition_work_package(
            "TASK-3", expected_status=TaskStatus.ON_DECK,
            new_status=TaskStatus.READY, changed_at=self.now.isoformat(),
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=self.now.isoformat(), reason="exact assurance fixture",
            bounded_run={"run_id": "assurance-fixture", "package_ids": ["TASK-3"],
                         "deadline": (self.now + timedelta(minutes=10)).isoformat(),
                         "base_ref": "main", "parent_limit": 1},
        )
        lease = self.registry.acquire_lease(
            "TASK-3", "claude", acquired_at=self.now.isoformat(),
            expires_at=(self.now + timedelta(minutes=5)).isoformat(),
            expected_dispatch_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.begin_attempt_runtime(
            "assurance-attempt", package_id="TASK-3", worker_id="claude",
            runner_pid=os.getpid(), started_at=self.now.isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.assertTrue(lease.id)

    def test_verdict_reviewer_overlap_blocks(self):
        self.begin_assurance_attempt()
        verdict = ReviewVerdict(ReviewOutcomeState.APPROVED, self.integrated,
                                self.base, queue_contract_digest(self.contract))
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_REVIEWER_IMPLEMENTED_INCLUDED_PACKAGE"):
            self.registry.record_integrated_assurance_verdict(
                "TASK-3", "assurance-attempt", "builder", "assurance-input", verdict,
                expected_revision=revision, decided_at=datetime.now(timezone.utc).isoformat(),
            )

    def test_verdict_wrong_sha_blocks(self):
        self.begin_assurance_attempt()
        verdict = ReviewVerdict(ReviewOutcomeState.APPROVED, self.integrated,
                                self.base, queue_contract_digest(self.contract))
        wrong = replace(verdict, reviewed_commit="a" * 40)
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_VERDICT_TARGET_MISMATCH"):
            self.registry.record_integrated_assurance_verdict(
                "TASK-3", "assurance-attempt", "claude", "assurance-input", wrong,
                expected_revision=self.registry.dispatch_control()["revision"],
                decided_at=datetime.now(timezone.utc).isoformat(),
            )

    def test_verdict_closes_exact_attempt_once(self):
        self.begin_assurance_attempt()
        verdict = ReviewVerdict(ReviewOutcomeState.APPROVED, self.integrated,
                                self.base, queue_contract_digest(self.contract))
        revision = self.registry.dispatch_control()["revision"]
        result = self.registry.record_integrated_assurance_verdict(
            "TASK-3", "assurance-attempt", "claude", "assurance-input", verdict,
            expected_revision=revision, decided_at=datetime.now(timezone.utc).isoformat(),
        )
        self.assertGreater(result, revision)
        snapshot = self.registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
        package = next(item for item in snapshot.work_packages if item["id"] == "TASK-3")
        self.assertEqual(package["status"], "DONE")
        self.assertFalse(snapshot.active_leases)
        with self.registry._connection() as connection:
            rows = connection.execute(
                "SELECT metadata_json FROM evidence WHERE package_id='TASK-3' "
                "AND kind='integrated-assurance-verdict'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["metadata_json"])["reviewed_commit"], self.integrated)

    def test_changes_requested_does_not_approve(self):
        self.begin_assurance_attempt()
        verdict = ReviewVerdict(ReviewOutcomeState.CHANGES_REQUESTED, self.integrated,
                                self.base, queue_contract_digest(self.contract),
                                findings=("missing device evidence",),
                                changes_requested=("Run physical device check",))
        self.registry.record_integrated_assurance_verdict(
            "TASK-3", "assurance-attempt", "claude", "assurance-input", verdict,
            expected_revision=self.registry.dispatch_control()["revision"],
            decided_at=datetime.now(timezone.utc).isoformat(),
        )
        snapshot = self.registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
        package = next(item for item in snapshot.work_packages if item["id"] == "TASK-3")
        self.assertEqual(package["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
