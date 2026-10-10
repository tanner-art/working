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
                ("initial-review-input", "TASK-2", "review-input",
                 "https://github.com/o/r/pull/1", "Initial review input",
                 self.now.isoformat(), json.dumps({"target_package_id": "TASK-1",
                    "implementation_commit": self.integrated, "base_commit": self.base,
                    "contract_sha256": "e" * 64})),
            )
            connection.execute(
                "INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("review-evidence", "TASK-2", "review", "https://github.com/o/r/pull/1",
                 "approved", self.now.isoformat(),
                 json.dumps({"reviewed_commit": self.integrated,
                             "reviewed_base_commit": self.base,
                             "contract_sha256": "e" * 64,
                             "review_input_evidence_id": "initial-review-input"})),
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
             "reviewed_commit": self.integrated,
             "reviewed_base_commit": self.base,
             "pr_head_commit": self.integrated,
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
            "schema_version": 2, "package_id": "TASK-3",
            "integrated_commit": self.integrated, "integrated_tree": self.tree,
            "base_commit": self.base, "target_ref": "main",
            "ordered_parent_shas": [self.integrated],
            "included_packages": [{
                "package_id": "TASK-1", "implementation_commit": self.integrated,
                "reviewed_commit": self.integrated,
                "reviewed_base_commit": self.base,
                "pr_head_commit": self.integrated,
                "prior_review_outcome_ids": [],
                "pr_url": "https://github.com/o/r/pull/1",
                "review_package_id": "TASK-2", "review_outcome_id": "review-outcome",
                "review_evidence_id": "review-evidence",
                "integration_receipt_id": "integration-receipt",
            }],
            "shared_path_handoffs": [],
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

    def seed_v2_review_provenance(self):
        # Baseline fixture already carries the exact v2 review-input chain.
        pass

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

    def test_schema_one_cannot_bypass_v2_assurance_at_any_registry_entry(self):
        legacy_item = {key: value for key, value in self.meta["included_packages"][0].items()
                       if key not in {"reviewed_commit", "reviewed_base_commit",
                                      "pr_head_commit", "prior_review_outcome_ids"}}
        legacy = {key: value for key, value in self.meta.items()
                  if key != "shared_path_handoffs"}
        legacy.update(schema_version=1, included_packages=[legacy_item])
        before = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_INPUT_INVALID"):
            self.registry.validate_integrated_assurance_candidate(self.evidence(legacy))
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_INPUT_INVALID"):
            self.registry.record_integrated_assurance_input(
                self.evidence(legacy), expected_revision=before,
            )
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM evidence WHERE package_id='TASK-3' "
                "AND kind='integrated-assurance-input'"
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT status FROM work_packages WHERE id='TASK-3'"
            ).fetchone()[0], "ON_DECK")
        # Simulate a legacy row already present before the validator upgrade.
        with self.registry._connection() as connection:
            connection.execute(
                "INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("old-assurance-input", "TASK-3", "integrated-assurance-input",
                 self.meta["ci"]["run_url"], "Legacy input", self.now.isoformat(),
                 json.dumps(legacy)),
            )
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_INPUT_INVALID"):
            self.registry.integrated_assurance_input("TASK-3")
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_INPUT_INVALID"):
            self.registry.transition_work_package(
                "TASK-3", expected_status=TaskStatus.ON_DECK,
                new_status=TaskStatus.READY, changed_at=self.now.isoformat(),
            )
        self.assertFalse(verify_integrated_source(
            replace(self.registry.validate_integrated_assurance_candidate(self.evidence()),
                    schema_version=1), repository=self.repo,
            github=lambda *args: self.fail("v1 source verifier must not call GitHub"),
            repository_name="o/r",
        ))

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
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_REVIEW_EVIDENCE_INVALID"):
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

    def test_v2_ordered_shared_path_and_historical_main_are_valid(self):
        first = self.integrated
        first_tree = self.tree
        self.write("src/feature.py", "second writer")
        self.commit("ordered second writer")
        second = self.git("rev-parse", "HEAD")
        second_tree = self.git("rev-parse", "HEAD^{tree}")
        self.write("docs/later.md", "unrelated later main")
        self.commit("later main")
        main_head = self.git("rev-parse", "HEAD")
        first_item = {**self.meta["included_packages"][0],
                      "reviewed_commit": first, "reviewed_base_commit": self.base,
                      "pr_head_commit": first,
                      "prior_review_outcome_ids": []}
        second_item = {**first_item, "package_id": "TASK-4", "implementation_commit": second,
                       "reviewed_commit": second, "reviewed_base_commit": first,
                       "pr_head_commit": second,
                       "pr_url": "https://github.com/o/r/pull/4",
                       "review_package_id": "TASK-5", "review_outcome_id": "review-outcome-4",
                       "review_evidence_id": "review-evidence-4",
                       "integration_receipt_id": "integration-receipt-4"}
        meta = {**self.meta, "schema_version": 2, "integrated_commit": second,
                "integrated_tree": second_tree, "ordered_parent_shas": [first, second],
                "included_packages": [first_item, second_item],
                "shared_path_handoffs": [{"path": "src/feature.py",
                                          "ordered_writers": ["TASK-1", "TASK-4"]}],
                "ci": {**self.meta["ci"], "commit": second}}
        facts = {
            package_id: {"id": item["review_outcome_id"], "state": "APPROVED",
                         "review_package_id": item["review_package_id"],
                         "implementer_worker_id": "builder", "reviewer_worker_id": "claude",
                         "approval_evidence_ids": [item["review_evidence_id"]],
                         "reviewed_commit": item["reviewed_commit"],
                         "reviewed_base_commit": item["reviewed_base_commit"],
                         "review_pr_url": item["pr_url"],
                         "source_implementation_commit": item["implementation_commit"],
                         "implementer_worker_ids": ("builder",),
                         "prior_review_outcome_ids": (), "prior_review_outcomes": ()}
            for package_id, item in (("TASK-1", first_item), ("TASK-4", second_item))
        }
        receipts = {
            package_id: {"id": item["integration_receipt_id"], "kind": "integration-acceptance",
                         "package_id": package_id, "metadata": {
                             "implementation_commit": item["implementation_commit"],
                             "reviewed_commit": item["reviewed_commit"],
                             "reviewed_base_commit": item["reviewed_base_commit"],
                             "pr_head_commit": item["pr_head_commit"],
                             "pr_url": item["pr_url"],
                             "review_outcome_id": item["review_outcome_id"],
                             "review_evidence_id": item["review_evidence_id"],
                             "merged_main_commit": commit, "merged_main_tree": tree,
                             "inclusion_mode": "ancestry", "changed_paths": ["src/feature.py"],
                         }}
            for package_id, item, commit, tree in (
                ("TASK-1", first_item, first, first_tree),
                ("TASK-4", second_item, second, second_tree),
            )
        }
        package = {"id": "TASK-3", "kind": "EVALUATION", "lane": "ASSURANCE",
                   "acceptance_criteria": ["visible feature works"],
                   "provider_diagnostics": {"queue_contract_sha256": queue_contract_digest(self.contract)}}
        evidence = {"id": "v2-input", "package_id": "TASK-3",
                    "kind": "integrated-assurance-input", "recorded_at": self.now.isoformat(),
                    "metadata": meta}
        value = parse_assurance_input(evidence, package=package,
                                      dependencies=("TASK-1", "TASK-4"),
                                      review_facts=facts, receipts=receipts)
        def github(*args):
            if args[0] == "api":
                return json.dumps({"object": {"sha": main_head}})
            if args[0] == "pr":
                item = first_item if args[2] == first_item["pr_url"] else second_item
                return json.dumps({"state": "MERGED", "headRefOid": item["pr_head_commit"],
                                   "mergeCommit": {"oid": first if item is first_item else second}})
            return json.dumps({"headSha": second, "status": "completed",
                               "conclusion": "success", "workflowName": "Validate app",
                               "url": meta["ci"]["run_url"]})
        self.assertTrue(verify_integrated_source(
            value, repository=self.repo, github=github, repository_name="o/r"))
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_SHARED_PATH_HANDOFF_INVALID"):
            parse_assurance_input({**evidence, "metadata": {**meta, "shared_path_handoffs": []}},
                                  package=package, dependencies=("TASK-1", "TASK-4"),
                                  review_facts=facts, receipts=receipts)
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_SHARED_PATH_HANDOFF_INVALID"):
            parse_assurance_input({**evidence, "metadata": {**meta, "shared_path_handoffs": [
                {"path": "src/feature.py", "ordered_writers": ["TASK-4", "TASK-1"]}]}},
                package=package, dependencies=("TASK-1", "TASK-4"),
                review_facts=facts, receipts=receipts)
        self.assertFalse(verify_integrated_source(
            value, repository=self.repo,
            github=lambda *args: json.dumps({"object": {"sha": self.base}}),
            repository_name="o/r"))
        sibling = subprocess.check_output(
            ["git", "-C", str(self.repo), "-c", "user.name=Test",
             "-c", "user.email=test@example.invalid", "commit-tree", second_tree,
             "-p", self.base], input="sibling second writer", text=True,
        ).strip()
        sibling_item = {**second_item, "implementation_commit": sibling,
                        "reviewed_commit": sibling, "pr_head_commit": sibling}
        sibling_receipt = {**receipts["TASK-4"], "metadata": {
            **receipts["TASK-4"]["metadata"], "implementation_commit": sibling,
            "reviewed_commit": sibling, "pr_head_commit": sibling}}
        sibling_value = replace(value,
            included_packages=(first_item, sibling_item),
            integration_receipts=(receipts["TASK-1"]["metadata"], sibling_receipt["metadata"]))
        self.assertFalse(verify_integrated_source(
            sibling_value, repository=self.repo, github=github, repository_name="o/r"))

    def test_v2_distinct_source_reviewed_pr_head_merge_and_prior_review(self):
        source = self.integrated
        self.write("src/feature.py", "PR head")
        self.commit("PR head")
        pr_head = self.git("rev-parse", "HEAD")
        self.write("src/feature.py", "independently reviewed integration")
        self.commit("reviewed integration")
        reviewed = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        merged = subprocess.check_output(
            ["git", "-C", str(self.repo), "-c", "user.name=Test",
             "-c", "user.email=test@example.invalid", "commit-tree", tree,
             "-p", self.base, "-p", reviewed],
            input="reviewed merge result", text=True,
        ).strip()
        item = {**self.meta["included_packages"][0], "implementation_commit": source,
                "reviewed_commit": reviewed, "reviewed_base_commit": self.base,
                "pr_head_commit": pr_head,
                "prior_review_outcome_ids": ["earlier-changes-requested"]}
        meta = {**self.meta, "schema_version": 2, "integrated_commit": merged,
                "integrated_tree": tree, "ordered_parent_shas": [merged],
                "included_packages": [item], "shared_path_handoffs": [],
                "ci": {**self.meta["ci"], "commit": merged}}
        package = {"id": "TASK-3", "kind": "EVALUATION", "lane": "ASSURANCE",
                   "acceptance_criteria": ["visible feature works"],
                   "provider_diagnostics": {"queue_contract_sha256": queue_contract_digest(self.contract)}}
        evidence = {"id": "v2-input", "package_id": "TASK-3",
                    "kind": "integrated-assurance-input", "recorded_at": self.now.isoformat(),
                    "metadata": meta}
        review = {"TASK-1": {"id": "review-outcome", "state": "APPROVED",
                             "review_package_id": "TASK-2", "implementer_worker_id": "builder",
                             "reviewer_worker_id": "claude", "approval_evidence_ids": ["review-evidence"],
                             "reviewed_commit": reviewed, "review_pr_url": item["pr_url"],
                             "reviewed_base_commit": self.base,
                             "source_implementation_commit": source,
                             "implementer_worker_ids": ("builder",),
                             "prior_review_outcome_ids": ("earlier-changes-requested",),
                             "prior_review_outcomes": ({"id": "earlier-changes-requested",
                                                        "state": "CHANGES_REQUESTED"},)}}
        receipts = {"TASK-1": {"id": "integration-receipt", "package_id": "TASK-1",
                               "kind": "integration-acceptance", "metadata": {
                                   "implementation_commit": source, "reviewed_commit": reviewed,
                                   "reviewed_base_commit": self.base,
                                   "pr_head_commit": pr_head, "pr_url": item["pr_url"],
                                   "review_outcome_id": "review-outcome",
                                   "review_evidence_id": "review-evidence",
                                   "merged_main_commit": merged, "merged_main_tree": tree,
                                   "inclusion_mode": "ancestry",
                                   "changed_paths": ["src/feature.py"]}}}
        value = parse_assurance_input(evidence, package=package, dependencies=("TASK-1",),
                                      review_facts=review, receipts=receipts)
        self.assertEqual(value.review_histories[0]["prior_outcomes"][0]["id"],
                         "earlier-changes-requested")
        def github(*args):
            if args[0] == "api":
                return json.dumps({"object": {"sha": merged}})
            if args[0] == "pr":
                return json.dumps({"state": "MERGED", "headRefOid": pr_head,
                                   "mergeCommit": {"oid": merged}})
            return json.dumps({"headSha": merged, "status": "completed",
                               "conclusion": "success", "workflowName": "Validate app",
                               "url": meta["ci"]["run_url"]})
        self.assertTrue(verify_integrated_source(
            value, repository=self.repo, github=github, repository_name="o/r"))
        # Advancing the review base to `source` would hide the intermediate
        # base..source delta from the independent reviewer.
        advanced_base = replace(value,
            included_packages=({**item, "reviewed_base_commit": source},),
            integration_receipts=({**value.integration_receipts[0],
                                   "reviewed_base_commit": source},))
        self.assertFalse(verify_integrated_source(
            advanced_base, repository=self.repo, github=github, repository_name="o/r"))
        self.assertFalse(verify_integrated_source(
            replace(value, integrated_commit=reviewed),
            repository=self.repo, github=github, repository_name="o/r"))
        self.write("docs/unreviewed.md", "unreviewed merge delta")
        self.commit("unreviewed merge delta")
        unreviewed_tree = self.git("rev-parse", "HEAD^{tree}")
        unreviewed_merge = subprocess.check_output(
            ["git", "-C", str(self.repo), "-c", "user.name=Test",
             "-c", "user.email=test@example.invalid", "commit-tree", unreviewed_tree,
             "-p", self.base, "-p", reviewed],
            input="unreviewed merge result", text=True,
        ).strip()
        changed_receipt = {**value.integration_receipts[0],
                           "merged_main_commit": unreviewed_merge,
                           "merged_main_tree": unreviewed_tree,
                           "changed_paths": ["src/feature.py", "docs/unreviewed.md"]}
        unreviewed_value = replace(value, integrated_commit=unreviewed_merge,
                                   integrated_tree=unreviewed_tree,
                                   ordered_parent_shas=(unreviewed_merge,),
                                   integration_receipts=(changed_receipt,))
        def unreviewed_github(*args):
            if args[0] == "api":
                return json.dumps({"object": {"sha": unreviewed_merge}})
            if args[0] == "pr":
                return json.dumps({"state": "MERGED", "headRefOid": pr_head,
                                   "mergeCommit": {"oid": unreviewed_merge}})
            return json.dumps({"headSha": unreviewed_merge, "status": "completed",
                               "conclusion": "success", "workflowName": "Validate app",
                               "url": meta["ci"]["run_url"]})
        self.assertFalse(verify_integrated_source(
            unreviewed_value, repository=self.repo,
            github=unreviewed_github, repository_name="o/r"))
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_ANCESTOR_NOT_APPROVED"):
            parse_assurance_input({**evidence, "metadata": {**meta, "included_packages": [
                {**item, "prior_review_outcome_ids": []}]}}, package=package,
                dependencies=("TASK-1",), review_facts=review, receipts=receipts)
        self.assertFalse(verify_integrated_source(
            replace(value, included_packages=({**item, "pr_head_commit": merged},)),
            repository=self.repo, github=github, repository_name="o/r"))
        sibling = subprocess.check_output(
            ["git", "-C", str(self.repo), "-c", "user.name=Test",
             "-c", "user.email=test@example.invalid", "commit-tree",
             self.git("rev-parse", f"{source}^{{tree}}"), "-p", self.base],
            input="non-ancestral source", text=True,
        ).strip()
        self.assertFalse(verify_integrated_source(
            replace(value, included_packages=({**item, "implementation_commit": sibling},)),
            repository=self.repo, github=github, repository_name="o/r"))

    def test_v2_requires_nonempty_acceptance_matrix_and_all_implementers(self):
        item = {**self.meta["included_packages"][0],
                "reviewed_commit": self.integrated,
                "reviewed_base_commit": self.base,
                "pr_head_commit": self.integrated,
                "prior_review_outcome_ids": []}
        meta = {**self.meta, "schema_version": 2, "included_packages": [item],
                "shared_path_handoffs": []}
        evidence = {"id": "input", "package_id": "TASK-3",
                    "kind": "integrated-assurance-input",
                    "recorded_at": self.now.isoformat(), "metadata": meta}
        package = {"id": "TASK-3", "kind": "EVALUATION", "lane": "ASSURANCE",
                   "acceptance_criteria": ["visible feature works"],
                   "provider_diagnostics": {"queue_contract_sha256": queue_contract_digest(self.contract)}}
        fact = {"id": "review-outcome", "state": "APPROVED",
                "review_package_id": "TASK-2", "implementer_worker_id": "builder",
                "reviewer_worker_id": "claude", "implementer_worker_ids": ("original-builder", "builder"),
                "approval_evidence_ids": ["review-evidence"],
                "reviewed_commit": self.integrated, "review_pr_url": item["pr_url"],
                "reviewed_base_commit": self.base,
                "source_implementation_commit": self.integrated,
                "prior_review_outcome_ids": (), "prior_review_outcomes": ()}
        receipt = {"id": "integration-receipt", "package_id": "TASK-1",
                   "kind": "integration-acceptance", "metadata": {
                       "implementation_commit": self.integrated,
                       "reviewed_commit": self.integrated,
                       "reviewed_base_commit": self.base,
                       "pr_head_commit": self.integrated,
                       "pr_url": "https://github.com/o/r/pull/1",
                       "review_outcome_id": "review-outcome",
                       "review_evidence_id": "review-evidence",
                       "merged_main_commit": self.integrated,
                       "merged_main_tree": self.tree,
                       "inclusion_mode": "ancestry",
                       "changed_paths": ["src/feature.py"]}}
        value = parse_assurance_input(evidence, package=package,
                                      dependencies=("TASK-1",),
                                      review_facts={"TASK-1": fact},
                                      receipts={"TASK-1": receipt})
        self.assertEqual(set(value.implementer_workers), {"original-builder", "builder"})
        mismatched_relation = {"original_package_id": "TASK-1",
                               "original_reviewed_commit": self.integrated,
                               "remediation_review_package_id": "TASK-2",
                               "reviewed_commit": self.integrated,
                               "merged_main_commit": "a" * 40,
                               "merged_main_tree": self.tree,
                               "pr_url": item["pr_url"]}
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_REMEDIATION_RECEIPT_MISMATCH"):
            parse_assurance_input(evidence, package=package, dependencies=("TASK-1",),
                                  review_facts={"TASK-1": {
                                      **fact, "remediation_relation": mismatched_relation}},
                                  receipts={"TASK-1": receipt})
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_MATRIX_INCOMPLETE"):
            parse_assurance_input({**evidence, "metadata": {**meta, "acceptance_matrix": []}},
                                  package={**package, "acceptance_criteria": []},
                                  dependencies=("TASK-1",), review_facts={"TASK-1": fact},
                                  receipts={"TASK-1": receipt})

    def test_v2_registry_terminal_approval_preserves_earlier_change_request(self):
        self.seed_v2_review_provenance()
        self.registry.register_work_package(WorkPackage(
            "TASK-0", "F", "Earlier review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("reviewed",), status=TaskStatus.DONE,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-1",),
        ))
        earlier = (self.now - timedelta(minutes=1)).isoformat()
        with self.registry._connection() as connection:
            connection.execute(
                "INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("earlier-review-input", "TASK-0", "review-input",
                 "https://github.com/o/r/pull/1", "Initial implementation", earlier,
                 json.dumps({"target_package_id": "TASK-1",
                             "implementation_commit": self.integrated})),
            )
            connection.execute(
                "INSERT INTO review_outcomes(id,review_package_id,target_package_id,"
                "implementer_worker_id,reviewer_worker_id,requested_at,decided_at,state,"
                "findings_json,changes_requested_json,approval_evidence_ids_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("earlier-cr", "TASK-0", "TASK-1", "builder", "claude", earlier, earlier,
                 "CHANGES_REQUESTED", '["UI unreachable"]', '["Wire the UI"]', "[]"),
            )
        with self.registry._connection() as connection:
            fact = SQLiteRegistry._assurance_review_fact_v2(connection, "TASK-1")
        self.assertEqual(fact["id"], "review-outcome")
        self.assertEqual(fact["prior_review_outcome_ids"], ("earlier-cr",))
        self.assertEqual(fact["prior_review_outcomes"][0]["changes_requested"], ["Wire the UI"])
        self.assertEqual(fact["source_implementation_commit"], self.integrated)
        self.registry.register_work_package(WorkPackage(
            "TASK-4", "F", "Later failed review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("reviewed",), status=TaskStatus.DONE,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-1",),
        ))
        later = (self.now + timedelta(minutes=1)).isoformat()
        with self.registry._connection() as connection:
            connection.execute(
                "INSERT INTO review_outcomes(id,review_package_id,target_package_id,"
                "implementer_worker_id,reviewer_worker_id,requested_at,decided_at,state,"
                "findings_json,changes_requested_json,approval_evidence_ids_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("later-cr", "TASK-4", "TASK-1", "builder", "claude", later, later,
                 "CHANGES_REQUESTED", '["regressed"]', '["repair"]', "[]"),
            )
        with self.registry._connection() as connection:
            with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_ANCESTOR_NOT_APPROVED"):
                SQLiteRegistry._assurance_review_fact_v2(connection, "TASK-1")

    def test_v2_registry_candidate_requires_exact_lineage_and_existing_matrix(self):
        self.seed_v2_review_provenance()
        with self.registry._connection() as connection:
            connection.execute("UPDATE evidence SET metadata_json=? WHERE id='integration-receipt'",
                               (json.dumps({**json.loads(connection.execute(
                                   "SELECT metadata_json FROM evidence WHERE id='integration-receipt'"
                               ).fetchone()[0]), "reviewed_commit": self.integrated,
                                   "reviewed_base_commit": self.base,
                                   "pr_head_commit": self.integrated}),))
        item = {**self.meta["included_packages"][0], "reviewed_commit": self.integrated,
                "reviewed_base_commit": self.base,
                "pr_head_commit": self.integrated, "prior_review_outcome_ids": []}
        meta = {**self.meta, "schema_version": 2, "included_packages": [item],
                "shared_path_handoffs": []}
        assurance = self.registry.validate_integrated_assurance_candidate(self.evidence(meta))
        self.assertEqual(assurance.schema_version, 2)
        self.assertEqual(assurance.review_histories[0]["prior_outcomes"], [])
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_MATRIX_INCOMPLETE"):
            self.registry.validate_integrated_assurance_candidate(self.evidence({
                **meta, "acceptance_matrix": [],
            }))
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_MATRIX_EVIDENCE_INVALID"):
            self.registry.validate_integrated_assurance_candidate(self.evidence({
                **meta, "acceptance_matrix": [{**meta["acceptance_matrix"][0],
                                               "evidence_id": "missing"}],
            }))

    def test_v2_claimed_assurance_reviewer_cannot_be_prior_implementer(self):
        self.seed_v2_review_provenance()
        self.registry.register_worker(Worker(
            "original-builder", "Original builder", ("independent-review",),
            (Lane.ASSURANCE,),
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK-0", "F", "Earlier review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("reviewed",), status=TaskStatus.DONE,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-1",),
        ))
        earlier = (self.now - timedelta(minutes=1)).isoformat()
        with self.registry._connection() as connection:
            connection.execute(
                "INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("earlier-review-input", "TASK-0", "review-input",
                 "https://github.com/o/r/pull/1", "Initial implementation", earlier,
                 json.dumps({"target_package_id": "TASK-1",
                             "implementation_commit": self.integrated})),
            )
            connection.execute(
                "INSERT INTO review_outcomes(id,review_package_id,target_package_id,"
                "implementer_worker_id,reviewer_worker_id,requested_at,decided_at,state,"
                "findings_json,changes_requested_json,approval_evidence_ids_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("earlier-cr", "TASK-0", "TASK-1", "original-builder", "claude",
                 earlier, earlier, "CHANGES_REQUESTED", '["gap"]', '["repair"]', "[]"),
            )
            receipt = json.loads(connection.execute(
                "SELECT metadata_json FROM evidence WHERE id='integration-receipt'"
            ).fetchone()[0])
            connection.execute(
                "UPDATE evidence SET metadata_json=? WHERE id='integration-receipt'",
                (json.dumps({**receipt, "reviewed_commit": self.integrated,
                             "reviewed_base_commit": self.base,
                             "pr_head_commit": self.integrated}),),
            )
        item = {**self.meta["included_packages"][0], "reviewed_commit": self.integrated,
                "reviewed_base_commit": self.base, "pr_head_commit": self.integrated,
                "prior_review_outcome_ids": ["earlier-cr"]}
        meta = {**self.meta, "schema_version": 2, "included_packages": [item],
                "shared_path_handoffs": []}
        assurance = self.registry.validate_integrated_assurance_candidate(self.evidence(meta))
        self.assertIn("original-builder", assurance.implementer_workers)
        self.begin_assurance_attempt(self.evidence(meta), reviewer="original-builder")
        verdict = ReviewVerdict(ReviewOutcomeState.APPROVED, self.integrated,
                                self.base, queue_contract_digest(self.contract))
        with self.assertRaisesRegex(RegistryConflict, "ASSURANCE_REVIEWER_IMPLEMENTED_INCLUDED_PACKAGE"):
            self.registry.record_integrated_assurance_verdict(
                "TASK-3", "assurance-attempt", "original-builder", "assurance-input", verdict,
                expected_revision=self.registry.dispatch_control()["revision"],
                decided_at=datetime.now(timezone.utc).isoformat(),
            )

    def begin_assurance_attempt(self, evidence=None, reviewer="claude"):
        self.registry.record_integrated_assurance_input(
            evidence or self.evidence(), expected_revision=self.registry.dispatch_control()["revision"],
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
            "TASK-3", reviewer, acquired_at=self.now.isoformat(),
            expires_at=(self.now + timedelta(minutes=5)).isoformat(),
            expected_dispatch_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.begin_attempt_runtime(
            "assurance-attempt", package_id="TASK-3", worker_id=reviewer,
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
