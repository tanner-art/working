import pathlib
import sys
import tempfile
import unittest
import json
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from registry_control import RunnerRegistryControl, queue_contract_digest
import runner
from runner import RegistryAttemptLifecycle, run
from scripts.factory_registry.codex_capacity import CapacityCollectorError
from scripts.factory_registry.claude_telemetry import claude_provider_signal
from scripts.factory_registry import (
    Feature,
    Lane,
    PackageKind,
    RegistryConflict,
    ReviewInput,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
)
from scripts.factory_registry.models import Evidence, ReviewOutcome, ReviewOutcomeState


class RunnerRegistryControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = pathlib.Path(self.temporary.name) / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def seed_assignment(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker(
                "worker-a",
                "Worker A",
                ("registry",),
                (Lane.PLATFORM,),
                usage_state="GREEN",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1",
                "FEATURE",
                "Task",
                "ORCHESTRATION",
                Lane.PLATFORM,
                ("registry",),
                10,
                ("verified",),
                status=TaskStatus.READY,
            )
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at=(now - timedelta(minutes=2)).isoformat(),
            reason="bounded canary",
        )
        self.registry.acquire_lease(
            "TASK-1",
            "worker-a",
            acquired_at=(now - timedelta(minutes=1)).isoformat(),
            expires_at=(now + timedelta(minutes=20)).isoformat(),
        )

    def test_is_absent_for_legacy_config_and_rejects_relative_database(self):
        self.assertIsNone(RunnerRegistryControl.from_config({}))
        with self.assertRaisesRegex(ValueError, "absolute"):
            RunnerRegistryControl.from_config({"registry_database": "registry.sqlite3"})

    def test_pre_claim_fails_closed_while_registry_is_paused(self):
        control = RunnerRegistryControl(self.database)
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            control.pre_claim()

    def test_pre_claim_requires_the_exact_registry_assignment_and_revision(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock(dispatch_control=Mock(return_value={}))
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(revision=17)
        control.registry.require_live_dispatch.return_value = 17
        eligible = SimpleNamespace(package_id="TASK-1", worker_id="worker-a")
        decision = SimpleNamespace(proposed_assignments=(eligible,), pair_evaluations=())
        with patch("registry_control.decide_shadow", return_value=decision):
            self.assertEqual(control.pre_claim("TASK-1", "worker-a"), 17)
        control.registry.require_live_dispatch.assert_called_once_with(
            expected_revision=17
        )

        with patch(
            "registry_control.decide_shadow",
            return_value=SimpleNamespace(
                proposed_assignments=(), pair_evaluations=()
            ),
        ):
            with self.assertRaisesRegex(RegistryConflict, "PAIR_NOT_FOUND"):
                control.pre_claim("TASK-1", "worker-a")

    def test_pre_claim_pins_the_normalized_queue_contract(self):
        body = {
            "task": "TASK-1", "paths": ["docs/canary.md"],
            "instructions": "Write the canary.", "depends_on": [],
            "lane": "PLATFORM", "kind": "PARENT",
            "capacity_size": "VERY_SMALL", "capacity_risk": "BOUNDED",
        }
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.dispatch_control.return_value = {}
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            revision=17,
            work_packages=({
                "id": "TASK-1",
                "provider_diagnostics": {
                    "queue_contract_sha256": queue_contract_digest(body),
                },
            },),
        )
        control.registry.require_live_dispatch.return_value = 17
        eligible = SimpleNamespace(package_id="TASK-1", worker_id="worker-a")
        decision = SimpleNamespace(proposed_assignments=(eligible,), pair_evaluations=())
        with patch("registry_control.decide_shadow", return_value=decision):
            self.assertEqual(
                control.pre_claim("TASK-1", "worker-a", task_contract=body), 17
            )
            changed = dict(body, instructions="Different work")
            with self.assertRaisesRegex(RegistryConflict, "QUEUE_CONTRACT_MISMATCH"):
                control.pre_claim("TASK-1", "worker-a", task_contract=changed)

    def test_review_preclaim_excludes_the_actual_implementer(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock(dispatch_control=Mock(return_value={}))
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            revision=17,
            work_packages=({"id": "TASK-REVIEW", "kind": "REVIEW"},),
        )
        control.registry.review_implementer_worker.return_value = "worker-a"
        control.registry.require_live_dispatch.return_value = 17
        eligible = SimpleNamespace(package_id="TASK-REVIEW", worker_id="worker-b")
        decision = SimpleNamespace(proposed_assignments=(eligible,), pair_evaluations=())
        with patch("registry_control.decide_shadow", return_value=decision):
            with self.assertRaisesRegex(
                RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"
            ):
                control.pre_claim("TASK-REVIEW", "worker-a")
            self.assertEqual(control.pre_claim("TASK-REVIEW", "worker-b"), 17)
        control.registry.review_implementer_worker.assert_called_with("TASK-REVIEW")

    def test_review_preclaim_fails_closed_when_its_bound_input_is_missing(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock(dispatch_control=Mock(return_value={}))
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            revision=17,
            work_packages=({"id": "TASK-REVIEW", "kind": "REVIEW"},),
        )
        control.registry.review_input.side_effect = RegistryConflict("REVIEW_INPUT_REQUIRED")
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_REQUIRED"):
            control.pre_claim("TASK-REVIEW", "worker-b")
        control.registry.review_implementer_worker.assert_not_called()

    def test_review_preclaim_uses_real_sqlite_branch_when_no_review_input_exists(self):
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-REVIEW", "FEATURE", "Review", "ORCHESTRATION",
                Lane.ASSURANCE, ("review",), 10, ("review",),
                kind=PackageKind.REVIEW, status=TaskStatus.READY,
            )
        )
        with self.registry._connection() as connection:
            evidence_count = connection.execute(
                "SELECT COUNT(*) FROM evidence WHERE package_id=? AND kind='review-input'",
                ("TASK-REVIEW",),
            ).fetchone()[0]
        self.assertEqual(evidence_count, 0)

        control = RunnerRegistryControl(self.database)
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_REQUIRED"):
            control.pre_claim("TASK-REVIEW", "worker-b")

    def test_operator_review_only_input_to_bounded_followup_claim_preserves_independence_and_exact_pr(self):
        """Exercise the real Registry write/claim path with fake PR service results."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = lambda value: value.isoformat().replace("+00:00", "Z")
        contract = {"task": "TASK-FOLLOWUP", "paths": ["docs/review.md"], "depends_on": []}
        digest = queue_contract_digest(contract)
        self.registry.register_feature(Feature("LEGACY", "multi-parent legacy", 10, TaskStatus.READY))
        self.registry.register_work_package(WorkPackage(
            "TASK-TARGET", "LEGACY", "historical implementation", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 10, ("historical success",), status=TaskStatus.READY,
        ))
        self.registry.register_work_package(WorkPackage(
            "TASK-REVIEW-OLD", "LEGACY", "preserved review", "ASSURANCE", Lane.ASSURANCE,
            ("review",), 10, ("changes requested retained",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-TARGET",),
        ))
        for worker in (
            Worker("implementer", "Implementer", ("registry",), (Lane.PLATFORM,), provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["implementer"]}, last_heartbeat_at=stamp(now), usage_state="NORMAL"),
            Worker("reviewer", "Reviewer", ("review",), (Lane.ASSURANCE,), provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["reviewer"]}, last_heartbeat_at=stamp(now), usage_state="NORMAL"),
            Worker("orchestra", "Orchestra", (), (), role="ORCHESTRA", provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["orchestra"]}, last_heartbeat_at=stamp(now), usage_state="NORMAL"),
        ):
            self.registry.register_worker(worker)

        def capacity(worker_id, percent):
            self.registry.record_worker_capacity_observations(worker_id, ({
                "id": f"usage-{worker_id}", "worker_id": worker_id, "observed_at": stamp(now),
                "reset_at": None, "consumed_percent": percent, "state": "NORMAL",
                "provider_diagnostics": {"capacity_mode": "percentage", "capacity_scope": worker_id},
            },), recorded_at=stamp(now))
        capacity("implementer", 10); capacity("reviewer", 10); capacity("orchestra", 10)

        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False, changed_at=stamp(now), reason="historical fixture")
        lease = self.registry.acquire_lease("TASK-TARGET", "implementer", acquired_at=stamp(now), expires_at=stamp(now + timedelta(minutes=5)), expected_dispatch_revision=self.registry.dispatch_control()["revision"])
        self.registry.begin_attempt_runtime("implementation", package_id="TASK-TARGET", worker_id="implementer", runner_pid=1, started_at=stamp(now + timedelta(seconds=1)), expected_revision=self.registry.dispatch_control()["revision"])
        self.registry.finish_attempt_runtime("implementation", ended_at=stamp(now + timedelta(seconds=2)), outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="historical success")
        self.assertIsNotNone(lease.id)
        review_lease = self.registry.acquire_lease("TASK-REVIEW-OLD", "reviewer", acquired_at=stamp(now + timedelta(seconds=3)), expires_at=stamp(now + timedelta(minutes=5)), expected_dispatch_revision=self.registry.dispatch_control()["revision"])
        self.registry.begin_attempt_runtime("old-review", package_id="TASK-REVIEW-OLD", worker_id="reviewer", runner_pid=1, started_at=stamp(now + timedelta(seconds=4)), expected_revision=self.registry.dispatch_control()["revision"])
        self.registry.finish_attempt_runtime("old-review", ended_at=stamp(now + timedelta(seconds=5)), outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="preserved changes request")
        self.assertIsNotNone(review_lease.id)
        self.registry.engage_dispatch_kill_switch(changed_at=stamp(now + timedelta(seconds=6)), reason="review-only preflight")
        paused = self.registry.dispatch_control()
        self.registry.set_dispatch_control(expected_revision=paused["revision"], expected_mode="STOPPING", new_mode="PAUSED", kill_switch_engaged=True, changed_at=stamp(now + timedelta(seconds=7)), reason="ownership drained")

        def review_input(review_id, input_id):
            packet = pathlib.Path(self.temporary.name) / input_id; packet.mkdir()
            files = {"base-to-implementation.diff": b"diff", "changed-files.txt": b"docs/review.md\n",
                     "contract.json": json.dumps(contract, sort_keys=True).encode(), "validation-evidence.json": b"{}"}
            for name, content in files.items(): (packet / name).write_bytes(content)
            hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
            manifest = {"schema_version": 1, "implementation_attempt_id": "implementation", "implementation_commit": "a" * 40,
                        "base_commit": "b" * 40, "files": hashes}
            raw = json.dumps(manifest, sort_keys=True).encode(); (packet / "manifest.json").write_bytes(raw)
            return ReviewInput(input_id, review_id, "TASK-TARGET", "implementation", "a" * 40, "b" * 40,
                "https://example.test/pull/261", digest, contract,
                {"ci": {"state": "SUCCESS", "implementation_commit": "a" * 40, "pr_url": "https://example.test/pull/261"},
                 "review_packet": {"path": str(packet), "manifest_sha256": hashlib.sha256(raw).hexdigest(), "files": hashes}},
                stamp(now + timedelta(seconds=8)))

        old_input = review_input("TASK-REVIEW-OLD", "old-input")
        self.registry.record_operator_review_input(old_input, expected_revision=self.registry.dispatch_control()["revision"])
        self.registry.record_review_outcome(ReviewOutcome(
            id="changes-requested", review_package_id="TASK-REVIEW-OLD", target_package_id="TASK-TARGET",
            implementer_worker_id="implementer", reviewer_worker_id="reviewer", requested_at=stamp(now + timedelta(seconds=3)),
            decided_at=stamp(now + timedelta(seconds=9)), state=ReviewOutcomeState.CHANGES_REQUESTED,
            changes_requested=("Review again against the exact head.",), reviewed_commit="a" * 40,
            reviewed_base_commit="b" * 40, contract_sha256=digest, review_input_evidence_id="old-input", reviewer_attempt_id="old-review",
        ), evidence=Evidence("old-decision", "TASK-REVIEW-OLD", "review", None, "Preserved changes request.", stamp(now + timedelta(seconds=5)),
            {"attempt_id": "old-review", "reviewed_commit": "a" * 40, "reviewed_base_commit": "b" * 40, "contract_sha256": digest, "review_input_evidence_id": "old-input"}), expected_revision=self.registry.dispatch_control()["revision"])
        followup = WorkPackage("TASK-FOLLOWUP", "LEGACY", "fresh review", "ASSURANCE", Lane.ASSURANCE,
            ("review",), 10, ("independent review",), status=TaskStatus.READY, kind=PackageKind.REVIEW,
            dependency_ids=("TASK-TARGET",), provider_diagnostics={
                "queue_contract_sha256": digest, "github_source_ref": "312",
            })
        self.registry.register_followup_review(followup, expected_revision=self.registry.dispatch_control()["revision"], recorded_at=stamp(now + timedelta(seconds=10)))
        snapshot = self.registry.dispatch_snapshot(observed_at=stamp(now + timedelta(seconds=10)))
        registered = next(item for item in snapshot.work_packages if item["id"] == "TASK-FOLLOWUP")
        self.assertEqual(registered["source_ref"], "312")
        self.registry.record_operator_review_input(review_input("TASK-FOLLOWUP", "followup-input"), expected_revision=self.registry.dispatch_control()["revision"])
        deadline_contract = {"task": "TASK-DEADLINE", "paths": ["docs/review.md"]}
        self.registry.register_work_package(WorkPackage(
            "TASK-DEADLINE", "LEGACY", "deadline probe", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 1, ("deadline enforcement",), status=TaskStatus.READY,
            provider_diagnostics={"queue_contract_sha256": queue_contract_digest(deadline_contract)},
        ))
        self.registry.bind_legacy_package_source(
            "TASK-DEADLINE", github_issue=999, queue_contract=deadline_contract,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=stamp(now + timedelta(seconds=10)),
        )

        live = self.registry.dispatch_control()
        deadline = now + timedelta(minutes=2)
        self.registry.set_dispatch_control(expected_revision=live["revision"], expected_mode="PAUSED", new_mode="LIVE", kill_switch_engaged=False, changed_at=stamp(now + timedelta(seconds=11)), reason="bounded followup", bounded_run={"run_id": "review-261", "package_ids": ["TASK-FOLLOWUP", "TASK-DEADLINE"], "deadline": stamp(deadline), "base_ref": "main", "parent_limit": 1})
        runner_control = RunnerRegistryControl(self.database)
        self.assertEqual(runner_control.bounded_source_issues(), (312, 999))
        with patch("registry_control.utc_now", return_value=stamp(now + timedelta(seconds=12))):
            with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAIR_INELIGIBLE"):
                runner_control.pre_claim("TASK-TARGET", "implementer")
            with self.assertRaisesRegex(RegistryConflict, "REVIEW_INDEPENDENCE_REQUIRED"):
                runner_control.pre_claim("TASK-FOLLOWUP", "implementer", task_contract=contract)
            with self.assertRaisesRegex(RegistryConflict, "GITHUB_SOURCE_MISMATCH"):
                runner_control.pre_claim(
                    "TASK-FOLLOWUP", "reviewer", task_contract=contract, github_issue=351,
                )
            revision = runner_control.pre_claim(
                "TASK-FOLLOWUP", "reviewer", task_contract=contract, github_issue=312,
            )
            lease_id = runner_control.claim_package("TASK-FOLLOWUP", worker_id="reviewer", expected_revision=revision, lease_seconds=300)
        self.assertTrue(lease_id)
        github = lambda *args: json.dumps({"headRefOid": "a" * 40}) if args[:2] == ("pr", "view") else json.dumps([{"name": "verify", "workflow": "Validate app", "state": "SUCCESS"}])
        self.assertTrue(runner.review_source_is_green(github, "owner/repo", review_input("TASK-FOLLOWUP", "green-check")))
        self.assertFalse(runner.review_source_is_green(lambda *args: json.dumps({"headRefOid": "c" * 40}) if args[:2] == ("pr", "view") else "[]", "owner/repo", review_input("TASK-FOLLOWUP", "wrong-head")))
        with patch("registry_control.datetime") as clock:
            clock.now.return_value = deadline + timedelta(seconds=1)
            with self.assertRaisesRegex(RegistryConflict, "RUN_DEADLINE_EXPIRED"):
                runner_control.claim_package("TASK-DEADLINE", worker_id="implementer", expected_revision=self.registry.dispatch_control()["revision"], lease_seconds=30)

    def test_claim_package_pins_dispatch_revision(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.acquire_lease.return_value = SimpleNamespace(id="lease-1")
        with patch("registry_control.datetime") as clock:
            clock.now.return_value = __import__('datetime').datetime(
                2026, 9, 25, tzinfo=__import__('datetime').timezone.utc
            )
            lease_id = control.claim_package(
                "TASK-1", worker_id="worker-a", expected_revision=9,
                lease_seconds=300,
            )
        self.assertEqual(lease_id, "lease-1")
        self.assertEqual(
            control.registry.acquire_lease.call_args.kwargs["expected_dispatch_revision"],
            9,
        )

    def test_claim_retry_redecides_once_for_a_revision_race(self):
        control = RunnerRegistryControl(self.database)
        with patch.object(control, "pre_claim", side_effect=[11, 12]) as pre_claim, \
                patch.object(control, "claim_package", side_effect=[
                    RegistryConflict("DISPATCH_REVISION_CHANGED"), "lease-2",
                ]) as claim:
            self.assertEqual(
                control.claim_with_retry(
                    "TASK-1", worker_id="worker-a", task_contract={"task": "TASK-1"},
                    lease_seconds=300,
                ),
                ("lease-2", 12),
            )
        self.assertEqual(pre_claim.call_count, 2)
        self.assertEqual(claim.call_count, 2)

    def test_reservation_revalidates_only_a_benign_heartbeat_revision_race(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        stale_revision = self.registry.dispatch_control()["revision"]
        self.registry.record_worker_heartbeat(
            "worker-a", observed_at=datetime.now(timezone.utc).isoformat()
        )
        with patch("registry_control.os.getpid", return_value=901):
            control.reserve_attempt(
                "attempt-heartbeat-race", package_id="TASK-1", worker_id="worker-a",
                expected_revision=stale_revision,
            )
        self.assertTrue(self.registry.attempt_exists("attempt-heartbeat-race"))

    def test_reservation_does_not_retry_across_a_stop(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        stale_revision = self.registry.dispatch_control()["revision"]
        self.registry.engage_dispatch_kill_switch(
            changed_at=datetime.now(timezone.utc).isoformat(), reason="stop"
        )
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_NOT_AUTHORIZED"):
            control.reserve_attempt(
                "attempt-stopped", package_id="TASK-1", worker_id="worker-a",
                expected_revision=stale_revision,
            )
        self.assertFalse(self.registry.attempt_exists("attempt-stopped"))

    def test_pre_claim_enforces_ready_review_priority_at_the_controller(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock(dispatch_control=Mock(return_value={}))
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            revision=17,
            work_packages=(
                {"id": "TASK-PARENT", "kind": "PARENT", "status": "READY", "priority": 99},
                {"id": "TASK-REVIEW", "kind": "REVIEW", "status": "READY", "priority": 1},
            ),
        )
        control.registry.require_live_dispatch.return_value = 17
        control.registry.review_implementer_worker.return_value = "builder"
        decision = SimpleNamespace(proposed_assignments=(
            SimpleNamespace(package_id="TASK-PARENT", worker_id="builder"),
            SimpleNamespace(package_id="TASK-REVIEW", worker_id="reviewer"),
        ), pair_evaluations=())
        with patch("registry_control.decide_shadow", return_value=decision):
            with self.assertRaisesRegex(RegistryConflict, "SESSION_QUEUE_PRIORITY"):
                control.pre_claim("TASK-PARENT", "builder")
            self.assertEqual(control.pre_claim("TASK-REVIEW", "reviewer"), 17)

    def test_pre_claim_uses_live_registry_health_and_capacity_evidence(self):
        now = datetime.now(timezone.utc).isoformat()
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker(
                "worker-a", "Worker A", ("registry",), (Lane.PLATFORM,),
                provider_diagnostics={
                    "capacity_mode": "provider_signal",
                    "capacity_scopes": ["provider_signal"],
                },
                last_heartbeat_at=now,
                usage_state="NORMAL",
            )
        )
        self.registry.register_worker(
            Worker(
                "orchestra", "Orchestra", (), (), role="ORCHESTRA",
                provider_diagnostics={
                    "capacity_mode": "percentage",
                    "capacity_scopes": ["weekly"],
                },
                last_heartbeat_at=now,
                usage_state="NORMAL",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1", "FEATURE", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 10, ("verified",), status=TaskStatus.READY,
            )
        )
        now = datetime.now(timezone.utc).isoformat()
        with self.registry._connection() as connection:
            connection.execute(
                """INSERT INTO usage_observations
                   (id, worker_id, observed_at, consumed_percent, state,
                    provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "usage-worker", "worker-a", now, None, "NORMAL",
                    json.dumps({
                        "capacity_mode": "provider_signal",
                        "capacity_scope": "provider_signal",
                        "service_state": "healthy",
                        "authentication_state": "valid",
                        "live_invocation_state": "succeeded",
                        "limit_signal": "NONE",
                    }),
                ),
            )
            connection.execute(
                """INSERT INTO usage_observations
                   (id, worker_id, observed_at, consumed_percent, state,
                    provider_diagnostics_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "usage-orchestra", "orchestra", now, 10, "NORMAL",
                    json.dumps({
                        "capacity_mode": "percentage",
                        "capacity_scope": "weekly",
                    }),
                ),
            )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=now,
            reason="bounded canary",
        )
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.utc_now", return_value=now):
            revision = control.pre_claim("TASK-1", "worker-a")
        self.assertEqual(revision, self.registry.dispatch_control()["revision"])

    def test_reserve_launch_and_failure_are_durable(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        revision = control.pre_claim()
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1",
                package_id="TASK-1",
                worker_id="worker-a",
                expected_revision=revision,
            )
        control.pre_launch()
        control.record_process("attempt-1", pid=901, pgid=901)
        control.fail("attempt-1", "bounded failure")

        with self.registry._connection() as connection:
            runtime = connection.execute(
                """SELECT runner_pid, agent_pid, agent_pgid, released_at
                   FROM attempt_runtime_ownership WHERE attempt_id='attempt-1'"""
            ).fetchone()
            attempt = connection.execute(
                "SELECT outcome, failure_detail FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            package = connection.execute(
                "SELECT status, runtime_seconds FROM work_packages WHERE id='TASK-1'"
            ).fetchone()
            attempt_runtime = connection.execute(
                "SELECT runtime_seconds FROM attempts WHERE id='attempt-1'"
            ).fetchone()[0]
        self.assertEqual(tuple(runtime[:3]), (900, 901, 901))
        self.assertIsNotNone(runtime[3])
        self.assertEqual(tuple(attempt), ("FAILED", "bounded failure"))
        self.assertEqual(package[0], "BLOCKED")
        self.assertGreaterEqual(attempt_runtime, 0.0)
        self.assertEqual(attempt_runtime, package[1])

    def test_success_runtime_updates_attempt_and_package_once_on_replay(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        started = datetime.now(timezone.utc)
        with patch("registry_control.utc_now", return_value=started.isoformat()), \
                patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-runtime-success", package_id="TASK-1", worker_id="worker-a",
                expected_revision=control.pre_claim(),
            )
        ended = started + timedelta(seconds=12.5)
        control.succeed(
            "attempt-runtime-success", ended_at=ended.isoformat()
        )
        # Operation replay must not add a second duration even if its caller
        # uses a later wall time.
        control.succeed(
            "attempt-runtime-success", ended_at=(ended + timedelta(seconds=5)).isoformat()
        )
        with self.registry._connection() as connection:
            attempt = connection.execute(
                "SELECT runtime_seconds FROM attempts WHERE id='attempt-runtime-success'"
            ).fetchone()[0]
            package = connection.execute(
                "SELECT runtime_seconds FROM work_packages WHERE id='TASK-1'"
            ).fetchone()[0]
        self.assertEqual(attempt, 12.5)
        self.assertEqual(package, 12.5)

    def test_failed_and_zero_duration_runtime_are_attempt_accounted(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        started = datetime.now(timezone.utc)
        with patch("registry_control.utc_now", return_value=started.isoformat()), \
                patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-runtime-zero", package_id="TASK-1", worker_id="worker-a",
                expected_revision=control.pre_claim(),
            )
        with patch("registry_control.utc_now", return_value=started.isoformat()):
            control.fail("attempt-runtime-zero", "zero-duration failure")
        with self.registry._connection() as connection:
            attempt = connection.execute(
                "SELECT outcome, runtime_seconds FROM attempts WHERE id='attempt-runtime-zero'"
            ).fetchone()
            package = connection.execute(
                "SELECT runtime_seconds FROM work_packages WHERE id='TASK-1'"
            ).fetchone()[0]
        self.assertEqual(tuple(attempt), ("FAILED", 0.0))
        self.assertEqual(package, 0.0)

    def test_bad_runtime_chronology_leaves_both_counters_unchanged(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        started = datetime.now(timezone.utc)
        with patch("registry_control.utc_now", return_value=started.isoformat()), \
                patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-runtime-bad-time", package_id="TASK-1", worker_id="worker-a",
                expected_revision=control.pre_claim(),
            )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_ATTEMPT_CHRONOLOGY"):
            control.succeed(
                "attempt-runtime-bad-time",
                ended_at=(started - timedelta(seconds=1)).isoformat(),
            )
        with self.registry._connection() as connection:
            counters = connection.execute(
                "SELECT (SELECT runtime_seconds FROM attempts WHERE id='attempt-runtime-bad-time'), "
                "runtime_seconds FROM work_packages WHERE id='TASK-1'"
            ).fetchone()
        self.assertEqual(tuple(counters), (0.0, 0.0))

    def test_live_heartbeat_observation_preserves_busy_lease_and_worker_identity(self):
        self.seed_assignment()
        before = self.registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
        worker = next(value for value in before.workers if value["id"] == "worker-a")
        lease = next(value for value in before.active_leases if value["worker_id"] == "worker-a")
        observed_at = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
        control = RunnerRegistryControl(self.database)
        control.observe_worker_heartbeat("worker-a", observed_at=observed_at)
        after = self.registry.dispatch_snapshot(observed_at=observed_at)
        current = next(value for value in after.workers if value["id"] == "worker-a")
        self.assertEqual(current["availability"], "BUSY")
        self.assertEqual(current["capabilities"], worker["capabilities"])
        self.assertEqual(current["approved_lanes"], worker["approved_lanes"])
        self.assertEqual(current["last_heartbeat_at"], observed_at.replace("+00:00", "Z"))
        self.assertEqual(
            next(value for value in after.active_leases if value["id"] == lease["id"]),
            lease,
        )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_HEARTBEAT_CHRONOLOGY"):
            control.observe_worker_heartbeat("worker-a", observed_at="2000-01-01T00:00:00Z")
        with self.assertRaisesRegex(RegistryConflict, "INVALID_HEARTBEAT_CHRONOLOGY"):
            control.observe_worker_heartbeat("worker-a", observed_at=observed_at)

    def test_idle_peer_liveness_can_be_refreshed_through_polling_without_usage_refresh(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(Feature("FEATURE", "Feature", 10, TaskStatus.READY))
        for worker_id in ("worker-a", "worker-b"):
            self.registry.register_worker(Worker(
                worker_id, worker_id, ("registry",), (Lane.PLATFORM,),
                provider_diagnostics={"capacity_scope": "short_window"},
                last_heartbeat_at=(now - timedelta(minutes=10)).isoformat(),
            ))
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=now.isoformat(),
            reason="polling fixture",
        )
        runner_a = RunnerRegistryControl(self.database)
        runner_b = RunnerRegistryControl(self.database)
        runner_a.observe_worker_heartbeat("worker-a", observed_at=now.isoformat())
        peer_time = (now + timedelta(seconds=30)).isoformat()
        runner_b.observe_worker_heartbeat("worker-b", observed_at=peer_time)
        snapshot = self.registry.dispatch_snapshot(observed_at=peer_time)
        workers = {worker["id"]: worker for worker in snapshot.workers}
        self.assertEqual(workers["worker-a"]["availability"], "IDLE")
        self.assertEqual(workers["worker-b"]["availability"], "IDLE")
        self.assertEqual(workers["worker-b"]["last_heartbeat_at"], peer_time.replace("+00:00", "Z"))
        self.assertEqual(
            workers["worker-b"]["provider_diagnostics"],
            {"capacity_scope": "short_window"},
        )

    def test_capacity_sources_are_isolated_and_alias_mismatch_does_not_block_claude(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            workers=(
                {"id": "codex-a", "provider_diagnostics": {}},
                {"id": "codex-b", "provider_diagnostics": {}},
                {"id": "orchestra-agent-b", "provider_diagnostics": {"capacity_pool": "wrong"}},
                {"id": "claude", "provider_diagnostics": {}},
            ), active_leases=(), usage_observations=(),
        )
        sample = {"ordinary_usage_allowed": True, "account_identity_sha256": "pool-b",
                  "observed_at": "2026-09-26T10:00:00Z",
                  "primary": {"usedPercent": 12, "windowDurationMins": 300}}
        config = {"capacity_collectors": {
            "codex-a": {"executable": "/bin/a", "codex_home": "/tmp/a"},
            "codex-b": {"executable": "/bin/b", "codex_home": "/tmp/b",
                        "shared_account_aliases": ["orchestra-agent-b"]},
        }, "claude_health_probe": {"worker_id": "claude", "command": ["python", "claude_keychain.py", "exec", "/claude"]}}
        with patch("registry_control.collect_rate_limits", side_effect=[
                CapacityCollectorError("unavailable"), sample]), \
                patch("registry_control.probe_claude_health", return_value={
                    "succeeded": True, "limit_signal": None, "returncode": 0,
                    "observed_at": "2026-09-26T10:00:01Z"}), \
                patch("registry_control.utc_now", return_value="2026-09-26T10:00:02Z"):
            collected = control.refresh_configured_capacity(config)
        self.assertEqual([item["worker_id"] for item in collected],
                         ["codex-a", "codex-b", "orchestra-agent-b", "claude"])
        self.assertEqual(collected[0]["observations"], ())
        self.assertEqual(collected[2]["observations"], ())
        self.assertEqual(collected[3]["observations"][0]["state"], "NORMAL")
        self.assertEqual(control.registry.record_worker_capacity_observations.call_count, 2)

    def test_busy_claude_is_skipped_and_malformed_probe_is_restrictive(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        snapshot = SimpleNamespace(
            workers=({"id": "claude", "provider_diagnostics": {}},),
            active_leases=({"worker_id": "claude"},), usage_observations=(),
        )
        control.registry.dispatch_snapshot.return_value = snapshot
        config = {"capacity_collectors": {}, "claude_health_probe": {
            "worker_id": "claude", "command": ["bad"], "cadence_seconds": 60}}
        self.assertEqual(control.refresh_configured_capacity(config), ())
        control.registry.record_worker_capacity_observations.assert_not_called()
        # A still-active lease is intentionally not released or reconfigured;
        # its expired provider signal remains constrained until real evidence.
        snapshot.active_leases = ()
        with patch("registry_control.utc_now", return_value="2026-09-26T10:00:00Z"):
            collected = control.refresh_configured_capacity(config)
        observation = collected[0]["observations"][0]
        self.assertEqual(observation["state"], "HARD_STOP")
        self.assertEqual(observation["provider_diagnostics"]["limit_signal"], "CAPACITY_LAUNCH_FAILURE")

    def test_fresh_claude_signal_suppresses_duplicate_probe(self):
        control = RunnerRegistryControl(self.database)
        control.registry = Mock()
        control.registry.dispatch_snapshot.return_value = SimpleNamespace(
            workers=({"id": "claude", "provider_diagnostics": {}},), active_leases=(),
            usage_observations=({"worker_id": "claude", "capacity_scope": "provider_signal",
                                "observed_at": "2026-09-26T10:00:00Z"},),
        )
        config = {"capacity_collectors": {}, "claude_health_probe": {
            "worker_id": "claude", "command": ["python", "claude_keychain.py", "exec", "/claude"],
            "cadence_seconds": 60}}
        with patch("registry_control.utc_now", return_value="2026-09-26T10:00:30Z"), \
                patch("registry_control.probe_claude_health") as probe:
            self.assertEqual(control.refresh_configured_capacity(config), ())
        probe.assert_not_called()

    def test_expired_claude_signal_is_reprobed_without_changing_ownership(self):
        self.seed_assignment()
        self.registry.register_worker(Worker(
            "claude", "Claude", ("review",), (Lane.ASSURANCE,),
            provider_diagnostics={"capacity_mode": "provider_signal",
                                  "capacity_scopes": ["provider_signal"]},
        ))
        prior_at = "2026-09-26T10:00:00Z"
        self.registry.record_worker_capacity_observations("claude", (
            claude_provider_signal("claude", observed_at=prior_at, succeeded=True),
        ), recorded_at=prior_at)
        before = self.registry.dispatch_snapshot(observed_at="2026-09-26T10:05:00Z")
        before_claude = next(item for item in before.workers if item["id"] == "claude")
        before_leases = before.active_leases
        fixture_at = "2026-09-26T10:02:00.000000Z"
        control = RunnerRegistryControl(self.database)
        config = {"capacity_collectors": {}, "claude_health_probe": {
            "worker_id": "claude", "command": ["fake-claude"], "cadence_seconds": 60,
        }}
        with patch("registry_control.utc_now", return_value="2026-09-26T10:03:00Z"), \
                patch("registry_control.probe_claude_health", return_value={
                    "succeeded": True, "limit_signal": None, "returncode": 0,
                    "observed_at": fixture_at,
                }) as probe:
            collected = control.refresh_configured_capacity(config)
        probe.assert_called_once_with(["fake-claude"], timeout=20)
        self.assertEqual(collected[0]["observations"][0]["observed_at"], fixture_at)
        after = self.registry.dispatch_snapshot(observed_at="2026-09-26T10:03:00Z")
        signals = [item for item in after.usage_observations if item["worker_id"] == "claude"]
        self.assertEqual(
            {item["observed_at"] for item in signals},
            {"2026-09-26T10:00:00.000000Z", fixture_at},
        )
        self.assertEqual(
            next(item for item in after.workers if item["id"] == "claude"), before_claude,
        )
        self.assertEqual(after.active_leases, before_leases)

    def test_implementation_completion_and_review_input_are_atomic(self):
        self.seed_assignment()
        self.registry.register_work_package(WorkPackage(
            "REVIEW-1", "FEATURE", "Review", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 10, ("review",), kind=PackageKind.REVIEW,
            dependency_ids=("TASK-1",), status=TaskStatus.READY,
        ))
        control = RunnerRegistryControl(self.database)
        revision = control.pre_claim()
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt("attempt-atomic", package_id="TASK-1", worker_id="worker-a", expected_revision=revision)
        completed_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        contract = {"task": "TASK-1", "instructions": "résumé"}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        review_input = ReviewInput(
            id="review-input-atomic", review_package_id="REVIEW-1", target_package_id="TASK-1",
            implementation_attempt_id="attempt-atomic", implementation_commit="a" * 40,
            base_commit="b" * 40, pr_url="https://example.test/pr/1", contract_sha256=digest,
            contract=contract, validation_evidence={"focused": "passed"}, recorded_at=completed_at,
        )
        control.succeed("attempt-atomic", review_inputs=(review_input,), ended_at=completed_at)
        self.assertEqual(self.registry.review_input("REVIEW-1")["id"], "review-input-atomic")
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute("SELECT status FROM work_packages WHERE id='TASK-1'").fetchone()[0], "VERIFY_REVIEW")
            runtime_seconds = connection.execute(
                "SELECT runtime_seconds FROM work_packages WHERE id='TASK-1'"
            ).fetchone()[0]
        self.assertGreater(runtime_seconds, 0)
        self.assertLess(runtime_seconds, 2)

    def test_review_inputs_require_successful_verify_completion_at_the_completion_timestamp(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        revision = control.pre_claim()
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt("attempt-invalid", package_id="TASK-1", worker_id="worker-a", expected_revision=revision)
        ended_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        contract = {"task": "TASK-1"}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        review_input = ReviewInput(
            id="review-input-invalid", review_package_id="REVIEW-1", target_package_id="TASK-1",
            implementation_attempt_id="attempt-invalid", implementation_commit="a" * 40,
            base_commit="b" * 40, pr_url="https://example.test/pr/1", contract_sha256=digest,
            contract=contract, validation_evidence={"focused": "passed"}, recorded_at=ended_at,
        )
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_COMPLETION_INVALID"):
            self.registry.finish_attempt_runtime(
                "attempt-invalid", ended_at=ended_at, outcome="FAILED", next_status=TaskStatus.BLOCKED,
                reason="failure", review_inputs=(review_input,),
            )
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute("SELECT status FROM work_packages WHERE id='TASK-1'").fetchone()[0], "ACTIVE")
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_TIMESTAMP_MISMATCH"):
            control.succeed(
                "attempt-invalid", review_inputs=(ReviewInput(
                    **{**review_input.__dict__, "recorded_at": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()}
                ),), ended_at=ended_at,
            )

    def test_lease_revocation_stops_renewal_and_recovery_closes_runtime(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker("worker-a", "Worker A", ("registry",), (Lane.PLATFORM,))
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1", "FEATURE", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 10, ("verified",), status=TaskStatus.READY,
            )
        )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=now.isoformat(), reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK-1", "worker-a", acquired_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1", package_id="TASK-1", worker_id="worker-a",
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        control.renew_runtime("attempt-1", lease.id, lease_seconds=300)
        control.record_process("attempt-1", pid=901, pgid=901)

        revoked_at = datetime.now(timezone.utc)
        self.registry.release_lease(
            lease.id, released_at=revoked_at.isoformat(),
            reason="operator revoked lease", next_status=TaskStatus.BLOCKED,
        )
        with self.assertRaisesRegex(RegistryConflict, "LEASE_REVOKED"):
            control.renew_runtime("attempt-1", lease.id, lease_seconds=300)
        control.fail("attempt-1", "runtime monitor observed lease revocation")

        with self.registry._connection() as connection:
            runtime = connection.execute(
                """SELECT released_at FROM attempt_runtime_ownership
                   WHERE attempt_id='attempt-1'"""
            ).fetchone()
            attempt = connection.execute(
                "SELECT ended_at, outcome FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            failures = connection.execute(
                """SELECT code FROM failure_observations
                   WHERE attempt_id='attempt-1' ORDER BY observed_at"""
            ).fetchall()
        self.assertIsNotNone(runtime["released_at"])
        self.assertIsNotNone(attempt["ended_at"])
        self.assertEqual(attempt["outcome"], "FAILED")
        self.assertIn("RUNTIME_RECOVERY", [row["code"] for row in failures])

    def test_real_provider_is_stopped_when_registry_lease_expires(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker("worker-a", "Worker A", ("registry",), (Lane.PLATFORM,))
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1", "FEATURE", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 10, ("verified",), status=TaskStatus.READY,
            )
        )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=now.isoformat(), reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK-1", "worker-a",
            acquired_at=(now - timedelta(seconds=10)).isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1", package_id="TASK-1", worker_id="worker-a",
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        lifecycle = RegistryAttemptLifecycle(control, "attempt-1")

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            started, completed = root / "started", root / "completed"
            command = [
                sys.executable, "-c",
                (
                    "from pathlib import Path; import time; "
                    f"Path({str(started)!r}).write_text('started'); "
                    "time.sleep(5); "
                    f"Path({str(completed)!r}).write_text('completed')"
                ),
            ]

            def bind_then_expire(pid):
                control.record_process("attempt-1", pid=pid, pgid=pid)
                expired_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat()
                with self.registry._connection() as connection:
                    connection.execute(
                        "UPDATE leases SET expires_at=? WHERE id=?",
                        (expired_at, lease.id),
                    )

            def monitor_registry():
                if started.exists():
                    control.renew_runtime("attempt-1", lease.id, lease_seconds=300)

            with self.assertRaisesRegex(RuntimeError, "LEASE_EXPIRED"):
                run(
                    command, launch_barrier=True, on_start=bind_then_expire,
                    monitor=monitor_registry, monitor_interval=0.1, timeout=10,
                )
            lifecycle.fail("runtime monitor observed lease expiry")
            self.assertTrue(started.exists())
            self.assertFalse(completed.exists())

        self.assertEqual(self.registry.active_attempt_runtimes(), ())
        with self.registry._connection() as connection:
            attempt = connection.execute(
                "SELECT outcome, ended_at FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            released = connection.execute(
                "SELECT released_at FROM leases WHERE id=?", (lease.id,)
            ).fetchone()[0]
        self.assertEqual(attempt["outcome"], "FAILED")
        self.assertIsNotNone(attempt["ended_at"])
        self.assertIsNotNone(released)

    def test_worker_disappearance_globally_stops_and_reconciles_all_runtimes(self):
        now = datetime.now(timezone.utc)
        self.registry.register_feature(
            Feature("FEATURE", "Feature", 10, TaskStatus.READY)
        )
        for suffix in ("a", "b", "c"):
            worker_id = f"worker-{suffix}"
            package_id = f"TASK-{suffix.upper()}"
            self.registry.register_worker(
                Worker(worker_id, worker_id, ("registry",), (Lane.PLATFORM,))
            )
            self.registry.register_work_package(
                WorkPackage(
                    package_id, "FEATURE", package_id, "ORCHESTRATION",
                    Lane.PLATFORM, ("registry",), 10, ("verified",),
                    status=TaskStatus.READY,
                )
            )
        current = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=current["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=now.isoformat(), reason="bounded canary",
        )
        for index, suffix in enumerate(("a", "b"), start=1):
            worker_id = f"worker-{suffix}"
            package_id = f"TASK-{suffix.upper()}"
            self.registry.acquire_lease(
                package_id, worker_id, acquired_at=now.isoformat(),
                expires_at=(now + timedelta(minutes=5)).isoformat(),
            )
            self.registry.begin_attempt_runtime(
                f"attempt-{suffix}", package_id=package_id, worker_id=worker_id,
                runner_pid=800 + index, started_at=now.isoformat(),
                expected_revision=self.registry.dispatch_control()["revision"],
            )
            if suffix == "a":
                self.registry.record_attempt_process(
                    f"attempt-{suffix}", agent_pid=900 + index,
                    agent_pgid=900 + index, recorded_at=now.isoformat(),
                )
        lease_only = self.registry.acquire_lease(
            "TASK-C", "worker-c", acquired_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )

        terminated = []
        control = RunnerRegistryControl(self.database)
        result = control.handle_worker_disappearance(
            "worker-a", terminate=terminated.append
        )
        self.assertEqual(result["unresolved"], ())
        self.assertEqual(terminated, [901])
        self.assertIn(f"lease:{lease_only.id}", result["resolved"])
        state = self.registry.dispatch_control()
        self.assertEqual(state["dispatch_mode"], "PAUSED")
        self.assertTrue(state["kill_switch_engaged"])
        self.assertEqual(self.registry.active_attempt_runtimes(), ())
        with self.registry._connection() as connection:
            workers = dict(connection.execute(
                "SELECT id, availability FROM workers ORDER BY id"
            ).fetchall())
            packages = dict(connection.execute(
                "SELECT id, status FROM work_packages ORDER BY id"
            ).fetchall())
            attempts = connection.execute(
                "SELECT outcome FROM attempts ORDER BY id"
            ).fetchall()
        self.assertEqual(workers, {
            "worker-a": "OFFLINE", "worker-b": "IDLE", "worker-c": "IDLE",
        })
        self.assertEqual(packages, {
            "TASK-A": "BLOCKED", "TASK-B": "BLOCKED", "TASK-C": "BLOCKED",
        })
        self.assertEqual([row["outcome"] for row in attempts], ["FAILED", "FAILED"])
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            control.pre_claim()
        repeated = control.handle_worker_disappearance(
            "worker-a", terminate=terminated.append
        )
        self.assertEqual(repeated, {"resolved": (), "unresolved": ()})
        self.assertEqual(terminated, [901])
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_unresolved_stop_keeps_stopping_and_records_deterministic_evidence(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1", package_id="TASK-1", worker_id="worker-a",
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        control.record_process("attempt-1", pid=901, pgid=901)
        control.engage_stop("operator pause")

        def cannot_terminate(_pgid):
            raise RuntimeError("simulated surviving process")

        result = control.reconcile_stopping_runtimes(terminate=cannot_terminate)
        self.assertEqual(result["resolved"], ())
        self.assertEqual(result["unresolved"], ("attempt-1",))
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "STOPPING")
        self.assertEqual(
            [item["attempt_id"] for item in self.registry.active_attempt_runtimes()],
            ["attempt-1"],
        )
        with self.registry._connection() as connection:
            failures = connection.execute(
                """SELECT id, code, detail FROM failure_observations
                   WHERE attempt_id='attempt-1'"""
            ).fetchall()
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["code"], "RUNTIME_RECOVERY_FAILED")
        self.assertIn("simulated surviving process", failures[0]["detail"])

    def test_process_record_fails_after_kill_switch(self):
        self.seed_assignment()
        control = RunnerRegistryControl(self.database)
        with patch("registry_control.os.getpid", return_value=900):
            control.reserve_attempt(
                "attempt-1",
                package_id="TASK-1",
                worker_id="worker-a",
                expected_revision=control.pre_claim(),
            )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:00Z", reason="operator stop"
        )
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            control.record_process("attempt-1", pid=901, pgid=901)


if __name__ == "__main__":
    unittest.main()
