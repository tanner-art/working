"""Fail-closed remediation provenance tests; never touches the live Registry."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from scripts.factory_registry.models import Evidence, Feature, Lane, PackageKind, TaskStatus, Worker, WorkPackage
from scripts.factory_registry.operator import verify_remediation_coverage_source
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.sqlite_registry import SQLiteRegistry


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RemediationCoverageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.registry = SQLiteRegistry(self.root / "registry.sqlite")
        self.registry.initialize()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.decided_at = (self.now - timedelta(minutes=1)).isoformat()
        self.recorded_at = self.now.isoformat()
        self.original_findings = ["Form was unreachable.", "Tests were missing."]
        self.original_requests = ["Wire the form and add tests."]
        self.reviewer_findings = ["Form is reachable from Review.", "Focused tests pass."]
        self.reviewed = "a" * 40
        self.base = "d" * 40
        self.contract_sha256 = "e" * 64
        self.merged = "b" * 40
        self.tree = "c" * 40
        self.pr = "https://github.com/o/r/pull/430"
        self.registry.register_feature(Feature("F", "Feature", 1, TaskStatus.READY))
        self.registry.register_worker(Worker("builder", "Builder", ("code",), (Lane.FEATURE,)))
        self.registry.register_worker(Worker("claude", "Claude", ("independent-review",), (Lane.ASSURANCE,)))
        for package_id, kind, status, lane in (
            ("TASK-177", PackageKind.PARENT, TaskStatus.VERIFY_REVIEW, Lane.FEATURE),
            ("TASK-178", PackageKind.REVIEW, TaskStatus.DONE, Lane.ASSURANCE),
            ("TASK-426", PackageKind.PARENT, TaskStatus.DONE, Lane.FEATURE),
            ("TASK-427", PackageKind.REVIEW, TaskStatus.DONE, Lane.ASSURANCE),
        ):
            self.registry.register_work_package(WorkPackage(
                package_id, "F", package_id, "TEST", lane,
                ("independent-review",) if kind == PackageKind.REVIEW else ("code",),
                1, ("exact behavior",), status=status, kind=kind,
            ))
        with self.registry._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO review_outcomes(id,review_package_id,target_package_id,"
                "implementer_worker_id,reviewer_worker_id,requested_at,decided_at,state,"
                "findings_json,changes_requested_json,approval_evidence_ids_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("original-verdict", "TASK-178", "TASK-177", "builder", "claude",
                 self.decided_at, self.decided_at, "CHANGES_REQUESTED",
                 json.dumps(self.original_findings), json.dumps(self.original_requests), "[]"),
            )
            connection.execute(
                "INSERT INTO review_outcomes(id,review_package_id,target_package_id,"
                "implementer_worker_id,reviewer_worker_id,requested_at,decided_at,state,"
                "findings_json,changes_requested_json,approval_evidence_ids_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("remediation-verdict", "TASK-427", "TASK-426", "builder", "claude",
                 self.decided_at, self.decided_at, "APPROVED",
                 json.dumps(self.reviewer_findings), "[]", '["review-evidence"]'),
            )
            for item in (
                ("review-evidence", "review", self.pr,
                 {"reviewed_commit": self.reviewed,
                  "reviewed_base_commit": self.base,
                  "contract_sha256": self.contract_sha256,
                  "review_input_evidence_id": "review-input"}),
                ("review-input", "review-input", self.pr,
                 {"target_package_id": "TASK-426", "implementation_commit": self.reviewed,
                  "base_commit": self.base, "contract_sha256": self.contract_sha256}),
            ):
                connection.execute(
                    "INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (item[0], "TASK-427", item[1], item[2], item[0],
                     self.decided_at, json.dumps(item[3])),
                )
            connection.commit()
        self.meta = {
            "schema_version": 1,
            "original_review_outcome_id": "original-verdict",
            "remediation_package_id": "TASK-426",
            "remediation_review_outcome_id": "remediation-verdict",
            "remediation_review_evidence_id": "review-evidence",
            "pr_url": self.pr,
            "reviewed_commit": self.reviewed,
            "merged_main_commit": self.merged,
            "merged_main_tree": self.tree,
            "finding_coverage": [
                {"source": "finding", "index": 0,
                 "source_sha256": sha(self.original_findings[0]),
                 "reviewer_findings": [{"index": 0, "sha256": sha(self.reviewer_findings[0])}],
                 "rationale": "Review now opens the form."},
                {"source": "finding", "index": 1,
                 "source_sha256": sha(self.original_findings[1]),
                 "reviewer_findings": [{"index": 1, "sha256": sha(self.reviewer_findings[1])}],
                 "rationale": "The new focused tests exercise this flow."},
                {"source": "change_request", "index": 0,
                 "source_sha256": sha(self.original_requests[0]),
                 "reviewer_findings": [
                     {"index": 0, "sha256": sha(self.reviewer_findings[0])},
                     {"index": 1, "sha256": sha(self.reviewer_findings[1])},
                 ],
                 "rationale": "The form is wired; the second reviewer finding verifies tests."},
            ],
        }

    def evidence(self, meta=None, evidence_id="coverage"):
        return Evidence(evidence_id, "TASK-177", "remediation-coverage", self.pr,
                        "Explicit finding coverage", self.recorded_at,
                        self.meta if meta is None else meta)

    def test_record_is_cas_append_only_and_does_not_rewrite_reviews(self):
        evidence = self.evidence()
        before = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "REMEDIATION_COVERAGE_REQUIRED"):
            self.registry.remediation_coverage("TASK-177")
        revision = self.registry.record_remediation_coverage(evidence, expected_revision=before)
        self.assertEqual(revision, before + 1)
        self.assertEqual(self.registry.record_remediation_coverage(evidence, expected_revision=before), revision)
        self.assertEqual(self.registry.remediation_coverage("TASK-177")["covered_findings"], 2)
        self.assertEqual(self.registry.remediation_coverage("TASK-177")["covered_change_requests"], 1)
        with self.assertRaisesRegex(RegistryConflict, "REMEDIATION_COVERAGE_ALREADY_RECORDED"):
            self.registry.record_remediation_coverage(
                self.evidence(evidence_id="another-coverage"), expected_revision=revision,
            )
        with self.registry._connection() as connection:
            rows = connection.execute("SELECT state FROM review_outcomes ORDER BY id").fetchall()
            self.assertEqual({row["state"] for row in rows}, {"APPROVED", "CHANGES_REQUESTED"})
            self.assertEqual(connection.execute(
                "SELECT status FROM work_packages WHERE id='TASK-177'"
            ).fetchone()[0], "VERIFY_REVIEW")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "REMEDIATION_COVERAGE_APPEND_ONLY"):
                connection.execute("UPDATE evidence SET summary='changed' WHERE id='coverage'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "REMEDIATION_COVERAGE_APPEND_ONLY"):
                connection.execute("DELETE FROM evidence WHERE id='coverage'")

    def test_missing_or_duplicate_finding_coverage_rejected(self):
        for coverage in (self.meta["finding_coverage"][:-1],
                         self.meta["finding_coverage"] + [self.meta["finding_coverage"][0]]):
            with self.subTest(coverage=coverage):
                metadata = {**self.meta, "finding_coverage": coverage}
                with self.assertRaisesRegex(RegistryConflict, "REMEDIATION_FINDING_COVERAGE_INCOMPLETE"):
                    self.registry.validate_remediation_coverage_candidate(self.evidence(metadata))

    def test_review_text_hash_and_exact_identity_rejected_when_changed(self):
        bad = {**self.meta, "finding_coverage": [
            {**self.meta["finding_coverage"][0], "reviewer_findings": [
                {"index": 0, "sha256": "0" * 64}]},
            *self.meta["finding_coverage"][1:]]}
        with self.assertRaisesRegex(RegistryConflict, "REMEDIATION_FINDING_PROVENANCE_MISMATCH"):
            self.registry.validate_remediation_coverage_candidate(self.evidence(bad))
        for change in ({"reviewed_commit": "f" * 40},
                       {"pr_url": "https://github.com/o/r/pull/431"},
                       {"remediation_review_outcome_id": "original-verdict"}):
            with self.subTest(change=change):
                bad = {**self.meta, **change}
                with self.assertRaises(RegistryConflict):
                    self.registry.validate_remediation_coverage_candidate(self.evidence(bad))

    def test_stale_revision_and_generic_evidence_cannot_bypass(self):
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_SPECIALIZED_OPERATION_REQUIRED"):
            self.registry.record_evidence(self.evidence())
        with self.assertRaisesRegex(RegistryConflict, "REVISION"):
            self.registry.record_remediation_coverage(self.evidence(), expected_revision=-1)
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM evidence WHERE kind='remediation-coverage'"
            ).fetchone()[0], 0)

    def test_source_verifier_requires_exact_merged_pr_and_ancestry(self):
        repository = self.root / "repo"
        repository.mkdir()
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        (repository / "file").write_text("before")
        subprocess.run(["git", "-C", str(repository), "add", "file"], check=True)
        subprocess.run(["git", "-C", str(repository), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "base"], check=True)
        (repository / "file").write_text("after")
        subprocess.run(["git", "-C", str(repository), "add", "file"], check=True)
        subprocess.run(["git", "-C", str(repository), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "fix"], check=True)
        merged = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
        tree = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD^{tree}"], text=True).strip()
        subprocess.run(["git", "-C", str(repository), "branch", "origin/main", merged], check=True)
        metadata = {**self.meta, "reviewed_commit": merged,
                    "merged_main_commit": merged, "merged_main_tree": tree}

        def github(*args):
            if args[0] == "pr":
                return json.dumps({"state": "MERGED", "headRefOid": merged,
                                   "mergeCommit": {"oid": merged}})
            return json.dumps({"object": {"sha": merged}})

        self.assertTrue(verify_remediation_coverage_source(
            metadata, repository=repository, github=github, repository_name="o/r",
        ))
        self.assertFalse(verify_remediation_coverage_source(
            {**metadata, "merged_main_tree": "0" * 40}, repository=repository,
            github=github, repository_name="o/r",
        ))
        self.assertFalse(verify_remediation_coverage_source(
            {**metadata, "pr_url": "https://github.com/other/repo/pull/430"},
            repository=repository, github=github, repository_name="o/r",
        ))
        self.assertFalse(verify_remediation_coverage_source(
            metadata, repository=repository,
            github=lambda *args: json.dumps({"state": "OPEN"}) if args[0] == "pr" else github(*args),
            repository_name="o/r",
        ))


if __name__ == "__main__":
    unittest.main()
