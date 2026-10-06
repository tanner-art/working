from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.factory_registry import (
    Attempt,
    Evidence,
    Feature,
    Lane,
    PackageCapacityRisk,
    PackageCapacitySize,
    PackageKind,
    RegistryConflict,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
)
from scripts.factory_registry.models import ReviewInput
from scripts.factory_registry.sqlite_registry import _verify_operator_review_packet
from scripts.factory_registry.preservation_import import import_snapshot


class SQLiteRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def feature(self, feature_id: str = "FEATURE-1") -> None:
        self.registry.register_feature(Feature(feature_id, "Feature", 100, TaskStatus.READY))

    def worker(self, worker_id: str, *capabilities: str) -> None:
        self.registry.register_worker(
            Worker(worker_id, worker_id, capabilities, (Lane.PLATFORM,), usage_state="GREEN")
        )

    def package(
        self,
        package_id: str,
        *,
        dependencies: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = ("registry",),
    ) -> None:
        self.registry.register_work_package(
            WorkPackage(
                package_id,
                "FEATURE-1",
                package_id,
                "ORCHESTRATION",
                Lane.PLATFORM,
                capabilities,
                100,
                ("test evidence exists",),
                status=TaskStatus.READY,
                dependency_ids=dependencies,
            )
        )

    def test_v2_review_ready_is_derived_from_immutable_registry_input(self) -> None:
        self.feature()
        self.registry.register_work_package(WorkPackage(
            "TARGET", "FEATURE-1", "target", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 100, ("implemented",), status=TaskStatus.READY,
        ))
        self.registry.register_work_package(WorkPackage(
            "REVIEW", "FEATURE-1", "review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 100, ("reviewed",),
            status=TaskStatus.READY, kind=PackageKind.REVIEW,
            dependency_ids=("TARGET",),
            provider_diagnostics={"readiness_schema_version": 2,
                                  "queue_contract_sha256": "c" * 64,
                                  "readiness_proof": {
                                      "base_commit": "b" * 40, "target_ref": "main",
                                      "queue_contract_sha256": "c" * 64,
                                      "acceptance_sha256": hashlib.sha256(
                                          b'["reviewed"]'
                                      ).hexdigest(),
                                      "planning_sha256": {"docs/PLAN.md": "d" * 64},
                                  }},
        ))
        self.registry.register_worker(Worker(
            "reviewer", "Reviewer", ("independent-review",), (Lane.ASSURANCE,),
        ))
        self.worker("implementer", "registry")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-10-05T09:59:00Z", reason="disposable review fixture",
        )
        self.registry.acquire_lease(
            "TARGET", "implementer", acquired_at="2026-10-05T10:00:00Z",
            expires_at="2026-10-05T11:00:00Z",
        )
        self.registry.begin_attempt_runtime(
            "attempt-1", package_id="TARGET", worker_id="implementer",
            runner_pid=1, started_at="2026-10-05T10:00:01Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "attempt-1", ended_at="2026-10-05T10:10:00Z", outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW, reason="fixture implementation",
        )
        projected = next(item for item in self.registry.dispatch_snapshot(
            observed_at="2026-10-05T12:00:00Z"
        ).work_packages if item["id"] == "REVIEW")
        self.assertIn("REVIEW_INPUT_COUNT_INVALID:0", projected["review_readiness_reasons"])
        from scripts.factory_registry.control_center_projection import project_control_center
        control = project_control_center(self.registry.control_center_snapshot(
            observed_at="2026-10-05T12:00:00Z"
        ))
        review_card = next(package for feature in control["features"]
                           for package in feature["packages"] if package["id"] == "REVIEW")
        self.assertIn("REVIEW_INPUT_COUNT_INVALID:0", review_card["blockReason"])
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_NOT_READY"):
            self.registry.acquire_lease(
                "REVIEW", "reviewer", acquired_at="2026-10-05T12:00:00Z",
                expires_at="2026-10-05T13:00:00Z",
            )
        packet = self.root / "review-packet"
        packet.mkdir()
        contract = {"task": "TARGET", "instructions": "review exact implementation"}
        contents = {
            "base-to-implementation.diff": b"diff",
            "changed-files.txt": b"file\n",
            "contract.json": (json.dumps(contract, sort_keys=True) + "\n").encode(),
            "validation-evidence.json": b"{}",
        }
        for name, content in contents.items():
            (packet / name).write_bytes(content)
        files = {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}
        manifest = {
            "schema_version": 1, "implementation_attempt_id": "attempt-1",
            "implementation_commit": "a" * 40, "base_commit": "b" * 40,
            "files": files,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        (packet / "manifest.json").write_bytes(manifest_bytes)
        self.registry.record_review_input(ReviewInput(
            id="review-input-1", review_package_id="REVIEW", target_package_id="TARGET",
            implementation_attempt_id="attempt-1", implementation_commit="a" * 40,
            base_commit="b" * 40, pr_url="https://example.test/pr/1",
            contract_sha256=hashlib.sha256(json.dumps(
                contract, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest(),
            contract=contract,
            validation_evidence={
                "ci": {"state": "SUCCESS", "implementation_commit": "a" * 40,
                       "pr_url": "https://example.test/pr/1"},
                "review_packet": {"path": str(packet),
                                  "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                                  "files": files},
            },
            recorded_at="2026-10-05T10:11:00Z",
        ))

        def reasons():
            return next(item for item in self.registry.dispatch_snapshot(
                observed_at="2026-10-05T12:00:00Z"
            ).work_packages if item["id"] == "REVIEW")["review_readiness_reasons"]

        self.assertEqual(reasons(), ())
        # The dispatch snapshot can be valid before a prerequisite disappears.
        # The lease transaction must recheck the packet instead of trusting it.
        eligible_snapshot = self.registry.dispatch_snapshot(observed_at="2026-10-05T12:00:00Z")
        self.assertEqual(next(item for item in eligible_snapshot.work_packages
                              if item["id"] == "REVIEW")["review_readiness_reasons"], ())
        (packet / "contract.json").write_text("tampered")
        self.assertIn("REVIEW_INPUT_INVALID:REVIEW_PACKET_FILE_MISMATCH", reasons())
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_NOT_READY"):
            self.registry.acquire_lease(
                "REVIEW", "reviewer", acquired_at="2026-10-05T12:00:01Z",
                expires_at="2026-10-05T13:00:01Z",
            )
        (packet / "contract.json").write_bytes(contents["contract.json"])
        self.assertEqual(reasons(), ())
        lease = self.registry.acquire_lease(
            "REVIEW", "reviewer", acquired_at="2026-10-05T12:00:02Z",
            expires_at="2026-10-05T13:00:02Z",
        )
        self.assertEqual(lease.package_id, "REVIEW")

    def test_v2_ready_contract_and_feature_promotion_are_atomic(self) -> None:
        self.registry.register_feature(Feature(
            "PENDING", "Pending", 10, TaskStatus.ON_DECK,
        ))

        def candidate(digest: str, *, criteria=("verify outcome",),
                      package_id="TASK-READY", feature_id="PENDING") -> WorkPackage:
            proof = {
                "base_commit": "b" * 40, "target_ref": "main",
                "queue_contract_sha256": digest,
                "acceptance_sha256": hashlib.sha256(json.dumps(
                    criteria, separators=(",", ":")
                ).encode()).hexdigest(),
                "planning_sha256": {"docs/PLAN.md": "d" * 64},
            }
            return WorkPackage(
                package_id, feature_id, "ready", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 10, criteria, status=TaskStatus.READY,
                provider_diagnostics={"readiness_schema_version": 2,
                                      "queue_contract_sha256": digest,
                                      "readiness_proof": proof},
            )

        with self.assertRaisesRegex(RegistryConflict, "READY_CONTRACT_INCOMPLETE"):
            self.registry.register_work_package(candidate("bad"))
        with self.assertRaisesRegex(RegistryConflict, "READY_CONTRACT_INCOMPLETE"):
            self.registry.register_work_package(candidate("a" * 64, criteria=()))
        self.registry.register_work_package(WorkPackage(
            "TASK-PROOFLESS", "PENDING", "proofless", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 10, ("verify outcome",), status=TaskStatus.ON_DECK,
            provider_diagnostics={"readiness_schema_version": 2,
                                  "queue_contract_sha256": "a" * 64},
        ))
        with self.assertRaisesRegex(RegistryConflict, "READY_CONTRACT_INCOMPLETE"):
            self.registry.transition_work_package(
                "TASK-PROOFLESS", expected_status=TaskStatus.ON_DECK,
                new_status=TaskStatus.READY, changed_at="2026-10-05T10:00:00Z",
            )
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT status FROM features WHERE id='PENDING'"
            ).fetchone()[0], "ON_DECK")
            self.assertIsNone(connection.execute(
                "SELECT id FROM work_packages WHERE id='TASK-READY'"
            ).fetchone())
            self.assertEqual(connection.execute(
                "SELECT status FROM work_packages WHERE id='TASK-PROOFLESS'"
            ).fetchone()[0], "ON_DECK")
        self.registry.register_work_package(candidate("a" * 64))
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT status FROM features WHERE id='PENDING'"
            ).fetchone()[0], "READY")
            self.assertEqual(connection.execute(
                "SELECT status FROM work_packages WHERE id='TASK-READY'"
            ).fetchone()[0], "READY")
        self.registry.register_feature(Feature("SECOND", "Second", 10, TaskStatus.ON_DECK))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.registry.register_work_package, (
                candidate("a" * 64, package_id="SECOND-A", feature_id="SECOND"),
                candidate("a" * 64, package_id="SECOND-B", feature_id="SECOND"),
            )))
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT status FROM features WHERE id='SECOND'"
            ).fetchone()[0], "READY")
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM work_packages WHERE feature_id='SECOND' AND status='READY'"
            ).fetchone()[0], 2)

    def test_review_readiness_accepts_verified_external_integration_lineage(self) -> None:
        from scripts.factory_registry.test_external_integration_review import ExternalIntegrationReviewTests

        fixture = ExternalIntegrationReviewTests()
        fixture.setUp()
        try:
            review_input = fixture.review_input()
            fixture.registry.record_external_integration_review_input(
                review_input, expected_revision=fixture.registry.dispatch_control()["revision"],
            )
            with fixture.registry._connection() as connection:
                self.assertEqual(
                    fixture.registry._review_readiness_reasons(connection, "TASK-232"), ()
                )
            (Path(review_input.validation_evidence["review_packet"]["path"]) /
             "contract.json").write_text("tampered")
            with fixture.registry._connection() as connection:
                self.assertIn(
                    "REVIEW_INPUT_INVALID:REVIEW_PACKET_FILE_MISMATCH",
                    fixture.registry._review_readiness_reasons(connection, "TASK-232"),
                )
        finally:
            fixture.temporary.cleanup()

    def test_external_bridge_cannot_promote_v2_review_without_proof(self) -> None:
        from scripts.factory_registry.test_external_integration_review import ExternalIntegrationReviewTests

        fixture = ExternalIntegrationReviewTests()
        original = SQLiteRegistry.register_work_package

        def register_proofless_review(registry, package):
            if package.id == "TASK-232":
                package = replace(package, provider_diagnostics={
                    **package.provider_diagnostics, "readiness_schema_version": 2,
                })
            return original(registry, package)

        with patch.object(SQLiteRegistry, "register_work_package", register_proofless_review):
            fixture.setUp()
        try:
            revision = fixture.registry.dispatch_control()["revision"]
            with self.assertRaisesRegex(RegistryConflict, "READY_CONTRACT_INCOMPLETE"):
                fixture.registry.record_external_integration_review_input(
                    fixture.review_input(), expected_revision=revision,
                )
            snapshot = fixture.registry.control_center_snapshot(observed_at=fixture.stamp(7))
            self.assertEqual(
                next(item["status"] for item in snapshot.work_packages
                     if item["id"] == "TASK-232"), "ON_DECK",
            )
            self.assertFalse([item for item in snapshot.evidence
                              if item["package_id"] == "TASK-232" and item["kind"] == "review-input"])
        finally:
            fixture.temporary.cleanup()

    def test_v2_external_bridge_review_can_claim_with_verified_lineage(self) -> None:
        from scripts.factory_registry.test_external_integration_review import ExternalIntegrationReviewTests

        fixture = ExternalIntegrationReviewTests()
        original = SQLiteRegistry.register_work_package

        def register_v2_review(registry, package):
            if package.id == "TASK-232":
                digest = package.provider_diagnostics["queue_contract_sha256"]
                proof = {
                    "base_commit": "b" * 40, "target_ref": "main",
                    "queue_contract_sha256": digest,
                    "acceptance_sha256": hashlib.sha256(b'["strict verdict"]').hexdigest(),
                    "planning_sha256": {"docs/PLAN.md": "d" * 64},
                }
                package = replace(package, provider_diagnostics={
                    **package.provider_diagnostics, "readiness_schema_version": 2,
                    "readiness_proof": proof,
                })
            return original(registry, package)

        with patch.object(SQLiteRegistry, "register_work_package", register_v2_review):
            fixture.setUp()
        try:
            fixture.registry.record_external_integration_review_input(
                fixture.review_input(),
                expected_revision=fixture.registry.dispatch_control()["revision"],
            )
            with fixture.registry._connection() as connection:
                self.assertEqual(
                    fixture.registry._review_readiness_reasons(connection, "TASK-232"), ()
                )
            fixture.registry.set_dispatch_control(
                expected_revision=fixture.registry.dispatch_control()["revision"],
                expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False,
                changed_at=fixture.stamp(8), reason="v2 external review fixture",
            )
            lease = fixture.registry.acquire_lease(
                "TASK-232", "claude", acquired_at=fixture.stamp(9),
                expires_at=fixture.stamp(120),
            )
            self.assertEqual(lease.package_id, "TASK-232")
        finally:
            fixture.temporary.cleanup()

    def test_uses_wal_and_expected_schema_version(self) -> None:
        self.assertEqual(self.registry.journal_mode(), "wal")
        with sqlite3.connect(self.database) as connection:
            versions = dict(connection.execute(
                """SELECT key, value FROM registry_metadata
                   WHERE key IN ('schema_version', 'control_schema_version')"""
            ).fetchall())
        self.assertEqual(
            versions,
            {"schema_version": "6", "control_schema_version": "1"},
        )

    def test_historical_reconciliation_retires_queue_without_rewriting_review_history(self) -> None:
        self.feature()
        self.package("STALE")
        self.registry.register_work_package(WorkPackage(
            "REVIEW", "FEATURE-1", "historical review", "ASSURANCE", Lane.PLATFORM,
            ("review",), 1, ("preserved",), status=TaskStatus.DONE,
            kind=PackageKind.REVIEW, dependency_ids=("STALE",),
        ))
        self.worker("implementer", "registry")
        self.worker("reviewer", "review")
        with self.registry._connection() as connection:
            connection.execute(
                """INSERT INTO review_outcomes
                   (id, review_package_id, target_package_id, implementer_worker_id,
                    reviewer_worker_id, requested_at, decided_at, state, findings_json,
                    changes_requested_json, approval_evidence_ids_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("changes", "REVIEW", "STALE", "implementer", "reviewer",
                 "2026-09-28T10:00:00Z", "2026-09-28T10:01:00Z", "CHANGES_REQUESTED",
                 "[]", '["fix"]', "[]"),
            )
        revision = self.registry.dispatch_control()["revision"]
        result = self.registry.reconcile_historical_package(
            reconciliation_id="reconcile-stale", package_id="STALE",
            disposition="INTEGRATED_ELSEWHERE", historical_commit="a" * 40,
            integration_commit="b" * 40, repository_head="c" * 40,
            evidence_uri="https://example.test/commit/c", expected_revision=revision,
            recorded_at="2026-09-28T11:00:00Z",
        )
        self.assertEqual(result, revision + 1)
        snapshot = self.registry.control_center_snapshot(observed_at="2026-09-28T11:01:00Z")
        package = next(item for item in snapshot.work_packages if item["id"] == "STALE")
        self.assertEqual(package["status"], "DONE")
        self.assertEqual(snapshot.review_outcomes[0]["state"], "CHANGES_REQUESTED")
        event = next(item for item in snapshot.events if item["event_type"] == "HISTORICAL_PACKAGE_RECONCILED")
        self.assertFalse(event["detail"]["review_passed"])
        with self.assertRaisesRegex(RegistryConflict, "ALREADY_RECORDED"):
            self.registry.reconcile_historical_package(
                reconciliation_id="another", package_id="STALE", disposition="SUPERSEDED",
                historical_commit="a" * 40, integration_commit="b" * 40,
                repository_head="c" * 40, evidence_uri="https://example.test/commit/c",
                expected_revision=result, recorded_at="2026-09-28T11:02:00Z",
            )

    def test_legacy_source_binding_is_contract_pinned_and_idempotent(self) -> None:
        self.feature()
        contract = {"task": "TASK-LEGACY", "depends_on": [], "paths": ["docs/legacy.md"]}
        digest = hashlib.sha256(json.dumps(
            contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        self.registry.register_work_package(WorkPackage(
            "TASK-LEGACY", "FEATURE-1", "legacy", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 1, ("preserved",), status=TaskStatus.ON_DECK,
            provider_diagnostics={"queue_contract_sha256": digest},
        ))
        revision = self.registry.dispatch_control()["revision"]
        bound = self.registry.bind_legacy_package_source(
            "TASK-LEGACY", github_issue=173, queue_contract=contract,
            expected_revision=revision, recorded_at="2026-09-27T12:00:00Z",
        )
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-27T12:00:01Z")
        package = next(value for value in snapshot.work_packages if value["id"] == "TASK-LEGACY")
        self.assertEqual((package["source_system"], package["source_ref"]), ("github_issue", "173"))
        self.assertEqual(self.registry.bind_legacy_package_source(
            "TASK-LEGACY", github_issue=173, queue_contract=contract,
            expected_revision=bound, recorded_at="2026-09-27T12:00:02Z",
        ), bound)
        with self.assertRaisesRegex(RegistryConflict, "QUEUE_CONTRACT_MISMATCH"):
            self.registry.bind_legacy_package_source(
                "TASK-LEGACY", github_issue=173, queue_contract={"task": "TASK-LEGACY"},
                expected_revision=bound, recorded_at="2026-09-27T12:00:03Z",
            )
        with self.assertRaisesRegex(RegistryConflict, "GITHUB_SOURCE_REPLACEMENT_FORBIDDEN"):
            self.registry.bind_legacy_package_source(
                "TASK-LEGACY", github_issue=174, queue_contract=contract,
                expected_revision=bound, recorded_at="2026-09-27T12:00:04Z",
            )
        with self.registry._connection() as connection:
            history = connection.execute(
                "SELECT event_type FROM task_events WHERE package_id='TASK-LEGACY'"
            ).fetchall()
        self.assertEqual([row[0] for row in history], ["LEGACY_SOURCE_BOUND"])

    def test_legacy_source_binding_rejects_each_gate_without_rewriting_history(self) -> None:
        self.feature()
        contract = {"task": "TASK-LEGACY", "depends_on": [], "paths": ["docs/legacy.md"]}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.registry.register_work_package(WorkPackage("DEPENDENCY", "FEATURE-1", "dependency", "ORCHESTRATION", Lane.PLATFORM, ("registry",), 1, ("preserved",), status=TaskStatus.DONE))
        self.registry.register_work_package(WorkPackage("TASK-LEGACY", "FEATURE-1", "legacy", "ORCHESTRATION", Lane.PLATFORM, ("registry",), 1, ("preserved",), status=TaskStatus.ON_DECK, provider_diagnostics={"queue_contract_sha256": digest}, dependency_ids=("DEPENDENCY",)))
        def bind(**kwargs):
            return self.registry.bind_legacy_package_source("TASK-LEGACY", github_issue=173, queue_contract=contract, expected_revision=self.registry.dispatch_control()["revision"], recorded_at="2026-09-27T12:00:00Z", **kwargs)
        # Each fixture changes only the gate it names; no failed request rewrites the source/dependency/history.
        with self.registry._connection() as connection:
            connection.execute("UPDATE work_packages SET status='VERIFY_REVIEW' WHERE id='TASK-LEGACY'")
        with self.assertRaisesRegex(RegistryConflict, "STATUS_INVALID"): bind()
        with self.registry._connection() as connection:
            connection.execute("UPDATE work_packages SET status='ON_DECK' WHERE id='TASK-LEGACY'")
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("INSERT INTO attempts(id, package_id, worker_id, lease_id, started_at, ended_at, outcome, provider_diagnostics_json) VALUES ('old', 'TASK-LEGACY', 'w', 'l', '2026-09-26T00:00:00Z', '2026-09-26T00:01:00Z', 'FAILED', '{}')")
        with self.assertRaisesRegex(RegistryConflict, "ATTEMPT_HISTORY"): bind()
        with self.registry._connection() as connection:
            connection.execute("DELETE FROM attempts WHERE id='old'")
        revision = bind()
        self.assertEqual(bind(), revision)
        with self.assertRaisesRegex(RegistryConflict, "REPLACEMENT_FORBIDDEN"):
            self.registry.bind_legacy_package_source("TASK-LEGACY", github_issue=174, queue_contract=contract, expected_revision=revision, recorded_at="2026-09-27T12:00:01Z")
        with self.registry._connection() as connection:
            dependencies = connection.execute("SELECT dependency_id FROM task_dependencies WHERE package_id='TASK-LEGACY'").fetchall()
        self.assertEqual([row[0] for row in dependencies], ["DEPENDENCY"])

    def test_legacy_source_binding_rejects_active_ownership_and_changed_digest_without_mutation(self) -> None:
        self.feature()
        contract = {"task": "TASK-LEGACY", "depends_on": [], "paths": ["docs/legacy.md"]}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.registry.register_work_package(WorkPackage(
            "DEPENDENCY", "FEATURE-1", "dependency", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 1, ("preserved",), status=TaskStatus.DONE,
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK-LEGACY", "FEATURE-1", "legacy", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 1, ("preserved",), status=TaskStatus.READY,
            dependency_ids=("DEPENDENCY",),
            provider_diagnostics={"queue_contract_sha256": digest},
        ))
        revision = self.registry.dispatch_control()["revision"]
        bound = self.registry.bind_legacy_package_source(
            "TASK-LEGACY", github_issue=173, queue_contract=contract,
            expected_revision=revision, recorded_at="2026-09-27T12:00:00Z",
        )

        self.worker("owner", "registry")
        lease = self.registry.acquire_lease(
            "TASK-LEGACY", "owner", acquired_at="2026-09-27T12:01:00Z",
            expires_at="2026-09-27T12:11:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_OWNERSHIP_PRESENT"):
            self.registry.bind_legacy_package_source(
                "TASK-LEGACY", github_issue=173, queue_contract=contract,
                expected_revision=self.registry.dispatch_control()["revision"], recorded_at="2026-09-27T12:02:00Z",
            )
        self.registry.release_lease(
            lease.id, released_at="2026-09-27T12:03:00Z", reason="fixture",
            next_status=TaskStatus.READY,
        )

        def preserved_state():
            with self.registry._connection() as connection:
                package = connection.execute(
                    "SELECT source_system, source_ref, status, provider_diagnostics_json FROM work_packages WHERE id='TASK-LEGACY'"
                ).fetchone()
                dependencies = connection.execute(
                    "SELECT dependency_id FROM task_dependencies WHERE package_id='TASK-LEGACY' ORDER BY dependency_id"
                ).fetchall()
                events = connection.execute(
                    "SELECT event_type FROM task_events WHERE package_id='TASK-LEGACY' ORDER BY rowid"
                ).fetchall()
            return tuple(package), tuple(row[0] for row in dependencies), tuple(row[0] for row in events)

        before = preserved_state()
        with self.assertRaisesRegex(RegistryConflict, "QUEUE_CONTRACT_MISMATCH"):
            self.registry.bind_legacy_package_source(
                "TASK-LEGACY", github_issue=173,
                queue_contract={**contract, "paths": ["docs/changed.md"]},
                expected_revision=self.registry.dispatch_control()["revision"], recorded_at="2026-09-27T12:04:00Z",
            )
        self.assertEqual(preserved_state(), before)

    def test_operator_review_input_requires_paused_drained_target_attempt_and_is_single_write(self) -> None:
        self.feature(); self.worker("implementer", "registry")
        self.package("TARGET")
        self.registry.register_work_package(WorkPackage("REVIEW", "FEATURE-1", "review", "ASSURANCE", Lane.ASSURANCE, ("review",), 1, ("review",), status=TaskStatus.READY, kind=PackageKind.REVIEW, dependency_ids=("TARGET",)))
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False, changed_at="2026-09-27T10:00:00Z", reason="fixture")
        self.registry.acquire_lease("TARGET", "implementer", acquired_at="2026-09-27T10:00:00Z", expires_at="2026-09-27T11:00:00Z")
        self.registry.begin_attempt_runtime("attempt", package_id="TARGET", worker_id="implementer", runner_pid=1, started_at="2026-09-27T10:00:01Z", expected_revision=self.registry.dispatch_control()["revision"])
        self.registry.finish_attempt_runtime("attempt", ended_at="2026-09-27T10:01:00Z", outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="done")
        self.registry.engage_dispatch_kill_switch(changed_at="2026-09-27T10:01:01Z", reason="pause")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(expected_revision=control["revision"], expected_mode="STOPPING", new_mode="PAUSED", kill_switch_engaged=True, changed_at="2026-09-27T10:01:02Z", reason="drained")
        packet = self.root / "packet"; packet.mkdir(); contract = {"task": "TARGET"}
        files = {"base-to-implementation.diff": b"d", "changed-files.txt": b"f\n", "contract.json": json.dumps(contract, sort_keys=True).encode(), "validation-evidence.json": b"{}"}
        for name, value in files.items(): (packet / name).write_bytes(value)
        hashes = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
        manifest = {"schema_version": 1, "implementation_attempt_id": "attempt", "base_commit": "b" * 40, "implementation_commit": "a" * 40, "files": hashes}; raw = json.dumps(manifest, sort_keys=True).encode(); (packet / "manifest.json").write_bytes(raw)
        value = ReviewInput("input", "REVIEW", "TARGET", "attempt", "a" * 40, "b" * 40, "https://example.test/pr", hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), contract, {"ci": {"state": "SUCCESS", "implementation_commit": "a" * 40, "pr_url": "https://example.test/pr"}, "review_packet": {"path": str(packet), "manifest_sha256": hashlib.sha256(raw).hexdigest(), "files": hashes}}, "2026-09-27T10:02:00Z")
        revision = self.registry.dispatch_control()["revision"]
        self.assertEqual(self.registry.record_operator_review_input(value, expected_revision=revision), revision + 1)
        with self.assertRaisesRegex(RegistryConflict, "ALREADY_RECORDED"):
            self.registry.record_operator_review_input(value, expected_revision=revision + 1)

    def test_operator_review_input_rejects_write_gates_without_changing_evidence_or_state(self) -> None:
        self.feature(); self.worker("implementer", "registry")
        self.registry.register_worker(Worker(
            "reviewer", "reviewer", ("review",), (Lane.ASSURANCE,), usage_state="GREEN"
        ))
        self.package("TARGET")
        self.registry.register_work_package(WorkPackage(
            "REVIEW", "FEATURE-1", "review", "ASSURANCE", Lane.ASSURANCE,
            ("review",), 1, ("review",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("TARGET",),
        ))
        packet = self.root / "packet-negative"; packet.mkdir()
        contract = {"task": "TARGET"}
        files = {"base-to-implementation.diff": b"d", "changed-files.txt": b"f\n",
                 "contract.json": json.dumps(contract, sort_keys=True).encode(), "validation-evidence.json": b"{}"}
        for name, content in files.items(): (packet / name).write_bytes(content)
        hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
        manifest = {"schema_version": 1, "implementation_attempt_id": "attempt", "base_commit": "b" * 40,
                    "implementation_commit": "a" * 40, "files": hashes}
        raw = json.dumps(manifest, sort_keys=True).encode(); (packet / "manifest.json").write_bytes(raw)
        value = ReviewInput(
            "input", "REVIEW", "TARGET", "attempt", "a" * 40, "b" * 40,
            "https://example.test/pr", hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            contract, {"ci": {"state": "SUCCESS", "implementation_commit": "a" * 40, "pr_url": "https://example.test/pr"},
                       "review_packet": {"path": str(packet), "manifest_sha256": hashlib.sha256(raw).hexdigest(), "files": hashes}},
            "2026-09-27T10:02:00Z",
        )

        def unchanged():
            with self.registry._connection() as connection:
                return (
                    connection.execute("SELECT status FROM work_packages WHERE id='REVIEW'").fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM evidence WHERE package_id='REVIEW'").fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM task_events WHERE package_id='REVIEW'").fetchone()[0],
                    self.registry.dispatch_control()["revision"],
                )

        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False, changed_at="2026-09-27T09:59:00Z", reason="historical fixture")
        self.registry.acquire_lease("TARGET", "implementer", acquired_at="2026-09-27T09:59:00Z", expires_at="2026-09-27T10:59:00Z")
        self.registry.begin_attempt_runtime("attempt", package_id="TARGET", worker_id="implementer", runner_pid=1, started_at="2026-09-27T09:59:01Z", expected_revision=self.registry.dispatch_control()["revision"])
        self.registry.finish_attempt_runtime("attempt", ended_at="2026-09-27T09:59:02Z", outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="historical success")
        before = unchanged()
        with self.assertRaisesRegex(RegistryConflict, "REQUIRES_PAUSED"):
            self.registry.record_operator_review_input(value, expected_revision=before[3])
        self.assertEqual(unchanged(), before)

        self.registry.engage_dispatch_kill_switch(changed_at="2026-09-27T10:00:01Z", reason="drain")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(expected_revision=control["revision"], expected_mode="STOPPING", new_mode="PAUSED", kill_switch_engaged=True, changed_at="2026-09-27T10:00:02Z", reason="paused")
        lease = self.registry.acquire_lease("REVIEW", "reviewer", acquired_at="2026-09-27T10:00:03Z", expires_at="2026-09-27T11:00:00Z")
        before = unchanged()
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_OWNERSHIP_PRESENT"):
            self.registry.record_operator_review_input(value, expected_revision=before[3])
        self.assertEqual(unchanged(), before)
        self.registry.release_lease(lease.id, released_at="2026-09-27T10:00:03Z", reason="fixture", next_status=TaskStatus.READY)

        mismatch = ReviewInput(**{**value.__dict__, "target_package_id": "OTHER"})
        before = unchanged()
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_TARGET_MISMATCH"):
            self.registry.record_operator_review_input(mismatch, expected_revision=before[3])
        self.assertEqual(unchanged(), before)

    def test_followup_registration_restores_global_ready_active_exclusivity(self) -> None:
        self.feature()
        contract = {"task": "TASK-351", "depends_on": [173], "paths": ["docs/review.md"]}
        digest = hashlib.sha256(json.dumps(
            contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        self.registry.register_work_package(WorkPackage(
            "UNRELATED", "FEATURE-1", "unrelated", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 1, ("preserved",), status=TaskStatus.READY,
        ))
        review = WorkPackage(
            "TASK-351", "FEATURE-1", "review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("independent",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("MISSING",),
            provider_diagnostics={
                "github_source_ref": "312", "queue_contract_sha256": digest,
            },
        )
        for status in ("READY", "ACTIVE"):
            with self.subTest(status=status):
                with self.registry._connection() as connection:
                    connection.execute("UPDATE work_packages SET status=? WHERE id='UNRELATED'", (status,))
                with self.assertRaisesRegex(RegistryConflict, "CANARY_NOT_EXCLUSIVE"):
                    self.registry.register_followup_review(
                        review, expected_revision=self.registry.dispatch_control()["revision"],
                        recorded_at="2026-09-27T12:00:00Z",
                    )

    def test_followup_registration_ignores_only_ready_review_with_blocked_parent(self) -> None:
        self.feature()
        contract = {"task": "TASK-351", "depends_on": [173], "paths": ["docs/review.md"]}
        digest = hashlib.sha256(json.dumps(
            contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        self.registry.register_work_package(WorkPackage(
            "TASK173", "FEATURE-1", "target", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 1, ("preserved",), status=TaskStatus.VERIFY_REVIEW,
        ))
        self.registry.register_work_package(WorkPackage(
            "PRIOR-REVIEW", "FEATURE-1", "prior review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("preserved",), status=TaskStatus.DONE,
            kind=PackageKind.REVIEW, dependency_ids=("TASK173",),
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK329", "FEATURE-1", "blocked parent", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 1, ("preserved",), status=TaskStatus.BLOCKED,
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK330", "FEATURE-1", "blocked-parent review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("preserved",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("TASK329",),
        ))
        self.worker("implementer", "registry")
        self.registry.register_worker(Worker(
            "reviewer", "reviewer", ("review",), (Lane.ASSURANCE,), usage_state="GREEN",
        ))
        with self.registry._connection() as connection:
            connection.execute(
                """INSERT INTO review_outcomes
                   (id, review_package_id, target_package_id,
                    implementer_worker_id, reviewer_worker_id,
                    requested_at, decided_at, state, findings_json,
                    changes_requested_json, approval_evidence_ids_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "prior-changes", "PRIOR-REVIEW", "TASK173", "implementer", "reviewer",
                    "2026-09-27T11:00:00.000000Z", "2026-09-27T11:01:00.000000Z",
                    "CHANGES_REQUESTED", "[]", '["retry"]', "[]",
                ),
            )
        review = WorkPackage(
            "TASK-351", "FEATURE-1", "follow-up review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("independent",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("TASK173",),
            provider_diagnostics={
                "github_source_ref": "312", "queue_contract_sha256": digest,
            },
        )

        self.registry.register_followup_review(
            review, expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at="2026-09-27T12:00:00Z",
        )

        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-27T12:00:01Z")
        packages = {package["id"]: package for package in snapshot.work_packages}
        self.assertEqual(packages["TASK330"]["status"], TaskStatus.READY.value)
        self.assertEqual(packages["TASK-351"]["status"], TaskStatus.READY.value)
        self.assertEqual(packages["TASK-351"]["source_ref"], "312")
        self.assertIn(
            {"package_id": "TASK-351", "dependency_id": "TASK173"},
            snapshot.dependencies,
        )

    def test_operator_review_packet_requires_exact_hashes_contract_and_green_ci(self) -> None:
        packet = self.root / "packet"
        packet.mkdir()
        contract = {"task": "TASK-1"}
        contents = {
            "base-to-implementation.diff": b"diff", "changed-files.txt": b"file\n",
            "contract.json": json.dumps(contract, sort_keys=True).encode(),
            "validation-evidence.json": b"{}",
        }
        for name, content in contents.items():
            (packet / name).write_bytes(content)
        files = {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}
        manifest = {"schema_version": 1, "implementation_attempt_id": "attempt", "base_commit": "b" * 40,
                    "implementation_commit": "a" * 40, "files": files}
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        (packet / "manifest.json").write_bytes(manifest_bytes)
        review_input = ReviewInput(
            id="input", review_package_id="REVIEW", target_package_id="TASK-1",
            implementation_attempt_id="attempt", implementation_commit="a" * 40,
            base_commit="b" * 40, pr_url="https://example.test/pr",
            contract_sha256=hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            contract=contract,
            validation_evidence={"ci": {"state": "SUCCESS", "implementation_commit": "a" * 40, "pr_url": "https://example.test/pr"},
                                 "review_packet": {"path": str(packet), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "files": files}},
            recorded_at="2026-09-27T12:00:00Z",
        )
        _verify_operator_review_packet(review_input)
        (packet / "contract.json").write_text('{"task":"tampered"}')
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_PACKET_FILE_MISMATCH"):
            _verify_operator_review_packet(review_input)

    def test_initialize_additively_upgrades_version_one_registry(self) -> None:
        legacy_database = self.root / "legacy.sqlite3"
        with sqlite3.connect(legacy_database) as connection:
            connection.execute(
                "CREATE TABLE registry_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO registry_metadata(key, value) VALUES ('schema_version', '1')"
            )
            connection.execute(
                "INSERT INTO registry_metadata(key, value) VALUES ('legacy_marker', 'preserved')"
            )
        legacy = SQLiteRegistry(legacy_database)
        legacy.initialize()
        with sqlite3.connect(legacy_database) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM registry_metadata"))
            usage_tables = connection.execute(
                """SELECT count(*) FROM sqlite_master
                   WHERE type='table' AND name IN ('usage_ledger', 'usage_ledger_sources')"""
            ).fetchone()[0]
            package_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(work_packages)")
            }
        self.assertEqual(metadata["schema_version"], "6")
        self.assertEqual(metadata["legacy_marker"], "preserved")
        self.assertEqual(usage_tables, 2)
        self.assertTrue({"capacity_size", "capacity_risk"}.issubset(package_columns))

    def test_initialize_refuses_unreviewed_schema_version_three_migration(self) -> None:
        database = self.root / "pre-a4b-v3.sqlite3"
        legacy = SQLiteRegistry(database)
        legacy.initialize()
        legacy.register_feature(Feature("PRESERVED", "Preserved feature", 100, TaskStatus.READY))
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TABLE review_outcomes")
            connection.execute("DROP TABLE attempt_runtime_ownership")
            connection.execute("DROP TABLE factory_control")
            connection.execute(
                "UPDATE registry_metadata SET value='3' WHERE key='schema_version'"
            )
            connection.execute(
                "DELETE FROM registry_metadata WHERE key='control_schema_version'"
            )

        with self.assertRaisesRegex(
            RegistryConflict, "REGISTRY_V3_OPERATOR_MIGRATION_REQUIRED"
        ):
            legacy.initialize()

        with sqlite3.connect(database) as connection:
            metadata = dict(connection.execute(
                "SELECT key, value FROM registry_metadata "
                "WHERE key IN ('schema_version', 'control_schema_version')"
            ))
            preserved = connection.execute(
                "SELECT title FROM features WHERE id='PRESERVED'"
            ).fetchone()[0]
            runtime_table = connection.execute(
                "SELECT count(*) FROM sqlite_schema "
                "WHERE type='table' AND name='attempt_runtime_ownership'"
            ).fetchone()[0]
            review_outcome_table = connection.execute(
                "SELECT count(*) FROM sqlite_schema "
                "WHERE type='table' AND name='review_outcomes'"
            ).fetchone()[0]
        self.assertEqual(
            metadata,
            {"schema_version": "3"},
        )
        self.assertEqual(preserved, "Preserved feature")
        self.assertEqual(runtime_table, 0)
        self.assertEqual(review_outcome_table, 0)

    def test_initialize_refuses_unreviewed_schema_version_four_migration(self) -> None:
        database = self.root / "pre-cp01-v4.sqlite3"
        legacy = SQLiteRegistry(database)
        legacy.initialize()
        legacy.register_feature(Feature("PRESERVED", "Preserved feature", 100, TaskStatus.READY))
        with sqlite3.connect(database) as connection:
            connection.execute(
                "DROP TRIGGER control_operation_receipts_are_append_only_update"
            )
            connection.execute(
                "DROP TRIGGER control_operation_receipts_are_append_only_delete"
            )
            connection.execute("DROP TABLE control_operation_receipts")
            connection.execute(
                "UPDATE registry_metadata SET value='4' WHERE key='schema_version'"
            )

        with self.assertRaisesRegex(
            RegistryConflict, "REGISTRY_V4_OPERATOR_MIGRATION_REQUIRED"
        ):
            legacy.initialize()

        with sqlite3.connect(database) as connection:
            schema_version = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='schema_version'"
            ).fetchone()[0]
            receipt_table = connection.execute(
                "SELECT count(*) FROM sqlite_schema "
                "WHERE type='table' AND name='control_operation_receipts'"
            ).fetchone()[0]
            preserved = connection.execute(
                "SELECT title FROM features WHERE id='PRESERVED'"
            ).fetchone()[0]
        self.assertEqual(schema_version, "4")
        self.assertEqual(receipt_table, 0)
        self.assertEqual(preserved, "Preserved feature")

    def test_initialize_adds_capacity_fields_to_existing_version_one_packages(self) -> None:
        legacy_database = self.root / "legacy-capacity.sqlite3"
        with sqlite3.connect(legacy_database) as connection:
            connection.executescript(
                """
                CREATE TABLE registry_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO registry_metadata(key, value) VALUES
                    ('schema_version', '1'), ('revision', '0'),
                    ('active_parent_limit', '3'), ('orchestra_reserve_percent', '20');
                CREATE TABLE work_packages (
                    id TEXT PRIMARY KEY, feature_id TEXT NOT NULL, status TEXT NOT NULL,
                    priority INTEGER NOT NULL, ready_at TEXT, created_at TEXT NOT NULL,
                    kind TEXT NOT NULL, source_system TEXT, source_ref TEXT
                );
                INSERT INTO work_packages
                    (id, feature_id, status, priority, created_at, kind)
                    VALUES ('legacy', 'feature', 'READY', 1, '2026-09-24T00:00:00Z', 'PARENT');
                """
            )
        legacy = SQLiteRegistry(legacy_database)
        legacy.initialize()
        with sqlite3.connect(legacy_database) as connection:
            row = connection.execute(
                "SELECT capacity_size, capacity_risk FROM work_packages WHERE id='legacy'"
            ).fetchone()
            version = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(row, ("SUBSTANTIAL", "UNCERTAIN"))
        self.assertEqual(version, "6")

    def test_initialize_classifies_version_two_usage_provenance(self) -> None:
        legacy_database = self.root / "legacy-v2.sqlite3"
        legacy = SQLiteRegistry(legacy_database)
        legacy.initialize()
        legacy.register_feature(Feature("FEATURE", "Feature", 100, TaskStatus.READY))
        legacy.register_worker(
            Worker("claude", "Claude", ("registry",), (Lane.PLATFORM,))
        )
        for package_id in ("TASK", "OTHER"):
            legacy.register_work_package(
                WorkPackage(
                    package_id,
                    "FEATURE",
                    package_id,
                    "ORCHESTRATION",
                    Lane.PLATFORM,
                    ("registry",),
                    100,
                    ("evidence",),
                    status=TaskStatus.READY,
                )
            )
        legacy.register_attempt(
            Attempt("ATTEMPT", "TASK", "claude", "2026-09-24T20:00:00Z")
        )
        with sqlite3.connect(legacy_database) as connection:
            connection.execute("DROP TABLE usage_ledger_sources")
            connection.execute("DROP TABLE usage_ledger")
            connection.execute(
                """CREATE TABLE usage_ledger (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, worker_id TEXT NOT NULL,
                    account_id TEXT NOT NULL, invocation_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, package_id TEXT, attempt_id TEXT,
                    observed_at TEXT NOT NULL, model_diagnostic TEXT,
                    input_tokens INTEGER, output_tokens INTEGER,
                    cache_read_input_tokens INTEGER, cache_creation_input_tokens INTEGER,
                    duration_ms REAL, outcome TEXT NOT NULL, task_completed INTEGER NOT NULL,
                    review_completed INTEGER NOT NULL, limit_signal TEXT,
                    limit_reset_at TEXT, limit_raw_error TEXT,
                    calibration_metadata_json TEXT NOT NULL,
                    primary_source_type TEXT NOT NULL,
                    primary_source_identity TEXT NOT NULL UNIQUE,
                    primary_source_metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(provider, worker_id, account_id, invocation_id)
                )"""
            )
            values = (
                "anthropic", "claude", "account", "2026-09-24T20:00:00Z",
                "SUCCEEDED", "{}", "CLI_JSON", "{}", "2026-09-24T20:00:00Z",
            )
            connection.execute(
                """INSERT INTO usage_ledger
                   (id, provider, worker_id, account_id, invocation_id, session_id,
                    package_id, attempt_id, observed_at, outcome, task_completed,
                    review_completed, calibration_metadata_json, primary_source_type,
                    primary_source_identity, primary_source_metadata_json, created_at)
                   VALUES ('linked', ?, ?, ?, 'linked', 'session-linked', 'TASK',
                           'ATTEMPT', ?, ?, 0, 0, ?, ?, 'source-linked', ?, ?)""",
                values,
            )
            connection.execute(
                """INSERT INTO usage_ledger
                   (id, provider, worker_id, account_id, invocation_id, session_id,
                    observed_at, outcome, task_completed, review_completed,
                    calibration_metadata_json, primary_source_type,
                    primary_source_identity, primary_source_metadata_json, created_at)
                   VALUES ('probe', ?, ?, ?, 'probe', 'session-probe', ?, ?, 0, 0,
                           ?, ?, 'source-probe', ?, ?)""",
                values,
            )
            connection.execute(
                """INSERT INTO usage_ledger
                   (id, provider, worker_id, account_id, invocation_id, session_id,
                    package_id, attempt_id, observed_at, outcome, task_completed,
                    review_completed, calibration_metadata_json, primary_source_type,
                    primary_source_identity, primary_source_metadata_json, created_at)
                   VALUES ('mismatched', ?, ?, ?, 'mismatched', 'session-mismatched',
                           'OTHER', 'ATTEMPT', ?, ?, 0, 0, ?, ?, 'source-mismatched', ?, ?)""",
                values,
            )
            connection.execute(
                "UPDATE registry_metadata SET value='2' WHERE key='schema_version'"
            )
        legacy.initialize()
        with sqlite3.connect(legacy_database) as connection:
            classes = dict(
                connection.execute("SELECT id, observation_class FROM usage_ledger")
            )
            version = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(
            classes,
            {
                "linked": "AUTONOMOUS",
                "probe": "LEGACY_UNCLASSIFIED",
                "mismatched": "LEGACY_UNCLASSIFIED",
            },
        )
        self.assertEqual(version, "6")

    def test_initialize_rejects_invalid_versions_without_mutating_database(self) -> None:
        cases = (
            ("newer", "7", "SCHEMA_VERSION_UNSUPPORTED: 7"),
            ("malformed", "future", "SCHEMA_VERSION_INVALID: future"),
        )
        for label, version, error in cases:
            with self.subTest(label=label):
                database = self.root / f"{label}.sqlite3"
                connection = sqlite3.connect(database)
                try:
                    self.assertEqual(
                        connection.execute("PRAGMA journal_mode = WAL").fetchone()[0],
                        "wal",
                    )
                    connection.execute(
                        "CREATE TABLE registry_metadata "
                        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO registry_metadata(key, value) "
                        "VALUES ('schema_version', ?)",
                        (version,),
                    )
                    connection.execute(
                        "CREATE TABLE future_schema_marker "
                        "(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO future_schema_marker(value) VALUES ('preserve')"
                    )
                    connection.commit()
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    connection.close()
                for suffix in ("-wal", "-shm"):
                    Path(f"{database}{suffix}").unlink(missing_ok=True)

                def immutable_state() -> tuple[str, tuple[tuple[object, ...], ...]]:
                    uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
                    readonly = sqlite3.connect(uri, uri=True)
                    try:
                        stored_version = readonly.execute(
                            "SELECT value FROM registry_metadata WHERE key='schema_version'"
                        ).fetchone()[0]
                        schema = tuple(readonly.execute(
                            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
                            "ORDER BY type, name"
                        ))
                        return stored_version, schema
                    finally:
                        readonly.close()

                before_bytes = database.read_bytes()
                before_files = sorted(path.name for path in self.root.glob(f"{database.name}*"))
                before_version, before_schema = immutable_state()
                before_journal_header = before_bytes[18:20]
                self.assertEqual(before_journal_header, b"\x02\x02")
                self.assertEqual(before_files, [database.name])

                with self.assertRaisesRegex(RegistryConflict, error):
                    SQLiteRegistry(database).initialize()

                stored_version, after_schema = immutable_state()
                after_files = sorted(path.name for path in self.root.glob(f"{database.name}*"))
                after_bytes = database.read_bytes()

                self.assertEqual(stored_version, version)
                self.assertEqual(before_version, version)
                self.assertEqual(after_bytes[18:20], before_journal_header)
                self.assertEqual(after_schema, before_schema)
                self.assertEqual(after_bytes, before_bytes)
                self.assertEqual(after_files, before_files)

    def test_initialize_reads_active_wal_before_opening_source(self) -> None:
        cases = (
            ("newer-active", "7", "SCHEMA_VERSION_UNSUPPORTED: 7"),
            ("malformed-active", "future", "SCHEMA_VERSION_INVALID: future"),
        )
        for label, wal_version, error in cases:
            with self.subTest(label=label):
                database = self.root / f"{label}.sqlite3"
                connection = sqlite3.connect(database)
                try:
                    connection.execute(
                        "CREATE TABLE registry_metadata "
                        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO registry_metadata(key, value) "
                        "VALUES ('schema_version', '1')"
                    )
                    connection.execute(
                        "CREATE TABLE active_wal_marker "
                        "(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO active_wal_marker(value) VALUES ('main')"
                    )
                    connection.commit()
                    self.assertEqual(
                        connection.execute("PRAGMA journal_mode = WAL").fetchone()[0],
                        "wal",
                    )
                    connection.execute("PRAGMA wal_autocheckpoint = 0")
                    connection.execute(
                        "UPDATE registry_metadata SET value=? WHERE key='schema_version'",
                        (wal_version,),
                    )
                    connection.execute(
                        "UPDATE active_wal_marker SET value='active-wal' WHERE id=1"
                    )
                    connection.commit()
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM registry_metadata WHERE key='schema_version'"
                        ).fetchone()[0],
                        wal_version,
                    )

                    immutable_uri = (
                        f"{database.resolve().as_uri()}?mode=ro&immutable=1"
                    )
                    immutable = sqlite3.connect(immutable_uri, uri=True)
                    try:
                        self.assertEqual(
                            immutable.execute(
                                "SELECT value FROM registry_metadata "
                                "WHERE key='schema_version'"
                            ).fetchone()[0],
                            "1",
                        )
                    finally:
                        immutable.close()

                    source_paths = tuple(
                        Path(f"{database}{suffix}") for suffix in ("", "-wal", "-shm")
                    )
                    self.assertTrue(all(path.exists() for path in source_paths))
                    before = {path.name: path.read_bytes() for path in source_paths}

                    with self.assertRaisesRegex(RegistryConflict, error):
                        SQLiteRegistry(database).initialize()

                    after = {path.name: path.read_bytes() for path in source_paths}
                    self.assertEqual(after, before)
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM registry_metadata WHERE key='schema_version'"
                        ).fetchone()[0],
                        wal_version,
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM active_wal_marker WHERE id=1"
                        ).fetchone()[0],
                        "active-wal",
                    )
                finally:
                    connection.close()

    def test_control_apis_fail_closed_for_newer_or_malformed_schema(self) -> None:
        for value, code in (
            ("2", "UNSUPPORTED_CONTROL_SCHEMA_VERSION"),
            ("future", "MALFORMED_CONTROL_SCHEMA_VERSION"),
        ):
            with self.subTest(value=value):
                with sqlite3.connect(self.database) as connection:
                    connection.execute(
                        "UPDATE registry_metadata SET value=? WHERE key='control_schema_version'",
                        (value,),
                    )
                with self.assertRaisesRegex(RegistryConflict, code):
                    self.registry.dispatch_control()
                with self.assertRaisesRegex(RegistryConflict, code):
                    self.registry.initialize()
                with sqlite3.connect(self.database) as connection:
                    stored = connection.execute(
                        "SELECT value FROM registry_metadata WHERE key='control_schema_version'"
                    ).fetchone()[0]
                    mode = connection.execute(
                        "SELECT dispatch_mode FROM factory_control WHERE singleton=1"
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE registry_metadata SET value='1' WHERE key='control_schema_version'"
                    )
                self.assertEqual(stored, value)
                self.assertEqual(mode, "PAUSED")

        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "DELETE FROM registry_metadata WHERE key='control_schema_version'"
            )
        with self.assertRaisesRegex(RegistryConflict, "CONTROL_SCHEMA_METADATA_MISSING"):
            self.registry.dispatch_control()
        with self.assertRaisesRegex(RegistryConflict, "CONTROL_SCHEMA_METADATA_MISSING"):
            self.registry.initialize()
        with sqlite3.connect(self.database) as connection:
            stored = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='control_schema_version'"
            ).fetchone()
            mode = connection.execute(
                "SELECT dispatch_mode FROM factory_control WHERE singleton=1"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO registry_metadata(key, value) VALUES ('control_schema_version', '1')"
            )
        self.assertIsNone(stored)
        self.assertEqual(mode, "PAUSED")

    def test_enforces_three_active_parent_packages_transactionally(self) -> None:
        self.feature()
        for number in range(1, 5):
            self.worker(f"worker-{number}", "registry")
            self.package(f"TASK-{number}")
        leases = []
        for number in range(1, 4):
            leases.append(
                self.registry.acquire_lease(
                    f"TASK-{number}", f"worker-{number}",
                    acquired_at="2026-09-24T10:00:00+00:00",
                    expires_at="2026-09-24T10:05:00+00:00",
                )
            )
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_PARENT_LIMIT"):
            self.registry.acquire_lease(
                "TASK-4", "worker-4",
                acquired_at="2026-09-24T10:01:00+00:00",
                expires_at="2026-09-24T10:06:00+00:00",
            )
        self.registry.release_lease(
            leases[0].id,
            released_at="2026-09-24T10:02:00+00:00",
            reason="READY_FOR_REVIEW",
            next_status=TaskStatus.VERIFY_REVIEW,
        )
        replacement = self.registry.acquire_lease(
            "TASK-4", "worker-4",
            acquired_at="2026-09-24T10:03:00+00:00",
            expires_at="2026-09-24T10:08:00+00:00",
        )
        self.assertEqual(replacement.package_id, "TASK-4")

    def test_concurrent_claim_allows_only_one_worker_to_own_package(self) -> None:
        self.feature()
        self.worker("worker-1", "registry")
        self.worker("worker-2", "registry")
        self.package("TASK")

        def claim(worker_id: str) -> str:
            try:
                lease = self.registry.acquire_lease(
                    "TASK", worker_id,
                    acquired_at="2026-09-24T10:00:00+00:00",
                    expires_at="2026-09-24T10:05:00+00:00",
                )
                return lease.worker_id
            except RegistryConflict as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(claim, ("worker-1", "worker-2")))
        self.assertEqual(sum(result.startswith("worker-") for result in results), 1)
        self.assertEqual(sum(result in {"PACKAGE_NOT_READY", "LEASE_CONFLICT"} for result in results), 1)

    def test_review_claim_excludes_the_actual_implementation_worker(self) -> None:
        self.feature()
        self.registry.register_worker(Worker(
            "hybrid", "Hybrid", ("registry", "independent-review"),
            (Lane.PLATFORM, Lane.ASSURANCE), usage_state="NORMAL",
        ))
        self.registry.register_worker(Worker(
            "reviewer", "Reviewer", ("independent-review",),
            (Lane.ASSURANCE,), usage_state="NORMAL",
        ))
        self.package("IMPLEMENTATION")
        self.registry.register_work_package(WorkPackage(
            "REVIEW", "FEATURE-1", "Review", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 99, ("independent approval",),
            status=TaskStatus.READY, kind=PackageKind.REVIEW,
            dependency_ids=("IMPLEMENTATION",),
        ))
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="review fixture",
        )
        self.registry.acquire_lease(
            "IMPLEMENTATION", "hybrid", acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:20:00Z",
        )
        self.registry.begin_attempt_runtime(
            "implementation-attempt", package_id="IMPLEMENTATION",
            worker_id="hybrid", runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "implementation-attempt", ended_at="2026-09-25T10:03:00Z",
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="ready for review",
        )
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"):
            self.registry.acquire_lease(
                "REVIEW", "hybrid", acquired_at="2026-09-25T10:04:00Z",
                expires_at="2026-09-25T10:20:00Z",
            )
        lease = self.registry.acquire_lease(
            "REVIEW", "reviewer", acquired_at="2026-09-25T10:04:00Z",
            expires_at="2026-09-25T10:20:00Z",
        )
        self.assertEqual(lease.worker_id, "reviewer")

    def test_active_package_transition_requires_atomic_lease_release(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00+00:00",
            expires_at="2026-09-24T10:05:00+00:00",
        )
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_TRANSITION_REQUIRES_LEASE_RELEASE"):
            self.registry.transition_work_package(
                "TASK", expected_status=TaskStatus.ACTIVE,
                new_status=TaskStatus.VERIFY_REVIEW,
                changed_at="2026-09-24T10:01:00+00:00",
            )

    def test_active_status_can_only_be_entered_by_acquiring_a_lease(self) -> None:
        self.feature()
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_REQUIRES_LEASE"):
            self.registry.transition_work_package(
                "TASK", expected_status=TaskStatus.READY,
                new_status=TaskStatus.ACTIVE,
                changed_at="2026-09-24T10:01:00Z",
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute("SELECT status FROM work_packages WHERE id='TASK'").fetchone()[0],
                "READY",
            )
            self.assertEqual(connection.execute("SELECT count(*) FROM leases").fetchone()[0], 0)

    def test_work_package_cannot_be_registered_as_active(self) -> None:
        self.feature()
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_REQUIRES_LEASE"):
            self.registry.register_work_package(
                WorkPackage(
                    "ACTIVE-TASK", "FEATURE-1", "Active", "ORCHESTRATION",
                    Lane.PLATFORM, ("registry",), 1, ("complete",),
                    status=TaskStatus.ACTIVE,
                )
            )

    def test_explicit_expiry_reconciles_lease_package_worker_failure_and_event(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        lease = self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:05:00Z",
        )
        self.assertEqual(
            self.registry.expire_leases(observed_at="2026-09-24T10:06:00Z"), 1
        )
        with sqlite3.connect(self.database) as connection:
            released = connection.execute(
                "SELECT released_at, release_reason FROM leases WHERE id=?", (lease.id,)
            ).fetchone()
            package = connection.execute(
                "SELECT status, failure_code FROM work_packages WHERE id='TASK'"
            ).fetchone()
            worker = connection.execute(
                "SELECT availability FROM workers WHERE id='worker'"
            ).fetchone()[0]
            event_count = connection.execute(
                "SELECT count(*) FROM task_events WHERE event_type='LEASE_EXPIRED'"
            ).fetchone()[0]
            failure_count = connection.execute(
                "SELECT count(*) FROM failure_observations WHERE code='HEARTBEAT_MISSED'"
            ).fetchone()[0]
        self.assertEqual(released[1], "LEASE_EXPIRED")
        self.assertEqual(package, ("BLOCKED", "HEARTBEAT_MISSED"))
        self.assertEqual(worker, "IDLE")
        self.assertEqual(event_count, 1)
        self.assertEqual(failure_count, 1)

    def test_release_after_expiry_reconciles_expiry_instead_of_completing(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        lease = self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:05:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "LEASE_NOT_ACTIVE"):
            self.registry.release_lease(
                lease.id,
                released_at="2026-09-24T10:06:00Z",
                reason="COMPLETED",
                next_status=TaskStatus.DONE,
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute("SELECT status FROM work_packages WHERE id='TASK'").fetchone()[0],
                "BLOCKED",
            )

    def test_lease_lifecycle_cannot_move_backward_in_time(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        lease = self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:10:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_CHRONOLOGY"):
            self.registry.renew_lease(
                lease.id,
                now="2026-09-24T09:59:00Z",
                expires_at="2026-09-24T10:11:00Z",
            )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_CHRONOLOGY"):
            self.registry.release_lease(
                lease.id,
                released_at="2026-09-24T09:59:00Z",
                reason="COMPLETED",
                next_status=TaskStatus.DONE,
            )
        self.registry.renew_lease(
            lease.id,
            now="2026-09-24T10:02:00Z",
            expires_at="2026-09-24T10:12:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_CHRONOLOGY"):
            self.registry.renew_lease(
                lease.id,
                now="2026-09-24T10:01:00Z",
                expires_at="2026-09-24T10:13:00Z",
            )

    def test_actively_leased_worker_cannot_be_reconfigured(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:05:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "WORKER_HAS_ACTIVE_LEASE"):
            self.registry.register_worker(
                Worker(
                    "worker", "Changed", (), (), role="ORCHESTRA",
                    availability="IDLE", usage_state="GREEN",
                )
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT role, availability FROM workers WHERE id='worker'"
                ).fetchone(),
                ("WORKER", "BUSY"),
            )

    def test_lease_timestamps_are_normalized_before_duration_check(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_EXPIRY"):
            self.registry.acquire_lease(
                "TASK", "worker",
                acquired_at="2026-09-24T10:00:00.900000+00:00",
                expires_at="2026-09-24T10:00:00Z",
            )

    def test_orchestra_role_cannot_claim_implementation_work(self) -> None:
        self.feature()
        self.registry.register_worker(
            Worker(
                "orchestra", "Orchestra", ("registry",), (Lane.PLATFORM,),
                role="ORCHESTRA", usage_state="GREEN",
            )
        )
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "ORCHESTRA_CANNOT_CLAIM"):
            self.registry.acquire_lease(
                "TASK", "orchestra",
                acquired_at="2026-09-24T10:00:00Z",
                expires_at="2026-09-24T10:05:00Z",
            )

    def test_rejects_capability_mismatch_and_incomplete_dependency(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("DEPENDENCY")
        self.package("BLOCKED", dependencies=("DEPENDENCY",))
        self.package("MISMATCH", capabilities=("database-migration",))
        with self.assertRaisesRegex(RegistryConflict, "DEPENDENCY_BLOCKED"):
            self.registry.acquire_lease(
                "BLOCKED", "worker",
                acquired_at="2026-09-24T10:00:00+00:00",
                expires_at="2026-09-24T10:05:00+00:00",
            )
        with self.assertRaisesRegex(RegistryConflict, "CAPABILITY_MISMATCH"):
            self.registry.acquire_lease(
                "MISMATCH", "worker",
                acquired_at="2026-09-24T10:00:00+00:00",
                expires_at="2026-09-24T10:05:00+00:00",
            )

    def test_events_are_append_only(self) -> None:
        event_id = self.registry.append_event(
            "OBSERVED", recorded_at="2026-09-24T10:00:00+00:00", detail={"safe": True}
        )
        with sqlite3.connect(self.database) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "TASK_EVENTS_APPEND_ONLY"):
                connection.execute(
                    "UPDATE task_events SET event_type='CHANGED' WHERE id=?", (event_id,)
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "TASK_EVENTS_APPEND_ONLY"):
                connection.execute("DELETE FROM task_events WHERE id=?", (event_id,))

    def test_preservation_import_is_read_only_and_idempotent(self) -> None:
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {"codex-a": {"time": 1000, "status": "idle"}}},
            "open_task_mapping": [
                {
                    "issue": 146,
                    "task": "TASK-140",
                    "title": "Usage feed",
                    "status": "VERIFY / REVIEW",
                    "worker": "Agent B",
                    "branch": "runner/task-140",
                    "pr": 148,
                }
            ],
            "worktrees": [
                {"worktree": "/preserved/worktree", "branch": "refs/heads/preserved", "dirty": True}
            ],
            "unmerged_local_branches": ["runner/task-140 abc123"],
        }
        source = self.root / "snapshot.json"
        source.write_text(json.dumps(snapshot, sort_keys=True))
        before = source.read_bytes()
        digest = hashlib.sha256(before).hexdigest()
        self.assertTrue(import_snapshot(source, self.database))
        self.assertFalse(import_snapshot(source, self.database))
        self.assertEqual(source.read_bytes(), before)
        with sqlite3.connect(self.database) as connection:
            imported_digest = connection.execute(
                "SELECT source_sha256 FROM preservation_imports"
            ).fetchone()[0]
            package = connection.execute(
                "SELECT status, lane, source_system, source_ref FROM work_packages WHERE id='TASK-140'"
            ).fetchone()
            dirty = connection.execute(
                "SELECT dirty FROM preserved_artifacts WHERE kind='WORKTREE'"
            ).fetchone()[0]
        self.assertEqual(imported_digest, digest)
        self.assertEqual(package, ("VERIFY_REVIEW", None, "github_issue", "146"))
        self.assertEqual(dirty, 1)

    def test_preservation_import_rejects_database_inside_preserved_worktree(self) -> None:
        preserved = self.root / "preserved-worktree"
        preserved.mkdir()
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {}},
            "open_task_mapping": [],
            "worktrees": [{"worktree": str(preserved), "dirty": True}],
            "unmerged_local_branches": [],
        }
        source = self.root / "snapshot-safe.json"
        source.write_text(json.dumps(snapshot))
        unsafe_database = preserved / "registry.sqlite3"
        with self.assertRaisesRegex(RegistryConflict, "UNSAFE_IMPORT_TARGET"):
            import_snapshot(source, unsafe_database)
        self.assertFalse(unsafe_database.exists())

    def test_preservation_import_rejects_database_inside_canonical_repository(self) -> None:
        canonical = self.root / "canonical-repository"
        canonical.mkdir()
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {"origin_main": "abc", "path": str(canonical)},
            "services": {"heartbeats": {}},
            "open_task_mapping": [],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        source = self.root / "snapshot-canonical.json"
        source.write_text(json.dumps(snapshot))
        unsafe_database = canonical / "registry.sqlite3"
        with self.assertRaisesRegex(RegistryConflict, "UNSAFE_IMPORT_TARGET"):
            import_snapshot(source, unsafe_database)
        self.assertFalse(unsafe_database.exists())

    def test_preservation_import_rejects_duplicate_normalized_tasks(self) -> None:
        duplicate = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {}},
            "open_task_mapping": [
                {"issue": 1, "task": "TASK-1", "title": "First", "status": "ON DECK"},
                {"issue": 2, "task": "TASK-1", "title": "Second", "status": "ON DECK"},
            ],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        with self.assertRaisesRegex(RegistryConflict, "DUPLICATE_PRESERVATION_TASK"):
            self.registry.import_preservation_snapshot(
                duplicate,
                source_uri="snapshot.json",
                source_sha256="a" * 64,
                imported_at="2026-09-24T10:00:00Z",
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM preservation_imports").fetchone()[0], 0)

    def test_preservation_import_rejects_existing_legacy_worker_collision(self) -> None:
        self.registry.register_worker(
            Worker(
                "legacy-worker:codex-a", "Existing", ("registry",),
                (Lane.PLATFORM,), usage_state="GREEN",
            )
        )
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {"codex-a": {"time": 1000}}},
            "open_task_mapping": [],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        with self.assertRaisesRegex(RegistryConflict, "PRESERVATION_COLLISION"):
            self.registry.import_preservation_snapshot(
                snapshot,
                source_uri="snapshot.json",
                source_sha256="b" * 64,
                imported_at="2026-09-24T10:00:00Z",
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM preservation_imports").fetchone()[0], 0)

    def test_preservation_import_rejects_malformed_artifacts_and_heartbeats(self) -> None:
        base = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {}},
            "open_task_mapping": [],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        malformed = [
            ({**base, "unmerged_local_branches": [None]}, "INVALID_PRESERVATION_BRANCH"),
            ({**base, "worktrees": [{"worktree": "relative/path"}]}, "INVALID_PRESERVATION_WORKTREE"),
            ({**base, "services": {"heartbeats": {"worker": "bad"}}}, "INVALID_PRESERVATION_HEARTBEAT"),
        ]
        for index, (snapshot, code) in enumerate(malformed):
            with self.subTest(code=code):
                with self.assertRaisesRegex(RegistryConflict, code):
                    self.registry.import_preservation_snapshot(
                        snapshot,
                        source_uri=f"snapshot-{index}.json",
                        source_sha256=str(index) * 64,
                        imported_at="2026-09-24T10:00:00Z",
                    )

    def test_registered_timestamps_are_normalized_to_utc(self) -> None:
        self.feature()
        self.registry.register_worker(
            Worker(
                "worker", "Worker", ("registry",), (Lane.PLATFORM,),
                last_heartbeat_at="2026-09-24T11:00:00+01:00", usage_state="GREEN",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK", "FEATURE-1", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 1, ("complete",), status=TaskStatus.READY,
                started_at="2026-09-24T11:00:00+01:00",
                last_heartbeat_at="2026-09-24T11:01:00+01:00",
            )
        )
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-24T10:02:00Z")
        self.assertEqual(snapshot.workers[0]["last_heartbeat_at"], "2026-09-24T10:00:00.000000Z")
        self.assertEqual(snapshot.work_packages[0]["started_at"], "2026-09-24T10:00:00.000000Z")
        self.assertEqual(
            snapshot.work_packages[0]["last_heartbeat_at"], "2026-09-24T10:01:00.000000Z"
        )

    def test_dispatch_snapshot_exposes_backend_neutral_scheduler_inputs(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-24T10:00:00Z")
        self.assertGreaterEqual(snapshot.revision, 3)
        self.assertEqual(snapshot.active_parent_limit, 3)
        self.assertEqual(snapshot.orchestra_reserve_percent, 20)
        self.assertEqual(snapshot.work_packages[0]["ready_at"] is not None, True)
        self.assertEqual(snapshot.work_packages[0]["capacity_size"], "SUBSTANTIAL")
        self.assertEqual(snapshot.work_packages[0]["capacity_risk"], "UNCERTAIN")
        self.assertEqual(snapshot.workers[0]["availability"], "IDLE")
        self.assertEqual(snapshot.workers[0]["capabilities"], ["registry"])
        self.assertEqual(snapshot.dependencies, ())
        self.assertEqual(snapshot.active_leases, ())

    def test_package_capacity_classification_is_registry_data(self) -> None:
        self.feature()
        self.registry.register_work_package(
            WorkPackage(
                "TASK", "FEATURE-1", "Task", "ASSURANCE", Lane.ASSURANCE,
                ("review",), 1, ("complete",), status=TaskStatus.READY,
                capacity_size=PackageCapacitySize.VERY_SMALL,
                capacity_risk=PackageCapacityRisk.BOUNDED,
            )
        )
        package = self.registry.dispatch_snapshot(
            observed_at="2026-09-24T10:00:00Z"
        ).work_packages[0]
        self.assertEqual(package["capacity_size"], "VERY_SMALL")
        self.assertEqual(package["capacity_risk"], "BOUNDED")

    def test_provider_metadata_does_not_grant_lane_or_capability(self) -> None:
        self.feature()
        self.registry.register_worker(
            Worker(
                "diagnostic-worker", "Diagnostic worker", (), (),
                provider_diagnostics={"provider": "preferred", "model": "expensive"},
                usage_state="GREEN",
            )
        )
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "LANE_NOT_APPROVED"):
            self.registry.acquire_lease(
                "TASK", "diagnostic-worker",
                acquired_at="2026-09-24T10:00:00+00:00",
                expires_at="2026-09-24T10:05:00+00:00",
            )

    def test_dispatch_control_defaults_paused_and_requires_revision_cas(self) -> None:
        control = self.registry.dispatch_control()
        self.assertEqual(control["dispatch_mode"], "PAUSED")
        self.assertTrue(control["kill_switch_engaged"])
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            self.registry.require_live_dispatch()
        with self.assertRaisesRegex(
            RegistryConflict, "DISPATCH_CONTROL_COMPARE_AND_SWAP_FAILED"
        ):
            self.registry.set_dispatch_control(
                expected_revision=control["revision"] + 1,
                expected_mode="PAUSED",
                new_mode="LIVE",
                kill_switch_engaged=False,
                changed_at="2026-09-25T10:00:00Z",
                reason="stale caller",
            )
        revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.assertEqual(self.registry.require_live_dispatch(), revision)

    def test_dispatch_control_retry_replays_one_semantic_mutation(self) -> None:
        control = self.registry.dispatch_control()
        arguments = {
            "expected_revision": control["revision"],
            "expected_mode": "PAUSED",
            "new_mode": "LIVE",
            "kill_switch_engaged": False,
            "reason": "bounded canary",
            "operation_id": "operation-enable-live",
        }
        revision = self.registry.set_dispatch_control(
            **arguments, changed_at="2026-09-25T10:00:00Z"
        )
        replayed = self.registry.set_dispatch_control(
            **arguments, changed_at="2026-09-25T10:00:05Z"
        )
        self.assertEqual(replayed, revision)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM task_events "
                    "WHERE event_type='DISPATCH_CONTROL_CHANGED'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM control_operation_receipts"
                ).fetchone()[0],
                1,
            )
        with self.assertRaisesRegex(RegistryConflict, "OPERATION_ID_REUSED"):
            self.registry.set_dispatch_control(
                **{**arguments, "reason": "different request"},
                changed_at="2026-09-25T10:00:06Z",
            )

    def test_rejected_named_operation_is_audited_and_replayed(self) -> None:
        control = self.registry.dispatch_control()
        arguments = {
            "expected_revision": control["revision"] + 1,
            "expected_mode": "PAUSED",
            "new_mode": "LIVE",
            "kill_switch_engaged": False,
            "reason": "stale caller",
            "operation_id": "operation-rejected-live",
        }
        for changed_at in (
            "2026-09-25T10:00:00Z",
            "2026-09-25T10:00:05Z",
        ):
            with self.assertRaisesRegex(
                RegistryConflict, "DISPATCH_CONTROL_COMPARE_AND_SWAP_FAILED"
            ):
                self.registry.set_dispatch_control(
                    **arguments, changed_at=changed_at
                )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM control_operation_receipts "
                    "WHERE operation_id='operation-rejected-live'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM task_events "
                    "WHERE event_type='CONTROL_OPERATION_REJECTED'"
                ).fetchone()[0],
                1,
            )

    def test_claim_and_attempt_retries_do_not_duplicate_ownership(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="bounded canary",
        )
        claim = {
            "package_id": "TASK",
            "worker_id": "worker",
            "expected_dispatch_revision": live_revision,
            "operation_id": "operation-claim-task",
        }
        lease = self.registry.acquire_lease(
            **claim,
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:11:00Z",
        )
        replayed_lease = self.registry.acquire_lease(
            **claim,
            acquired_at="2026-09-25T10:01:05Z",
            expires_at="2026-09-25T10:11:05Z",
        )
        self.assertEqual(replayed_lease, lease)

        attempt_revision = self.registry.dispatch_control()["revision"]
        attempt = {
            "attempt_id": "attempt-1",
            "package_id": "TASK",
            "worker_id": "worker",
            "runner_pid": 123,
            "expected_revision": attempt_revision,
            "operation_id": "operation-attempt-start",
        }
        self.registry.begin_attempt_runtime(
            **attempt, started_at="2026-09-25T10:02:00Z"
        )
        self.registry.begin_attempt_runtime(
            **attempt, started_at="2026-09-25T10:02:05Z"
        )
        finish = {
            "attempt_id": "attempt-1",
            "outcome": "SUCCEEDED",
            "next_status": TaskStatus.VERIFY_REVIEW,
            "reason": "ready for review",
            "operation_id": "operation-attempt-finish",
        }
        self.registry.finish_attempt_runtime(
            **finish, ended_at="2026-09-25T10:03:00Z"
        )
        self.registry.finish_attempt_runtime(
            **finish, ended_at="2026-09-25T10:03:05Z"
        )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM leases").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM attempts").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM task_events WHERE event_type='LEASE_ACQUIRED'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM task_events "
                    "WHERE event_type='ATTEMPT_RUNTIME_RESERVED'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM task_events WHERE event_type='ATTEMPT_FINISHED'"
                ).fetchone()[0],
                1,
            )

    def test_delayed_claim_replay_does_not_expire_original_lease(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="bounded canary",
        )
        arguments = {
            "package_id": "TASK",
            "worker_id": "worker",
            "expected_dispatch_revision": live_revision,
            "operation_id": "operation-delayed-claim",
        }
        lease = self.registry.acquire_lease(
            **arguments,
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:05:00Z",
        )
        revision = self.registry.dispatch_control()["revision"]
        replayed = self.registry.acquire_lease(
            **arguments,
            acquired_at="2026-09-25T10:06:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        self.assertEqual(replayed, lease)
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)
        with sqlite3.connect(self.database) as connection:
            self.assertIsNone(connection.execute(
                "SELECT released_at FROM leases WHERE id=?", (lease.id,)
            ).fetchone()[0])
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM task_events WHERE event_type='LEASE_EXPIRED'"
            ).fetchone()[0], 0)

    def test_mismatched_delayed_claim_replay_cannot_expire_lease(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:05:00Z",
            expected_dispatch_revision=live_revision,
            operation_id="operation-mismatched-claim",
        )
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "OPERATION_ID_REUSED"):
            self.registry.acquire_lease(
                "TASK", "worker",
                acquired_at="2026-09-25T10:06:00Z",
                expires_at="2026-09-25T10:11:00Z",
                expected_dispatch_revision=live_revision,
                operation_id="operation-mismatched-claim",
            )
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)
        with sqlite3.connect(self.database) as connection:
            self.assertIsNone(connection.execute(
                "SELECT released_at FROM leases WHERE id=?", (lease.id,)
            ).fetchone()[0])
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM task_events WHERE event_type='LEASE_EXPIRED'"
            ).fetchone()[0], 0)

    def test_delayed_release_replays_do_not_expire_unrelated_lease(self) -> None:
        self.feature()
        self.worker("worker-a", "registry")
        self.worker("worker-b", "registry")
        self.package("TASK-A")
        self.package("TASK-B")
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="bounded canary",
        )
        lease_a = self.registry.acquire_lease(
            "TASK-A", "worker-a",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:20:00Z",
            expected_dispatch_revision=live_revision,
            operation_id="operation-claim-a",
        )
        lease_b = self.registry.acquire_lease(
            "TASK-B", "worker-b",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:05:00Z",
            operation_id="operation-claim-b",
        )
        release = {
            "lease_id": lease_a.id,
            "reason": "implementation stopped",
            "next_status": TaskStatus.READY,
            "operation_id": "operation-release-a",
        }
        self.registry.release_lease(
            **release, released_at="2026-09-25T10:02:00Z"
        )
        revision = self.registry.dispatch_control()["revision"]
        self.registry.release_lease(
            **release, released_at="2026-09-25T10:06:00Z"
        )
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)
        with self.assertRaisesRegex(RegistryConflict, "OPERATION_ID_REUSED"):
            self.registry.release_lease(
                lease_a.id,
                released_at="2026-09-25T10:06:00Z",
                reason="different reason",
                next_status=TaskStatus.READY,
                operation_id="operation-release-a",
            )
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)
        with sqlite3.connect(self.database) as connection:
            self.assertIsNone(connection.execute(
                "SELECT released_at FROM leases WHERE id=?", (lease_b.id,)
            ).fetchone()[0])
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM task_events WHERE event_type='LEASE_EXPIRED'"
            ).fetchone()[0], 0)

    def test_direct_transition_policy_rejects_terminal_reopening(self) -> None:
        self.feature()
        self.package("TASK")
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE work_packages SET status='DONE' WHERE id='TASK'")
        with self.assertRaisesRegex(RegistryConflict, "INVALID_PACKAGE_TRANSITION"):
            self.registry.transition_work_package(
                "TASK", expected_status=TaskStatus.DONE,
                new_status=TaskStatus.READY,
                changed_at="2026-09-25T10:00:00Z",
            )

    def test_operation_receipts_are_append_only(self) -> None:
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="bounded canary",
            operation_id="operation-append-only",
        )
        with sqlite3.connect(self.database) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "APPEND_ONLY"):
                connection.execute(
                    "UPDATE control_operation_receipts SET result_json='{}'"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "APPEND_ONLY"):
                connection.execute("DELETE FROM control_operation_receipts")

    def test_evidence_retry_is_exactly_once(self) -> None:
        self.feature()
        self.package("TASK")
        evidence = Evidence(
            "evidence-1", "TASK", "validation", None, "tests passed",
            "2026-09-25T10:00:00Z", {"suite": "registry"},
        )
        self.registry.record_evidence(evidence)
        revision = self.registry.dispatch_control()["revision"]
        self.registry.record_evidence(evidence)
        self.assertEqual(self.registry.dispatch_control()["revision"], revision)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM evidence").fetchone()[0], 1
            )
        changed = Evidence(
            "evidence-1", "TASK", "validation", None, "different result",
            "2026-09-25T10:00:00Z", {"suite": "registry"},
        )
        with self.assertRaisesRegex(RegistryConflict, "OPERATION_ID_REUSED"):
            self.registry.record_evidence(changed)

    def test_revision_pinned_lease_claim_rechecks_live_gate_atomically(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:00:01Z", reason="operator stop"
        )
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_NOT_AUTHORIZED"):
            self.registry.acquire_lease(
                "TASK", "worker",
                acquired_at="2026-09-25T10:00:02Z",
                expires_at="2026-09-25T10:10:02Z",
                expected_dispatch_revision=live_revision,
            )
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-25T10:00:02Z")
        self.assertEqual(snapshot.active_leases, ())
        self.assertEqual(snapshot.work_packages[0]["status"], "READY")

    def test_dispatch_snapshot_projects_worker_capacity_mode_for_live_gate(self) -> None:
        self.registry.register_worker(
            Worker(
                "claude", "Claude", ("registry",), (Lane.ASSURANCE,),
                provider_diagnostics={
                    "capacity_mode": "provider_signal",
                    "capacity_scopes": ["provider_signal"],
                },
                usage_state="NORMAL",
            )
        )
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-25T10:00:00Z")
        worker = snapshot.workers[0]
        self.assertEqual(worker["capacity_mode"], "provider_signal")
        self.assertEqual(worker["capacity_scopes"], ["provider_signal"])

    def test_dispatch_control_enforces_complete_phase_transition_table(self) -> None:
        legal = {
            ("PAUSED", "LIVE"),
            ("PAUSED", "STOPPING"),
            ("LIVE", "STOPPING"),
            ("STOPPING", "PAUSED"),
            ("STOPPING", "RECOVERY_REQUIRED"),
            ("RECOVERY_REQUIRED", "PAUSED"),
            ("RECOVERY_REQUIRED", "STOPPING"),
        }
        modes = ("PAUSED", "LIVE", "STOPPING", "RECOVERY_REQUIRED")
        for source in modes:
            for target in modes:
                with self.subTest(source=source, target=target):
                    database = self.root / f"transition-{source}-{target}.sqlite3"
                    registry = SQLiteRegistry(database)
                    registry.initialize()
                    with sqlite3.connect(database) as connection:
                        connection.execute(
                            "UPDATE factory_control SET dispatch_mode=?, "
                            "kill_switch_engaged=? WHERE singleton=1",
                            (source, int(source != "LIVE")),
                        )
                    before = registry.dispatch_control()
                    arguments = {
                        "expected_revision": before["revision"],
                        "expected_mode": source,
                        "new_mode": target,
                        "kill_switch_engaged": target != "LIVE",
                        "changed_at": "2026-09-25T10:00:00Z",
                        "reason": "transition-table test",
                    }
                    if (source, target) in legal:
                        registry.set_dispatch_control(**arguments)
                        self.assertEqual(
                            registry.dispatch_control()["dispatch_mode"], target
                        )
                    else:
                        with self.assertRaisesRegex(
                            RegistryConflict, "INVALID_DISPATCH_TRANSITION"
                        ):
                            registry.set_dispatch_control(**arguments)
                        after = registry.dispatch_control()
                        self.assertEqual(after["dispatch_mode"], source)
                        self.assertEqual(after["revision"], before["revision"])

    def test_runtime_provenance_is_atomic_and_finishes_all_ownership(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        revision = self.registry.dispatch_control()["revision"]
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=revision,
        )
        self.registry.record_attempt_process(
            "attempt-1",
            agent_pid=101,
            agent_pgid=101,
            recorded_at="2026-09-25T10:02:01Z",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:02Z", reason="operator stop"
        )
        stopped = self.registry.dispatch_control()
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_OWNERSHIP_PRESENT"):
            self.registry.set_dispatch_control(
                expected_revision=stopped["revision"],
                expected_mode="STOPPING",
                new_mode="PAUSED",
                kill_switch_engaged=True,
                changed_at="2026-09-25T10:02:03Z",
                reason="unsafe early pause",
            )
        self.registry.finish_attempt_runtime(
            "attempt-1",
            ended_at="2026-09-25T10:03:00Z",
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="ready for review",
        )
        with sqlite3.connect(self.database) as connection:
            runtime = connection.execute(
                """SELECT runner_pid, agent_pid, agent_pgid, released_at
                   FROM attempt_runtime_ownership WHERE attempt_id='attempt-1'"""
            ).fetchone()
            attempt = connection.execute(
                "SELECT outcome, ended_at FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            package = connection.execute(
                "SELECT status FROM work_packages WHERE id='TASK'"
            ).fetchone()[0]
            released = connection.execute(
                "SELECT release_reason FROM leases WHERE id=?", (lease.id,)
            ).fetchone()[0]
        self.assertEqual(runtime[:3], (100, 101, 101))
        self.assertIsNotNone(runtime[3])
        self.assertEqual(attempt[0], "SUCCEEDED")
        self.assertIsNotNone(attempt[1])
        self.assertEqual(package, "VERIFY_REVIEW")
        self.assertEqual(released, "ready for review")
        self.assertEqual(self.registry.runtime_orphans(), ())
        stopped = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=stopped["revision"],
            expected_mode="STOPPING",
            new_mode="PAUSED",
            kill_switch_engaged=True,
            changed_at="2026-09-25T10:04:00Z",
            reason="ownership drained",
        )

    def test_process_binding_rechecks_kill_switch_and_orphans_stay_visible(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:01Z", reason="operator stop"
        )
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            self.registry.record_attempt_process(
                "attempt-1",
                agent_pid=101,
                agent_pgid=101,
                recorded_at="2026-09-25T10:02:02Z",
            )
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE attempts SET ended_at=?, outcome='FAILED' WHERE id='attempt-1'",
                ("2026-09-25T10:03:00.000000Z",),
            )
        orphans = self.registry.runtime_orphans()
        self.assertEqual([item["attempt_id"] for item in orphans], ["attempt-1"])
        self.assertIsNone(orphans[0]["released_at"])

    def test_stopping_cannot_return_live_with_unreleased_runtime_orphan(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:01Z", reason="operator stop"
        )
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE attempts SET ended_at=?, outcome='FAILED' WHERE id='attempt-1'",
                ("2026-09-25T10:03:00.000000Z",),
            )
            connection.execute(
                "UPDATE leases SET released_at=?, release_reason='incomplete recovery' WHERE id=?",
                ("2026-09-25T10:03:00.000000Z", lease.id),
            )
            connection.execute(
                "UPDATE work_packages SET status='BLOCKED' WHERE id='TASK'"
            )
            connection.execute(
                "UPDATE workers SET availability='IDLE' WHERE id='worker'"
            )
        stopped = self.registry.dispatch_control()
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_OWNERSHIP_PRESENT"):
            self.registry.set_dispatch_control(
                expected_revision=stopped["revision"],
                expected_mode="STOPPING",
                new_mode="LIVE",
                kill_switch_engaged=False,
                changed_at="2026-09-25T10:04:00Z",
                reason="unsafe restart",
            )
        unchanged = self.registry.dispatch_control()
        self.assertEqual(unchanged["dispatch_mode"], "STOPPING")
        self.assertTrue(unchanged["kill_switch_engaged"])
        self.assertEqual(unchanged["revision"], stopped["revision"])

    def test_expired_lease_and_disappeared_worker_surface_runtime_orphans(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.record_attempt_process(
            "attempt-1",
            agent_pid=101,
            agent_pgid=101,
            recorded_at="2026-09-25T10:02:01Z",
        )
        self.assertEqual(
            self.registry.runtime_orphans(observed_at="2026-09-25T10:05:00Z"), ()
        )
        expired = self.registry.runtime_orphans(observed_at="2026-09-25T10:11:00Z")
        self.assertEqual([item["attempt_id"] for item in expired], ["attempt-1"])
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE workers SET availability='OFFLINE' WHERE id='worker'"
            )
        disappeared = self.registry.runtime_orphans(
            observed_at="2026-09-25T10:05:00Z"
        )
        self.assertEqual(disappeared[0]["worker_availability"], "OFFLINE")


if __name__ == "__main__":
    unittest.main()
