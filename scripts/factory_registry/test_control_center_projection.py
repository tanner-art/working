from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.factory_registry import (
    Evidence,
    Feature,
    Lane,
    PackageKind,
    ReviewOutcome,
    ReviewOutcomeState,
    RegistryConflict,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
    build_control_center_projection,
    serialize_control_center_projection,
    validate_control_center_projection,
)
from scripts.factory_registry.control_center_projection import ControlCenterProjectionError
from scripts.factory_registry.control_center_server import (
    SIGNATURE_HEADER,
    create_projection_handler,
    serve_local_projection,
)


NOW = "2026-09-24T20:00:00Z"
TOKEN = "local-read-token"
SECRET = "projection-signing-secret-at-least-32-bytes"


class ControlCenterProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.registry.register_feature(
            Feature("FEATURE-1", "Control visibility", 100, TaskStatus.READY, "Live state")
        )
        self.registry.register_worker(
            Worker(
                "agent-b", "Agent B", ("platform",), (Lane.PLATFORM,),
                provider_diagnostics={
                    "provider": "OpenAI", "model": "Codex",
                    "service_state": "healthy", "authentication_state": "valid",
                },
                last_heartbeat_at="2026-09-24T19:59:00Z", usage_state="GREEN",
            )
        )
        self.registry.register_worker(
            Worker(
                "claude", "Claude", ("review",), (Lane.ASSURANCE,),
                provider_diagnostics={
                    "provider": "Anthropic", "model": "Claude Code",
                    "service_state": "healthy", "authentication_state": "valid",
                },
                last_heartbeat_at="2026-09-24T19:59:30Z", usage_state="GREEN",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "PACKAGE-1", "FEATURE-1", "Projection implementation", "PLATFORM",
                Lane.PLATFORM, ("platform",), 100, ("Projection is read-only",),
                status=TaskStatus.READY, branch="codex/projection",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "REVIEW-1", "FEATURE-1", "Independent review", "ASSURANCE",
                Lane.ASSURANCE, ("review",), 90, ("Review independently",),
                status=TaskStatus.READY, dependency_ids=("PACKAGE-1",),
                kind=PackageKind.REVIEW,
            )
        )
        self.registry.record_evidence(
            Evidence(
                "evidence-1", "PACKAGE-1", "runner-log", "https://example.test/check",
                "Projection contract test", "2026-09-24T19:50:00Z",
                {"attempt_id": "attempt-1"},
            )
        )
        self._insert_extended_records()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _insert_extended_records(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """INSERT INTO attempts
                   (id, package_id, worker_id, started_at, ended_at, outcome,
                    runtime_seconds, blocked_seconds, provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "attempt-1", "PACKAGE-1", "agent-b", "2026-09-24T19:40:00Z",
                    "2026-09-24T19:50:00Z", "SUCCEEDED", 600, 0,
                    json.dumps({"branch": "codex/projection", "commit_sha": "abc123"}),
                ),
            )
            connection.execute(
                """INSERT INTO attempts
                   (id, package_id, worker_id, started_at, ended_at, outcome,
                    runtime_seconds, blocked_seconds, provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "review-attempt-1", "REVIEW-1", "claude", "2026-09-24T19:51:00Z",
                    "2026-09-24T19:52:00Z", "SUCCEEDED", 60, 0, "{}",
                ),
            )
            connection.execute(
                """INSERT INTO usage_ledger VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "usage-1", "anthropic", "claude", "private-account-id", "invocation-1",
                    "session-1", "AUTONOMOUS", "REVIEW-1", "review-attempt-1",
                    "2026-09-24T19:52:00Z", "claude-test", 10, 20, 30, 40, 1000,
                    "SUCCEEDED", 0, 1, None, None, None, "{}", "CLI_JSON", "source-1",
                    "{}", "2026-09-24T19:52:00Z",
                ),
            )
            connection.execute(
                "INSERT INTO usage_ledger_sources VALUES (?, ?, ?, ?, ?, ?)",
                ("source-row-1", "usage-1", "CLI_JSON", "source-1", "2026-09-24T19:52:00Z", "{}"),
            )
            connection.execute(
                """INSERT INTO failure_observations
                   (id, package_id, worker_id, attempt_id, code, detail, observed_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "failure-1", "PACKAGE-1", "agent-b", "attempt-1", "CI_FAILURE",
                    "A validation run failed before the successful retry.",
                    "2026-09-24T19:46:00Z", "{}",
                ),
            )
            connection.execute(
                """INSERT INTO task_events
                   (id, event_type, recorded_at, package_id, worker_id, attempt_id, detail_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "event-1", "REVIEW", "2026-09-24T19:53:00Z", "REVIEW-1", "claude",
                    "review-attempt-1", json.dumps({"summary": "Independent review completed."}),
                ),
            )
            connection.execute(
                "UPDATE registry_metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
            )

    def _logical_state(self) -> dict[str, object]:
        with sqlite3.connect(self.database) as connection:
            tables = [
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ) if not row[0].startswith("sqlite_")
            ]
            return {
                table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                for table in tables
            }

    def test_projection_matches_schema_v2_and_preserves_registry_provenance(self) -> None:
        projection = build_control_center_projection(self.registry, observed_at=NOW)
        validate_control_center_projection(projection)
        self.assertEqual(projection["schemaVersion"], 2)
        self.assertEqual(projection["source"]["kind"], "registry-projection")
        self.assertEqual(projection["factory"]["health"], "constrained")
        package = projection["features"][0]["packages"][0]
        self.assertEqual(package["attempts"][0]["commitSha"], "abc123")
        self.assertEqual(package["evidence"][0]["id"], "evidence-1")
        self.assertEqual(package["evidence"][0]["kind"], "artifact")
        self.assertEqual(projection["reviews"][0]["eligibleReviewerIds"], ["claude"])
        invocation = projection["usageInvocations"][0]
        self.assertEqual(invocation["packageId"], "REVIEW-1")
        self.assertEqual(invocation["attemptId"], "review-attempt-1")
        self.assertEqual(invocation["cacheWriteTokens"], 40)
        self.assertNotIn("private-account-id", json.dumps(projection))
        self.assertEqual(projection["capacity"][-1]["source"], "factory_measured")
        self.assertIsNone(projection["capacity"][-1]["usedPercent"])
        self.assertEqual(projection["events"][0]["kind"], "REVIEW")
        self.assertEqual(projection["failures"][0]["code"], "CI_FAILURE")

    def test_explicit_review_outcome_survives_completed_review_with_typed_evidence(self) -> None:
        self.registry.record_evidence(Evidence(
            "review-approval", "REVIEW-1", "review", "https://example.test/review",
            "Independent approval record", "2026-09-24T19:54:00Z",
            {"attempt_id": "review-attempt-1"},
        ))
        self.registry.record_review_outcome(ReviewOutcome(
            id="outcome-1",
            review_package_id="REVIEW-1",
            target_package_id="PACKAGE-1",
            implementer_worker_id="agent-b",
            reviewer_worker_id="claude",
            requested_at="2026-09-24T19:51:00Z",
            decided_at="2026-09-24T19:54:00Z",
            state=ReviewOutcomeState.APPROVED,
            findings=("All acceptance criteria passed.",),
            approval_evidence_ids=("review-approval",),
        ))

        projection = build_control_center_projection(self.registry, observed_at=NOW)
        review = next(item for item in projection["reviews"] if item["id"] == "outcome-1")
        self.assertEqual(review["packageId"], "PACKAGE-1")
        self.assertEqual(review["state"], "approved")
        self.assertEqual(review["assignedReviewerId"], "claude")
        self.assertEqual(review["approvalEvidence"][0]["id"], "review-approval")
        self.assertFalse(any(
            item["code"] == "REVIEW_STATE_UNRECORDED" and item["packageId"] == "PACKAGE-1"
            for item in projection["failures"]
        ))
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        forged_outcome = {**raw.review_outcomes[0], "implementer_worker_id": "claude"}
        from scripts.factory_registry.control_center_projection import project_control_center
        with self.assertRaisesRegex(ControlCenterProjectionError, "implementer is invalid"):
            project_control_center(replace(raw, review_outcomes=(forged_outcome,)))
        forged_evidence = tuple(
            {**item, "metadata": {"attempt_id": "attempt-1"}}
            if item["id"] == "review-approval" else item
            for item in raw.evidence
        )
        with self.assertRaisesRegex(ControlCenterProjectionError, "review evidence is missing"):
            project_control_center(replace(raw, evidence=forged_evidence))
        with sqlite3.connect(self.database) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "REVIEW_OUTCOMES_APPEND_ONLY"):
                connection.execute(
                    "UPDATE review_outcomes SET state='CHANGES_REQUESTED' WHERE id='outcome-1'"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "REVIEW_OUTCOMES_APPEND_ONLY"):
                connection.execute("DELETE FROM review_outcomes WHERE id='outcome-1'")

    def test_review_approval_requires_independent_typed_evidence(self) -> None:
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"):
            self.registry.record_review_outcome(ReviewOutcome(
                id="self-review", review_package_id="REVIEW-1", target_package_id="PACKAGE-1",
                implementer_worker_id="agent-b", reviewer_worker_id="agent-b",
                requested_at="2026-09-24T19:51:00Z", decided_at="2026-09-24T19:54:00Z",
                state=ReviewOutcomeState.APPROVED, approval_evidence_ids=("evidence-1",),
            ))

    def test_review_outcome_rejects_forged_implementer_and_reviewer_provenance(self) -> None:
        self.registry.register_worker(Worker(
            "agent-a", "Agent A", ("platform",), (Lane.PLATFORM,), usage_state="GREEN",
        ))
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """INSERT INTO attempts
                   (id, package_id, worker_id, started_at, ended_at, outcome,
                    runtime_seconds, blocked_seconds, provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 0, '{}')""",
                (
                    "older-agent-a-attempt", "PACKAGE-1", "agent-a",
                    "2026-09-24T19:20:00.000000Z", "2026-09-24T19:30:00.000000Z",
                    "SUCCEEDED",
                ),
            )
        self.registry.record_evidence(Evidence(
            "review-bound", "REVIEW-1", "review", None, "Bound reviewer evidence",
            "2026-09-24T19:54:00Z", {"attempt_id": "review-attempt-1"},
        ))
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_IMPLEMENTER_MISMATCH"):
            self.registry.record_review_outcome(ReviewOutcome(
                id="forged-implementer", review_package_id="REVIEW-1",
                target_package_id="PACKAGE-1", implementer_worker_id="agent-a",
                reviewer_worker_id="claude", requested_at="2026-09-24T19:51:00Z",
                decided_at="2026-09-24T19:54:00Z", state=ReviewOutcomeState.APPROVED,
                approval_evidence_ids=("review-bound",),
            ))

        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """INSERT INTO attempts
                   (id, package_id, worker_id, started_at, ended_at, outcome,
                    runtime_seconds, blocked_seconds, provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 0, '{}')""",
                (
                    "reviewer-target-attempt", "PACKAGE-1", "claude",
                    "2026-09-24T19:31:00.000000Z", "2026-09-24T19:32:00.000000Z",
                    "FAILED",
                ),
            )
        with self.assertRaisesRegex(RegistryConflict, "REVIEWER_IMPLEMENTED_TARGET"):
            self.registry.record_review_outcome(ReviewOutcome(
                id="forged-independence", review_package_id="REVIEW-1",
                target_package_id="PACKAGE-1", implementer_worker_id="agent-b",
                reviewer_worker_id="claude", requested_at="2026-09-24T19:51:00Z",
                decided_at="2026-09-24T19:54:00Z", state=ReviewOutcomeState.APPROVED,
                approval_evidence_ids=("review-bound",),
            ))

    def test_review_outcome_rejects_evidence_not_bound_to_reviewer_attempt(self) -> None:
        self.registry.record_evidence(Evidence(
            "forged-review-evidence", "REVIEW-1", "review", None,
            "Claims approval but names the implementation attempt",
            "2026-09-24T19:54:00Z", {"attempt_id": "attempt-1"},
        ))
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_EVIDENCE_MISMATCH"):
            self.registry.record_review_outcome(ReviewOutcome(
                id="forged-evidence", review_package_id="REVIEW-1",
                target_package_id="PACKAGE-1", implementer_worker_id="agent-b",
                reviewer_worker_id="claude", requested_at="2026-09-24T19:51:00Z",
                decided_at="2026-09-24T19:54:00Z", state=ReviewOutcomeState.APPROVED,
                approval_evidence_ids=("forged-review-evidence",),
            ))

    def test_review_outcome_requires_reviewer_owned_review_attempt(self) -> None:
        self.registry.register_worker(Worker(
            "agent-c", "Agent C", ("review",), (Lane.ASSURANCE,), usage_state="GREEN",
        ))
        with self.assertRaisesRegex(RegistryConflict, "REVIEWER_ATTEMPT_REQUIRED"):
            self.registry.record_review_outcome(ReviewOutcome(
                id="missing-reviewer-attempt", review_package_id="REVIEW-1",
                target_package_id="PACKAGE-1", implementer_worker_id="agent-b",
                reviewer_worker_id="agent-c", requested_at="2026-09-24T19:51:00Z",
                decided_at="2026-09-24T19:54:00Z", state=ReviewOutcomeState.APPROVED,
                approval_evidence_ids=("evidence-1",),
            ))

    def test_review_outcome_rejects_target_attempt_finishing_after_review_request(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """INSERT INTO attempts
                   (id, package_id, worker_id, started_at, ended_at, outcome,
                    runtime_seconds, blocked_seconds, provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?, 120, 0, '{}')""",
                (
                    "overlapping-target-attempt", "PACKAGE-1", "agent-b",
                    "2026-09-24T19:50:30.000000Z", "2026-09-24T19:52:30.000000Z",
                    "FAILED",
                ),
            )
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_TARGET_CHANGED_DURING_REVIEW"):
            self.registry.record_review_outcome(ReviewOutcome(
                id="stale-overlap", review_package_id="REVIEW-1",
                target_package_id="PACKAGE-1", implementer_worker_id="agent-b",
                reviewer_worker_id="claude", requested_at="2026-09-24T19:51:00Z",
                decided_at="2026-09-24T19:54:00Z", state=ReviewOutcomeState.APPROVED,
                approval_evidence_ids=("evidence-1",),
            ))

    def test_review_outcome_rejects_active_target_attempt_at_review_request(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """INSERT INTO attempts
                   (id, package_id, worker_id, started_at, ended_at, outcome,
                    runtime_seconds, blocked_seconds, provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, NULL, NULL, 0, 0, '{}')""",
                (
                    "active-overlapping-target-attempt", "PACKAGE-1", "agent-b",
                    "2026-09-24T19:50:30.000000Z",
                ),
            )
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_TARGET_CHANGED_DURING_REVIEW"):
            self.registry.record_review_outcome(ReviewOutcome(
                id="stale-active-overlap", review_package_id="REVIEW-1",
                target_package_id="PACKAGE-1", implementer_worker_id="agent-b",
                reviewer_worker_id="claude", requested_at="2026-09-24T19:51:00Z",
                decided_at="2026-09-24T19:54:00Z", state=ReviewOutcomeState.APPROVED,
                approval_evidence_ids=("evidence-1",),
            ))

    def test_projection_rejects_target_attempts_overlapping_recorded_review(self) -> None:
        self.registry.record_evidence(Evidence(
            "review-overlap-evidence", "REVIEW-1", "review", None,
            "Bound reviewer evidence", "2026-09-24T19:54:00Z",
            {"attempt_id": "review-attempt-1"},
        ))
        self.registry.record_review_outcome(ReviewOutcome(
            id="outcome-overlap-check", review_package_id="REVIEW-1",
            target_package_id="PACKAGE-1", implementer_worker_id="agent-b",
            reviewer_worker_id="claude", requested_at="2026-09-24T19:51:00Z",
            decided_at="2026-09-24T19:54:00Z", state=ReviewOutcomeState.APPROVED,
            approval_evidence_ids=("review-overlap-evidence",),
        ))
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        target_attempt = next(item for item in raw.attempts if item["id"] == "attempt-1")
        overlaps = (
            {
                **target_attempt, "id": "forged-completed-overlap",
                "started_at": "2026-09-24T19:50:30Z",
                "ended_at": "2026-09-24T19:52:30Z", "outcome": "FAILED",
            },
            {
                **target_attempt, "id": "forged-active-overlap",
                "started_at": "2026-09-24T19:50:30Z",
                "ended_at": None, "outcome": None,
            },
        )
        from scripts.factory_registry.control_center_projection import project_control_center
        for overlapping_attempt in overlaps:
            with self.subTest(attempt_id=overlapping_attempt["id"]):
                with self.assertRaisesRegex(
                    ControlCenterProjectionError, "target changed during review",
                ):
                    project_control_center(replace(
                        raw, attempts=(*raw.attempts, overlapping_attempt),
                    ))

    def test_projection_rejects_packages_missing_from_feature_queue(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        orphan = {**raw.work_packages[0], "id": "ORPHAN", "feature_id": "MISSING"}
        from scripts.factory_registry.control_center_projection import project_control_center
        with self.assertRaisesRegex(ControlCenterProjectionError, "absent from the queue"):
            project_control_center(replace(raw, work_packages=(*raw.work_packages, orphan)))

    def test_validation_rejects_counts_from_another_revision(self) -> None:
        projection = build_control_center_projection(self.registry, observed_at=NOW)
        for field in ("activeParentCount", "readyCount"):
            with self.subTest(field=field):
                tampered = json.loads(json.dumps(projection))
                tampered["factory"][field] += 1
                with self.assertRaisesRegex(ControlCenterProjectionError, "counts do not match"):
                    validate_control_center_projection(tampered)

    def test_unknown_diagnostics_remain_unknown_and_unsafe_links_are_removed(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        worker = dict(raw.workers[0])
        worker["provider_diagnostics"] = {}
        package = dict(raw.work_packages[0])
        package["pr_url"] = "javascript:alert(1)"
        evidence = dict(raw.evidence[0])
        evidence["uri"] = "https://user:secret@example.test/private"
        attempt = dict(raw.attempts[0])
        attempt["provider_diagnostics"] = {
            **attempt["provider_diagnostics"],
            "pr_url": "https://user:secret@example.test/attempt-pr",
        }
        event = dict(raw.events[0])
        event["detail"] = {
            **event["detail"],
            "pr_url": "https://user:secret@example.test/event-pr",
        }
        from scripts.factory_registry.control_center_projection import project_control_center
        projection = project_control_center(replace(
            raw, workers=(worker, *raw.workers[1:]),
            work_packages=(package, *raw.work_packages[1:]), evidence=(evidence,),
            attempts=(attempt, *raw.attempts[1:]), events=(event,),
        ))
        projected_worker = next(item for item in projection["workers"] if item["id"] == worker["id"])
        self.assertEqual(projected_worker["serviceState"], "unknown")
        self.assertEqual(projected_worker["authenticationState"], "unknown")
        self.assertEqual(projected_worker["health"], "constrained")
        projected_package = projection["features"][0]["packages"][0]
        self.assertIsNone(projected_package["pullRequestUrl"])
        self.assertIsNone(projected_package["evidence"][0]["url"])
        self.assertIsNone(projected_package["attempts"][0]["pullRequestUrl"])
        self.assertIsNone(projection["events"][0]["pullRequestUrl"])
        serialized = json.dumps(projection)
        self.assertNotIn("user:secret", serialized)

    def test_capacity_states_match_control_center_contract_exactly(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        from scripts.factory_registry.control_center_projection import project_control_center
        cases = {
            "GREEN": "normal", "CAUTION": "caution", "CHECKPOINT": "checkpoint",
            "FINISH_ONLY": "checkpoint", "HARD_STOP": "hard_stop",
            "LIMITED": "limited", "UNKNOWN": "unknown",
        }
        for source, expected in cases.items():
            worker = dict(raw.workers[0])
            worker["usage_state"] = source
            projection = project_control_center(replace(raw, workers=(worker, *raw.workers[1:])))
            projected = next(item for item in projection["workers"] if item["id"] == worker["id"])
            self.assertEqual(projected["capacityState"], expected)
        limited = dict(raw.usage_invocations[0])
        limited["outcome"] = "LIMITED"
        limited["limit_signal"] = "rate_limit"
        projection = project_control_center(replace(raw, usage_invocations=(limited,)))
        measured = next(item for item in projection["capacity"] if item["source"] == "factory_measured")
        self.assertEqual(measured["state"], "limited")

    def test_stale_or_unknown_idle_orchestra_constrains_worker_and_factory(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        from scripts.factory_registry.control_center_projection import project_control_center
        base_orchestra = {
            "id": "orchestra", "display_name": "Orchestra", "role": "ORCHESTRA",
            "availability": "IDLE", "capabilities": ("coordination",), "approved_lanes": (),
            "provider_diagnostics": {
                "provider": "OpenAI", "model": "Codex",
                "service_state": "healthy", "authentication_state": "valid",
            },
            "last_heartbeat_at": "2026-09-24T19:59:00Z", "usage_state": "GREEN",
        }
        healthy = project_control_center(replace(raw, workers=(*raw.workers, base_orchestra)))
        self.assertEqual(next(item for item in healthy["workers"] if item["id"] == "orchestra")["health"], "healthy")
        self.assertEqual(healthy["factory"]["health"], "healthy")

        cases = (
            {"last_heartbeat_at": "2026-09-24T19:50:00Z"},
            {"provider_diagnostics": {**base_orchestra["provider_diagnostics"], "service_state": "unknown"}},
            {"provider_diagnostics": {**base_orchestra["provider_diagnostics"], "authentication_state": "unknown"}},
        )
        for override in cases:
            with self.subTest(override=override):
                orchestra = {**base_orchestra, **override}
                projection = project_control_center(replace(raw, workers=(*raw.workers, orchestra)))
                worker = next(item for item in projection["workers"] if item["id"] == "orchestra")
                self.assertEqual(worker["health"], "constrained")
                self.assertEqual(projection["factory"]["health"], "constrained")

    def test_resolved_critical_failure_does_not_constrain_factory_attention(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        from scripts.factory_registry.control_center_projection import project_control_center
        orchestra = {
            "id": "orchestra", "display_name": "Orchestra", "role": "ORCHESTRA",
            "availability": "IDLE", "capabilities": ("coordination",), "approved_lanes": (),
            "provider_diagnostics": {
                "provider": "OpenAI", "model": "Codex",
                "service_state": "healthy", "authentication_state": "valid",
            },
            "last_heartbeat_at": "2026-09-24T19:59:00Z", "usage_state": "GREEN",
        }
        recovered = {**raw.failures[0], "code": "AUTH_FAILURE"}
        projection = project_control_center(replace(
            raw, workers=(*raw.workers, orchestra), failures=(recovered,),
        ))
        self.assertFalse(projection["failures"][0]["requiresHuman"])
        self.assertEqual(projection["factory"]["attentionCount"], 0)
        self.assertEqual(projection["factory"]["health"], "healthy")

    def test_sparse_verify_review_evidence_authoritatively_requires_attention(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        from scripts.factory_registry.control_center_projection import project_control_center
        orchestra = {
            "id": "orchestra", "display_name": "Orchestra", "role": "ORCHESTRA",
            "availability": "IDLE", "capabilities": ("coordination",), "approved_lanes": (),
            "provider_diagnostics": {
                "provider": "OpenAI", "model": "Codex",
                "service_state": "healthy", "authentication_state": "valid",
            },
            "last_heartbeat_at": "2026-09-24T19:59:00Z", "usage_state": "GREEN",
        }
        package = {**raw.work_packages[0], "status": "VERIFY_REVIEW", "failure_code": None, "failure_detail": None}
        review_evidence = {
            **raw.evidence[0], "kind": "review", "summary": "Approved rejected words are not structured state",
        }
        historical_failure = {**raw.failures[0], "code": "REVIEW_FAILURE"}
        projection = project_control_center(replace(
            raw,
            workers=(*raw.workers, orchestra),
            work_packages=(package, *raw.work_packages[1:]),
            evidence=(review_evidence,),
            failures=(historical_failure,),
        ))

        historical = next(item for item in projection["failures"] if item["id"] == historical_failure["id"])
        reconciliation = next(item for item in projection["failures"] if item["code"] == "REVIEW_STATE_UNRECORDED")
        self.assertFalse(historical["requiresHuman"])
        self.assertEqual(reconciliation["packageId"], package["id"])
        self.assertTrue(reconciliation["requiresHuman"])
        self.assertEqual(reconciliation["title"], "Review outcome is not recorded")
        self.assertEqual(
            reconciliation["detail"],
            "Review evidence exists for this VERIFY / REVIEW package, but this Registry revision has no structured review outcome or current failure.",
        )
        self.assertEqual(projection["factory"]["attentionCount"], 1)
        self.assertEqual(projection["factory"]["health"], "constrained")
        self.assertNotIn("approved", reconciliation["detail"].lower())
        self.assertNotIn("rejected", reconciliation["detail"].lower())

    def test_projection_is_logically_read_only(self) -> None:
        before = self._logical_state()
        first = build_control_center_projection(self.registry, observed_at=NOW)
        second = build_control_center_projection(self.registry, observed_at=NOW)
        self.assertEqual(first, second)
        self.assertEqual(self._logical_state(), before)

    def test_preservation_reconciliation_projects_actual_artifact_counts(self) -> None:
        reconciliation = {
            "expected_tasks": 0, "imported_tasks": 0,
            "expected_workers": 0, "imported_workers": 0,
            "expected_worktrees": 2, "imported_worktrees": 2,
            "expected_branches": 1, "imported_branches": 1,
            "unexplained_records": 0,
        }
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO preservation_imports VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("import-1", "/preserved.json", "a" * 64, "2026-09-24T19:55:00Z", 1, json.dumps(reconciliation), "{}"),
            )
            for artifact_id, kind, identity, dirty in (
                ("artifact-1", "WORKTREE", "/tmp/one", 1),
                ("artifact-2", "WORKTREE", "/tmp/two", 0),
                ("artifact-3", "BRANCH", "codex/preserved", 0),
            ):
                connection.execute(
                    "INSERT INTO preserved_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                    (artifact_id, "import-1", kind, identity, dirty, "{}"),
                )
            connection.execute("UPDATE registry_metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        reconciliation_view = build_control_center_projection(self.registry, observed_at=NOW)["reconciliation"]
        self.assertEqual(reconciliation_view["status"], "clean")
        self.assertEqual(reconciliation_view["worktreeCount"], 2)
        self.assertEqual(reconciliation_view["dirtyWorktreeCount"], 1)
        self.assertEqual(reconciliation_view["unmergedBranchCount"], 1)

    def test_ready_review_package_is_visible_without_invented_approval(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        from scripts.factory_registry.control_center_projection import project_control_center
        projection = project_control_center(raw)
        review = projection["reviews"][0]
        self.assertEqual(review["state"], "waiting")
        self.assertEqual(review["implementerWorkerId"], "agent-b")
        self.assertEqual(review["eligibleReviewerIds"], ["claude"])
        self.assertIsNone(review["assignedReviewerId"])

    def test_backend_neutral_boundary_requires_only_control_center_snapshot(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)

        class ReadOnlyRegistry:
            def control_center_snapshot(self, *, observed_at: str):
                self.observed_at = observed_at
                return replace(raw, observed_at=observed_at)

        registry = ReadOnlyRegistry()
        projection = build_control_center_projection(registry, observed_at=NOW)  # type: ignore[arg-type]
        self.assertEqual(registry.observed_at, NOW)
        self.assertEqual(projection["registryRevision"], str(raw.revision))

    def test_wrong_usage_worker_fails_closed(self) -> None:
        raw = self.registry.control_center_snapshot(observed_at=NOW)
        usage = dict(raw.usage_invocations[0])
        usage["worker_id"] = "agent-b"
        with self.assertRaisesRegex(ControlCenterProjectionError, "does not own"):
            from scripts.factory_registry.control_center_projection import project_control_center
            project_control_center(replace(raw, usage_invocations=(usage,)))

    def test_serialization_is_deterministic(self) -> None:
        projection = build_control_center_projection(self.registry, observed_at=NOW)
        first = serialize_control_center_projection(projection)
        second = serialize_control_center_projection(dict(reversed(list(projection.items()))))
        self.assertEqual(first, second)


class ProjectionTransportTest(ControlCenterProjectionTest):
    def setUp(self) -> None:
        super().setUp()
        handler = create_projection_handler(
            self.registry, bearer_token=TOKEN, signing_secret=SECRET, now=lambda: NOW
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/factory-control"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def test_authenticated_response_is_hmac_signed_over_exact_body(self) -> None:
        request = Request(self.url, headers={"Authorization": f"Bearer {TOKEN}"})
        with urlopen(request) as response:
            body = response.read()
            signature = response.headers[SIGNATURE_HEADER]
            self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
        expected = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(signature, f"sha256={expected}")
        validate_control_center_projection(json.loads(body))

    def test_missing_or_wrong_bearer_fails_closed(self) -> None:
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as caught:
                urlopen(Request(self.url, headers=headers))
            self.assertEqual(caught.exception.code, 401)

    def test_transport_exposes_no_write_method(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.url, data=b"{}", method="POST", headers={"Authorization": f"Bearer {TOKEN}"}))
        self.assertEqual(caught.exception.code, 405)

    def test_non_loopback_bind_is_rejected_before_server_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            serve_local_projection(
                self.registry, bearer_token=TOKEN, signing_secret=SECRET,
                host="0.0.0.0", port=0,
            )


if __name__ == "__main__":
    unittest.main()
