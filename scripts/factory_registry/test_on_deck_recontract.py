"""Fail-closed tests for attaching v2 contracts to existing ON_DECK pairs."""

import json
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from scripts.factory_registry import Feature, Lane, PackageKind, SQLiteRegistry, TaskStatus, Worker, WorkPackage
from scripts.factory_registry.operator import (
    OperatorError,
    parse_on_deck_pair_spec,
    prepare_ready_package,
)
from scripts.factory_registry.repository import RegistryConflict


class OnDeckRecontractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for name in ("docs/PLAN.md", "src/impl.py", "docs/review.md", "tests/test_impl.py"):
            path = self.repo / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(name)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(self.repo), "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid", "commit", "-qm", "base",
        ], check=True)
        subprocess.run(["git", "-C", str(self.repo), "branch", "-M", "main"], check=True)
        self.base = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "main"], text=True,
        ).strip()
        self.database = self.root / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.registry.register_feature(Feature(id="FEATURE-1", title="Canvas", priority=1))
        self.registry.register_work_package(WorkPackage(
            id="TASK-101", feature_id="FEATURE-1", title="Implementation",
            category="PRODUCT", lane=Lane.FEATURE,
            required_capabilities=("implementation",), priority=1,
            acceptance_criteria=("Sparse old criterion",), status=TaskStatus.ON_DECK,
            kind=PackageKind.PARENT, provider_diagnostics={"planning_commit": "old"},
        ))
        self.registry.register_work_package(WorkPackage(
            id="TASK-102", feature_id="FEATURE-1", title="Independent review",
            category="ASSURANCE", lane=Lane.ASSURANCE,
            required_capabilities=("independent-review",), priority=1,
            acceptance_criteria=("Sparse old criterion",), status=TaskStatus.ON_DECK,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-101",),
            provider_diagnostics={"planning_commit": "old"},
        ))

    def spec(self, *, implementation_dependencies=()):
        def package(task, title, category, lane, kind, capabilities, source, paths, dependencies):
            contract = {
                "schema_version": 2, "task": task, "lane": lane, "kind": kind,
                "capacity_size": "SUBSTANTIAL", "capacity_risk": "UNCERTAIN",
                "instructions": "Complete this bounded package and retain exact evidence.",
                "paths": paths, "depends_on": [int(item.removeprefix("TASK-")) for item in dependencies],
                "readiness": {
                    "base_commit": self.base, "planning_paths": ["docs/PLAN.md"],
                    "existing_paths": paths, "new_paths": [],
                    "integration_paths": [paths[0]], "test_paths": [paths[-1]],
                    "dependency_kinds": {item: "coding" for item in dependencies},
                },
            }
            return {
                "id": task, "feature_id": "FEATURE-1", "title": title,
                "category": category, "lane": lane, "kind": kind,
                "required_capabilities": capabilities, "priority": 1,
                "capacity_size": "SUBSTANTIAL", "capacity_risk": "UNCERTAIN",
                "acceptance_criteria": ["An observable, reviewed result exists."],
                "dependency_ids": list(dependencies), "source_ref": source,
                "queue_contract": contract,
            }
        return {
            "feature_id": "FEATURE-1",
            "implementation": package(
                "TASK-101", "Implementation", "PRODUCT", "FEATURE", "PARENT",
                ["implementation"], "201", ["src/impl.py", "tests/test_impl.py"],
                implementation_dependencies,
            ),
            "review": package(
                "TASK-102", "Independent review", "ASSURANCE", "ASSURANCE", "REVIEW",
                ["independent-review"], "202", ["docs/review.md"], ("TASK-101",),
            ),
        }

    def prepared(self, spec=None, target_ref="main"):
        feature_id, implementation, review, impl_contract, review_contract = (
            parse_on_deck_pair_spec(spec or self.spec())
        )
        self.assertEqual(feature_id, "FEATURE-1")
        return (
            prepare_ready_package(implementation, impl_contract,
                                  repository=self.repo, target_ref=target_ref),
            prepare_ready_package(review, review_contract,
                                  repository=self.repo, target_ref=target_ref),
            (impl_contract, review_contract),
        )

    def apply(self, operation_id="recontract-1", spec=None, expected_revision=None,
              target_ref="main"):
        implementation, review, contracts = self.prepared(spec, target_ref)
        revision = self.registry.dispatch_control()["revision"] if expected_revision is None else expected_revision
        return self.registry.recontract_on_deck_pair(
            implementation, review, expected_revision=revision,
            recorded_at="2026-10-10T12:00:00Z", operation_id=operation_id,
            repository=self.repo, target_ref=target_ref, contracts=contracts,
        )

    def rows(self):
        with sqlite3.connect(self.database) as connection:
            return connection.execute(
                "SELECT id,status,source_system,source_ref,acceptance_criteria_json,provider_diagnostics_json "
                "FROM work_packages WHERE id IN ('TASK-101','TASK-102') ORDER BY id"
            ).fetchall()

    def test_recontracts_existing_pair_without_promotion_and_replays_exactly(self):
        before = self.registry.dispatch_control()["revision"]
        result = self.apply(expected_revision=before)
        self.assertEqual(result["revision"], before + 1)
        self.assertEqual(result["status"], "ON_DECK")
        self.assertEqual(self.apply(expected_revision=before), result)
        self.assertEqual(self.registry.dispatch_control()["revision"], before + 1)
        rows = self.rows()
        self.assertEqual([row[1] for row in rows], ["ON_DECK", "ON_DECK"])
        self.assertEqual([row[3] for row in rows], ["201", "202"])
        for row in rows:
            self.assertEqual(row[2], "github_issue")
            self.assertEqual(json.loads(row[4]), ["An observable, reviewed result exists."])
            self.assertEqual(json.loads(row[5])["readiness_schema_version"], 2)
            self.assertEqual(json.loads(row[5])["planning_commit"], "old")
            self.assertTrue(json.loads(row[5])["on_deck_recontract_requires_promotion"])
        with self.assertRaisesRegex(RegistryConflict, "ON_DECK_RECONTRACT_REQUIRES_PROMOTION"):
            self.registry.transition_work_package(
                "TASK-101", expected_status=TaskStatus.ON_DECK,
                new_status=TaskStatus.READY, changed_at="2026-10-10T12:01:00Z",
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM evidence WHERE id=? AND kind='ON_DECK_RECONTRACT'",
                (result["evidence_id"],),
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM control_operation_receipts WHERE operation_id='recontract-1'"
            ).fetchone()[0], 1)

    def test_stale_revision_and_reused_operation_id_fail_closed(self):
        initial = self.registry.dispatch_control()["revision"]
        self.apply(expected_revision=initial)
        with self.assertRaisesRegex(RegistryConflict, "OPERATION_ID_REUSED"):
            self.apply(operation_id="recontract-1", spec={
                **self.spec(), "implementation": {
                    **self.spec()["implementation"], "acceptance_criteria": ["Different criterion"],
                },
            }, expected_revision=initial)
        with self.assertRaisesRegex(RegistryConflict, "REGISTRY_REVISION_CHANGED"):
            self.apply(operation_id="recontract-2", expected_revision=initial)
        with self.assertRaisesRegex(RegistryConflict, "ON_DECK_PAIR_ALREADY_RECONTRACTED"):
            self.apply(operation_id="recontract-3")
        self.assertEqual([row[1] for row in self.rows()], ["ON_DECK", "ON_DECK"])

    def test_replay_binds_full_authoritative_package_identity(self):
        implementation, review, contracts = self.prepared()
        revision = self.registry.dispatch_control()["revision"]
        self.registry.recontract_on_deck_pair(
            implementation, review, expected_revision=revision,
            recorded_at="2026-10-10T12:00:00Z", operation_id="identity-bound",
            repository=self.repo, target_ref="main", contracts=contracts,
        )
        variants = (
            (replace(implementation, title="Changed title"), contracts),
            (replace(implementation, category="OTHER"), contracts),
            (replace(implementation, priority=9), contracts),
            (replace(implementation, required_capabilities=("other",)), contracts),
            (replace(implementation, lane=Lane.PLATFORM),
             ({**contracts[0], "lane": "PLATFORM"}, contracts[1])),
        )
        for variant, input_contracts in variants:
            with self.subTest(variant=variant):
                with self.assertRaisesRegex(RegistryConflict, "OPERATION_ID_REUSED"):
                    self.registry.recontract_on_deck_pair(
                        variant, review, expected_revision=revision,
                        recorded_at="2026-10-10T12:00:00Z", operation_id="identity-bound",
                        repository=self.repo, target_ref="main", contracts=input_contracts,
                    )

    def test_direct_registry_api_rejects_contract_path_and_dependency_mismatch(self):
        implementation, review, contracts = self.prepared()
        revision = self.registry.dispatch_control()["revision"]
        forged_paths = replace(implementation, provider_diagnostics={
            **implementation.provider_diagnostics,
            "exclusive_paths": ["docs/review.md"],
        })
        forged_dependency = replace(implementation, dependency_ids=("TASK-900",))
        forged_contract = {**contracts[0], "task": "TASK-900"}
        for candidate, input_contracts in (
            (forged_paths, contracts),
            (forged_dependency, contracts),
            (implementation, (forged_contract, contracts[1])),
        ):
            with self.subTest(candidate=candidate.id, contract=input_contracts[0].get("task")):
                with self.assertRaisesRegex(RegistryConflict, "ON_DECK_CONTRACT_BINDING_MISMATCH"):
                    self.registry.recontract_on_deck_pair(
                        candidate, review, expected_revision=revision,
                        recorded_at="2026-10-10T12:00:00Z", operation_id="forged-contract",
                        repository=self.repo, target_ref="main", contracts=input_contracts,
                    )
        self.assertIsNone(self.rows()[0][3])

    def test_timeout_at_mutable_ref_recheck_fails_closed(self):
        implementation, review, contracts = self.prepared()
        with patch(
            "scripts.factory_registry.sqlite_registry.registration_proof",
            side_effect=[implementation.provider_diagnostics["readiness_proof"],
                         review.provider_diagnostics["readiness_proof"]],
        ), patch(
            "scripts.factory_registry.sqlite_registry.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git rev-parse", timeout=5),
        ):
            with self.assertRaisesRegex(RegistryConflict, "ON_DECK_TARGET_REF_CHANGED"):
                self.registry.recontract_on_deck_pair(
                    implementation, review,
                    expected_revision=self.registry.dispatch_control()["revision"],
                    recorded_at="2026-10-10T12:00:00Z", operation_id="ref-timeout",
                    repository=self.repo, target_ref="main", contracts=contracts,
                )
        self.assertIsNone(self.rows()[0][3])

    def test_explicit_origin_main_is_pinned_for_planning_only(self):
        subprocess.run([
            "git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/main", self.base,
        ], check=True)
        result = self.apply(target_ref="origin/main")
        self.assertEqual(result["status"], "ON_DECK")
        for row in self.rows():
            self.assertEqual(
                json.loads(row[5])["readiness_proof"]["target_ref"], "origin/main"
            )

    def test_live_mode_and_ready_path_collision_fail_closed(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE factory_control SET dispatch_mode='LIVE',kill_switch_engaged=0 WHERE singleton=1"
            )
        with self.assertRaisesRegex(RegistryConflict, "ON_DECK_RECONTRACT_REQUIRES_PAUSED"):
            self.apply(operation_id="live-rejected")
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE factory_control SET dispatch_mode='PAUSED',kill_switch_engaged=1 WHERE singleton=1"
            )
        self.registry.register_feature(Feature(id="OTHER", title="Other", priority=2))
        self.registry.register_work_package(WorkPackage(
            id="TASK-900", feature_id="OTHER", title="Ready owner",
            category="PRODUCT", lane=Lane.FEATURE,
            required_capabilities=("implementation",), priority=2,
            acceptance_criteria=("Existing owner",), status=TaskStatus.READY,
            kind=PackageKind.PARENT,
            provider_diagnostics={"exclusive_paths": ["src/impl.py"]},
        ))
        with self.assertRaisesRegex(RegistryConflict, "EXCLUSIVE_PATH_COLLISION"):
            self.apply(operation_id="collision-rejected")
        self.assertIsNone(self.rows()[0][3])

    def test_changed_target_ref_and_dependency_edge_fail_closed(self):
        implementation, review, contracts = self.prepared()
        (self.repo / "docs/PLAN.md").write_text("changed")
        subprocess.run(["git", "-C", str(self.repo), "add", "docs/PLAN.md"], check=True)
        subprocess.run([
            "git", "-C", str(self.repo), "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid", "commit", "-qm", "advance",
        ], check=True)
        with self.assertRaisesRegex(RegistryConflict, "ON_DECK_PROOF_CHANGED"):
            self.registry.recontract_on_deck_pair(
                implementation, review,
                expected_revision=self.registry.dispatch_control()["revision"],
                recorded_at="2026-10-10T12:00:00Z", operation_id="moved-ref",
                repository=self.repo, target_ref="main", contracts=contracts,
            )
        self.assertIsNone(self.rows()[0][3])

    def test_unapproved_predecessor_review_is_not_silently_accepted(self):
        for worker_id in ("implementer", "reviewer"):
            self.registry.register_worker(Worker(
                id=worker_id, display_name=worker_id,
                capabilities=("independent-review",), approved_lanes=(Lane.ASSURANCE,),
            ))
        self.registry.register_work_package(WorkPackage(
            id="TASK-100", feature_id="FEATURE-1", title="Prior review",
            category="ASSURANCE", lane=Lane.ASSURANCE,
            required_capabilities=("independent-review",), priority=1,
            acceptance_criteria=("Historical review",), status=TaskStatus.DONE,
            kind=PackageKind.REVIEW,
        ))
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO task_dependencies(package_id,dependency_id) VALUES ('TASK-101','TASK-100')"
            )
            connection.execute(
                """INSERT INTO review_outcomes
                   (id,review_package_id,target_package_id,implementer_worker_id,
                    reviewer_worker_id,requested_at,decided_at,state,findings_json,
                    changes_requested_json,approval_evidence_ids_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("old-review", "TASK-100", "TASK-101", "implementer", "reviewer",
                 "2026-10-09T12:00:00Z", "2026-10-09T13:00:00Z",
                 "CHANGES_REQUESTED", '["blocking finding"]', '["fix it"]', "[]"),
            )
        with self.assertRaisesRegex(RegistryConflict, "DEPENDENCY_REVIEW_NOT_APPROVED"):
            self.apply(operation_id="unapproved", spec=self.spec(
                implementation_dependencies=("TASK-100",)
            ))
        self.assertIsNone(self.rows()[0][3])

    def test_mismatched_source_or_review_structure_is_rejected(self):
        spec = self.spec()
        spec["review"]["source_ref"] = "201"
        implementation, review, contracts = self.prepared(spec)
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_SOURCE_NOT_INDEPENDENT"):
            self.registry.recontract_on_deck_pair(
                implementation, review,
                expected_revision=self.registry.dispatch_control()["revision"],
                recorded_at="2026-10-10T12:00:00Z", operation_id="same-source",
                repository=self.repo, target_ref="main", contracts=contracts,
            )
        spec = self.spec()
        spec["review"]["dependency_ids"] = []
        with self.assertRaises(OperatorError):
            parse_on_deck_pair_spec(spec)


if __name__ == "__main__":
    unittest.main()
