from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from scripts.factory_registry.delivery_plan import FeatureBrief, build_packages, validate_plan
from scripts.factory_registry.delivery_integration import ApprovalBinding, IntegrationPolicy, prepare_integration, publish_integration
from scripts.factory_registry.models import Evidence, Lane, ReviewInput, ReviewOutcome, ReviewOutcomeState, TaskStatus, Worker
from scripts.factory_registry.repository import RegistryConflict, RegistryNotFound
from scripts.factory_registry.sqlite_registry import SQLiteRegistry


class DeliveryRegistryTests(unittest.TestCase):
    """Use real SQLite transactions and Git-derived v2 package contracts."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repo"
        self.repository.mkdir()
        self.git("init", "-b", "codex/delivery")
        self.git("config", "user.name", "Factory tests")
        self.git("config", "user.email", "tests@example.invalid")
        (self.repository / "docs").mkdir()
        (self.repository / "src").mkdir()
        (self.repository / "docs/PLAN.md").write_text("Implement one visible behavior, preserving user content.\n")
        (self.repository / "src/App.tsx").write_text("export const App = () => null\n")
        self.git("add", ".")
        self.git("commit", "-m", "planning base")
        self.base = self.git("rev-parse", "HEAD")
        self.database = self.root / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.registry.register_worker(Worker("orchestra", "Coordinator", ("coordination",),
                                             (Lane.FEATURE,), role="ORCHESTRA"))
        self.now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repository, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def stamp(self, seconds=0):
        return (self.now + timedelta(seconds=seconds)).isoformat()

    def revision(self):
        return self.registry.dispatch_control()["revision"]

    def test_preparation_heartbeat_is_narrow_auditable_and_retry_safe(self):
        self.submit()
        self.authorize()
        before = self.registry.dispatch_snapshot(observed_at=self.stamp())
        revision = self.revision()
        result = self.registry.record_delivery_preparation_heartbeat('run-1', 'orchestra',
            expected_revision=revision, recorded_at=self.stamp(1))
        self.assertEqual(result['revision'], revision + 1)
        self.assertEqual(self.registry.record_delivery_preparation_heartbeat('run-1', 'orchestra',
            expected_revision=revision, recorded_at=self.stamp(1)), result)
        after = self.registry.dispatch_snapshot(observed_at=self.stamp(2))
        self.assertEqual(before.active_leases, after.active_leases)
        self.assertEqual(before.work_packages, after.work_packages)
        self.assertEqual(before.usage_observations, after.usage_observations)
        for old, new in zip(before.workers, after.workers):
            self.assertEqual({k: v for k, v in old.items() if k not in {'last_heartbeat_at', 'updated_at'}},
                             {k: v for k, v in new.items() if k not in {'last_heartbeat_at', 'updated_at'}})
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM task_events WHERE event_type='DELIVERY_PREPARATION_HEARTBEAT'").fetchone()[0], 1)
        with self.assertRaisesRegex(RegistryConflict, 'INVALID_HEARTBEAT_CHRONOLOGY'):
            self.registry.record_delivery_preparation_heartbeat('run-1', 'orchestra',
                expected_revision=self.revision(), recorded_at=self.stamp())
        with self.assertRaisesRegex(RegistryConflict, 'DISPATCH_PAUSED'):
            self.registry.record_worker_heartbeat('orchestra', observed_at=self.stamp(2))

    def test_preparation_heartbeat_rejects_invalid_authority_without_mutation(self):
        scenarios = ('missing', 'wrong-worker', 'expired', 'superseded', 'stopped',
                     'stopping', 'live', 'kill-off', 'not-orchestra', 'busy', 'stale-revision',
                     'same-bounded-run')
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                fixture = DeliveryRegistryTests()
                fixture.setUp()
                try:
                    fixture.submit()
                    fixture.authorize()
                    worker, run, stamp = 'orchestra', 'run-1', fixture.stamp(1)
                    if scenario == 'missing':
                        run = 'absent'
                    elif scenario == 'wrong-worker':
                        worker = 'codex-a'
                    elif scenario == 'expired':
                        stamp = fixture.stamp(3600)
                    elif scenario == 'superseded':
                        fixture.authorize(run_id='run-2')
                    else:
                        # Simulate malformed/recovered control states only in this
                        # disposable test database; production uses operator APIs.
                        with fixture.registry._connection() as connection:
                            if scenario == 'stopped':
                                connection.execute("INSERT INTO registry_metadata VALUES (?,?)",
                                    ('delivery:run-state:run-1', json.dumps({'schema_version': 1, 'state': 'STOPPED'})))
                            elif scenario in {'stopping', 'live'}:
                                connection.execute('UPDATE factory_control SET dispatch_mode=?', (scenario.upper(),))
                            elif scenario == 'kill-off':
                                connection.execute('UPDATE factory_control SET kill_switch_engaged=0')
                            elif scenario == 'not-orchestra':
                                connection.execute("UPDATE workers SET role='WORKER' WHERE id='orchestra'")
                            elif scenario == 'busy':
                                connection.execute("UPDATE workers SET availability='BUSY' WHERE id='orchestra'")
                            elif scenario == 'same-bounded-run':
                                connection.execute("INSERT INTO registry_metadata VALUES (?,?)",
                                    ('bounded_run_scope', json.dumps({'run_id': 'run-1', 'package_ids': ['TASK-1'],
                                        'deadline': fixture.stamp(3600), 'base_ref': 'codex/delivery', 'parent_limit': 2})))
                            connection.commit()
                    revision = fixture.revision()
                    before = fixture.registry.dispatch_snapshot(observed_at=stamp).workers
                    with self.assertRaises(RegistryConflict):
                        fixture.registry.record_delivery_preparation_heartbeat(run, worker,
                            expected_revision=revision - (scenario == 'stale-revision'), recorded_at=stamp)
                    self.assertEqual(fixture.revision(), revision)
                    self.assertEqual(fixture.registry.dispatch_snapshot(observed_at=stamp).workers, before)
                finally:
                    fixture.doCleanups()

    def test_preparation_heartbeat_rejects_active_ownership(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        self.registry.register_worker(Worker('builder', 'Builder', ('implementation',), (Lane.FEATURE,)))
        self.start()
        self.registry.acquire_lease('TASK-1', 'builder', acquired_at=self.stamp(11), expires_at=self.stamp(300))
        self.registry.begin_attempt_runtime('active-attempt', package_id='TASK-1', worker_id='builder',
            runner_pid=12345, started_at=self.stamp(12), expected_revision=self.revision())
        with self.registry._connection() as connection:
            connection.execute("UPDATE factory_control SET dispatch_mode='PAUSED', kill_switch_engaged=1")
            connection.execute("DELETE FROM registry_metadata WHERE key IN ('delivery:run-state:run-1','bounded_run_scope')")
            connection.commit()
        # Test each remaining ownership class, including partially reconciled
        # malformed recovery states, without treating release as completion.
        for release in ('none', 'lease', 'attempt'):
            with self.subTest(released=release):
                with self.registry._connection() as connection:
                    if release == 'lease':
                        connection.execute('UPDATE leases SET released_at=?', (self.stamp(13),))
                    elif release == 'attempt':
                        connection.execute('UPDATE attempts SET ended_at=?', (self.stamp(13),))
                    connection.commit()
                revision = self.revision()
                with self.assertRaisesRegex(RegistryConflict, 'ACTIVE_OWNERSHIP_PRESENT'):
                    self.registry.record_delivery_preparation_heartbeat('run-1', 'orchestra',
                        expected_revision=revision, recorded_at=self.stamp(14))
                self.assertEqual(self.revision(), revision)

    def brief(self, feature_id="FEATURE-1", dependencies=()):
        return FeatureBrief.from_dict({
            "id": feature_id, "title": "User feature " + feature_id,
            "user_experience": "I press the button and see my saved thought.",
            "acceptance_criteria": ["Pressing the button displays the thought."],
            "dependency_feature_ids": list(dependencies),
        })

    def submit(self, brief=None):
        brief = brief or self.brief()
        return self.registry.submit_delivery_request(brief.as_dict(), expected_revision=self.revision(),
                                                     recorded_at=self.stamp())

    def authorize(self, features=("FEATURE-1",), run_id="run-1", max_generations=3, seconds=0):
        spec = {"run_id": run_id, "feature_ids": list(features), "deadline": self.stamp(3600),
                "base_ref": "codex/delivery", "parent_limit": 2, "max_generations": max_generations,
                "coordinator_worker_id": "orchestra"}
        return self.registry.authorize_delivery_run(spec, expected_revision=self.revision(),
                                                    recorded_at=self.stamp(seconds))

    def plan_and_pair(self, brief=None, *, implementation_issue=1, dependencies=None,
                      run_id="run-1", action_id="plan-1", alternate_behavior=False, seconds=1, generation=0):
        brief = brief or self.brief()
        module = "childDisplay" if brief.id == "FEATURE-2" else "thoughtDisplay"
        payload = {
            "state": "PREPARED", "feature_id": brief.id, "base_commit": self.base,
            "user_experience": brief.user_experience,
            "dependency_feature_ids": list(brief.dependency_feature_ids), "decisions_needed": [],
            "package": {
                "behavior": "Display saved thought" if not alternate_behavior else "Different implementation guidance",
                "module_boundary": "Thought display module", "public_interface": ["ThoughtDisplay renders thought"],
                "persistence_owner": "none",
                "end_to_end": {"entry_point": "Review", "user_action": "Press thought button",
                               "observable_result": "Saved thought is visible"},
                "acceptance_criteria": ["Pressing the button displays the thought."],
                "out_of_scope": ["Calendar changes"], "instructions": "Build and wire the bounded module.",
                "required_capabilities": ["implementation"], "capacity_size": "SMALL", "capacity_risk": "BOUNDED",
                "planning_paths": ["docs/PLAN.md"], "existing_paths": ["src/App.tsx"],
                "new_paths": [f"src/{module}.tsx", f"src/{module}.test.tsx"],
                "integration_paths": ["src/App.tsx"], "test_paths": [f"src/{module}.test.tsx"],
            },
        }
        plan = validate_plan(payload, brief=brief, repository=self.repository, target_ref="codex/delivery")
        pair = build_packages(plan, repository=self.repository, target_ref="codex/delivery",
                              implementation_issue=implementation_issue, review_issue=implementation_issue + 1,
                              dependency_packages=dependencies)
        if action_id:
            self.registry.reserve_delivery_action(run_id, brief.id, action_id, "PLAN",
                {"base_commit": self.base, "generation": generation},
                owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(seconds))
            self.registry.update_delivery_action(action_id, owner="orchestra", state="SUCCEEDED",
                result={"plan": plan.as_dict()}, expected_revision=self.revision(), recorded_at=self.stamp(seconds + 4))
        return plan, pair

    def register(self, pair, *, feature="FEATURE-1", generation=0, run="run-1", action="plan-1",
                 previous_review=None, seconds=6):
        return self.registry.register_delivery_pair(run, feature, generation, pair.implementation, pair.review,
            plan_action_id=action, previous_review_id=previous_review,
            expected_revision=self.revision(), recorded_at=self.stamp(seconds))

    def start(self, package_id="TASK-1", run="run-1", *, package_ids=None, seconds=10):
        registered = self.registry.delivery_snapshot(run_id=run)["features"]
        if package_ids is None:
            package_ids = sorted(identifier for feature in registered if feature["pair"]
                                 for identifier in (feature["pair"]["implementation_id"], feature["pair"]["review_id"]))
        return self.registry.set_dispatch_control(expected_revision=self.revision(), expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=self.stamp(seconds), reason="test bounded run",
            bounded_run={"run_id": run, "package_ids": package_ids, "deadline": self.stamp(3600),
                         "base_ref": "codex/delivery", "parent_limit": 2})

    def stop(self, seconds=50):
        self.registry.set_dispatch_control(expected_revision=self.revision(), expected_mode="LIVE",
            new_mode="STOPPING", kill_switch_engaged=True, changed_at=self.stamp(seconds), reason="owner stop")
        self.registry.set_dispatch_control(expected_revision=self.revision(), expected_mode="STOPPING",
            new_mode="PAUSED", kill_switch_engaged=True, changed_at=self.stamp(seconds + 1), reason="drained")

    def finish_implementation(self, pair):
        self.registry.register_worker(Worker("builder", "Builder", ("implementation",), (Lane.FEATURE,)))
        self.registry.register_worker(Worker("reviewer", "Reviewer", ("independent-review",), (Lane.ASSURANCE,)))
        self.start()
        self.registry.acquire_lease("TASK-1", "builder", acquired_at=self.stamp(11), expires_at=self.stamp(300))
        self.registry.begin_attempt_runtime("implementation-attempt", package_id="TASK-1", worker_id="builder",
            runner_pid=12345, started_at=self.stamp(12), expected_revision=self.revision())
        self.git("checkout", "-b", "codex/implementation")
        (self.repository / "src/thoughtDisplay.tsx").write_text("export const thought = 'saved thought'\n")
        (self.repository / "src/thoughtDisplay.test.tsx").write_text("// Fixture implementation validation\n")
        self.git("add", ".")
        self.git("commit", "-m", "implemented thought display")
        implementation = self.git("rev-parse", "HEAD")
        packet = self.root / "review-packet"
        packet.mkdir()
        contents = {
            "base-to-implementation.diff": self.git("diff", self.base, implementation).encode(),
            "changed-files.txt": self.git("diff", "--name-only", self.base, implementation).encode(),
            "contract.json": json.dumps(pair.implementation_contract, sort_keys=True).encode(),
            "validation-evidence.json": b'{"fixture_validation":"passed"}',
        }
        hashes = {}
        for name, content in contents.items():
            (packet / name).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        manifest = {"schema_version": 1, "implementation_attempt_id": "implementation-attempt",
                    "implementation_commit": implementation, "base_commit": self.base, "files": hashes}
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        (packet / "manifest.json").write_bytes(manifest_bytes)
        review_input = ReviewInput(id="review-input-1", review_package_id="TASK-2", target_package_id="TASK-1",
            implementation_attempt_id="implementation-attempt", implementation_commit=implementation,
            base_commit=self.base, pr_url="https://github.com/example/app/pull/1",
            contract_sha256=pair.implementation.provider_diagnostics["queue_contract_sha256"],
            contract=pair.implementation_contract,
            validation_evidence={"review_packet": {"path": str(packet), "files": hashes,
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}}, recorded_at=self.stamp(20))
        self.registry.finish_attempt_runtime("implementation-attempt", ended_at=self.stamp(20),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="fixture implementation done",
            review_inputs=(review_input,))
        ci = {"state": "SUCCESS", "implementation_commit": implementation, "pr_url": review_input.pr_url,
              "run_url": "https://github.com/example/app/actions/runs/123"}
        return review_input, ci

    def finish_review(self, review_input, *, verdict=ReviewOutcomeState.APPROVED):
        self.registry.acquire_lease("TASK-2", "reviewer", acquired_at=self.stamp(31), expires_at=self.stamp(300))
        self.registry.begin_attempt_runtime("review-attempt", package_id="TASK-2", worker_id="reviewer",
            runner_pid=12346, started_at=self.stamp(32), expected_revision=self.revision())
        self.registry.finish_attempt_runtime("review-attempt", ended_at=self.stamp(40), outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW, reason="fixture independent review done")
        outcome = ReviewOutcome(id="verdict-1", review_package_id="TASK-2", target_package_id="TASK-1",
            implementer_worker_id="builder", reviewer_worker_id="reviewer", requested_at=self.stamp(20),
            decided_at=self.stamp(42), state=verdict, findings=("Exact artifact reviewed",),
            changes_requested=("Wire the missing button",) if verdict is ReviewOutcomeState.CHANGES_REQUESTED else (),
            approval_evidence_ids=("verdict-evidence",), reviewed_commit=review_input.implementation_commit,
            reviewed_base_commit=review_input.base_commit, contract_sha256=review_input.contract_sha256,
            review_input_evidence_id=review_input.id, reviewer_attempt_id="review-attempt")
        evidence = Evidence("verdict-evidence", "TASK-2", "review", review_input.pr_url, "Structured fixture verdict",
            self.stamp(41), {"attempt_id": "review-attempt", "reviewed_commit": review_input.implementation_commit,
                            "reviewed_base_commit": review_input.base_commit,
                            "contract_sha256": review_input.contract_sha256, "review_input_evidence_id": review_input.id})
        self.registry.record_review_outcome(outcome, evidence=evidence, expected_revision=self.revision())

    def publish_candidate(self):
        """Persist candidate and really push it, leaving Registry recording undone."""
        remote = self.root / "remote.git"
        self.git("init", "--bare", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "origin", "codex/delivery")
        self.registry.reserve_delivery_action("run-1", "FEATURE-1", "integrate-1", "INTEGRATE", {},
            owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(44))
        approval = ApprovalBinding(**self.registry.delivery_approval("FEATURE-1"))
        policy = IntegrationPolicy(remote="origin", target_branch="codex/delivery",
            validation_commands=((sys.executable, "-c", "from pathlib import Path; "
                                  "assert Path('src/thoughtDisplay.tsx').read_text().startswith('export const thought')"),))
        candidate = prepare_integration(self.repository, approval, policy, expected_target_sha=self.base,
                                        integration_id="integrate-1", workspace_parent=self.root)
        self.registry.update_delivery_action("integrate-1", owner="orchestra", state="RUNNING",
            result={"candidate": candidate}, expected_revision=self.revision(), recorded_at=self.stamp(45))
        publication = publish_integration(self.repository, candidate, approval, policy)
        return candidate, publication, approval, policy

    def advance_target(self):
        self.git("checkout", "codex/delivery")
        (self.repository / "docs/UNRELATED.md").write_text("A separately integrated change.\n")
        self.git("add", ".")
        self.git("commit", "-m", "advance integration target")
        return self.git("rev-parse", "HEAD")

    def test_exact_submission_replays_without_revision_or_history_duplication(self):
        before = self.revision()
        first = self.submit()
        after = self.revision()
        replay = self.registry.submit_delivery_request(self.brief().as_dict(), expected_revision=before,
                                                       recorded_at=self.stamp(20))
        self.assertEqual(first, replay)
        self.assertEqual(self.revision(), after)
        self.assertEqual(len(self.registry.delivery_snapshot()["features"]), 1)
        changed = {**self.brief().as_dict(), "user_experience": "A different product request"}
        with self.assertRaises(RegistryConflict):
            self.registry.submit_delivery_request(changed, expected_revision=after, recorded_at=self.stamp(20))
        self.assertEqual(self.revision(), after)
        self.assertEqual(self.registry.delivery_snapshot()["features"][0]["brief"], self.brief().as_dict())

    def test_authorization_rejects_cycles_and_missing_dependencies_atomically(self):
        self.submit(self.brief("FEATURE-A", ("FEATURE-B",)))
        self.submit(self.brief("FEATURE-B", ("FEATURE-A",)))
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_DEPENDENCY_CYCLE"):
            self.authorize(("FEATURE-A", "FEATURE-B"))
        self.assertEqual(self.revision(), before)
        self.submit(self.brief("FEATURE-C", ("FEATURE-MISSING",)))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_DEPENDENCY_NOT_AUTHORIZED"):
            self.authorize(("FEATURE-C",), run_id="run-2")
        with self.assertRaises(RegistryNotFound):
            self.authorize(("FEATURE-UNKNOWN",), run_id="run-3")
        self.assertFalse([key for key in self.registry.delivery_snapshot()["records"] if key.startswith("authorization:")])

    def test_pair_registration_has_one_ready_implementation_and_waiting_review(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        result = self.register(pair)
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(7))
        packages = {row["id"]: row for row in snapshot.work_packages}
        self.assertEqual(packages["TASK-1"]["status"], "READY")
        self.assertEqual(packages["TASK-2"]["status"], "ON_DECK")
        self.assertEqual(packages["TASK-1"]["source_ref"], "1")
        self.assertEqual(result["review_id"], "TASK-2")
        before = self.revision()
        self.assertEqual(self.register(pair), result)
        self.assertEqual(self.revision(), before)
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][0]["next_action"], "WAIT_IMPLEMENTATION")

    def test_authorization_is_forbidden_while_live(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        self.start()
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_AUTHORIZATION_REQUIRES_PAUSED"):
            self.authorize(run_id="run-2")
        self.assertEqual(self.revision(), before)

    def test_stopping_expired_and_finished_run_pair_registration_fail_closed(self):
        self.submit()
        self.submit(self.brief("FEATURE-2"))
        self.authorize(("FEATURE-1", "FEATURE-2"))
        _, first = self.plan_and_pair()
        self.register(first)
        _, second = self.plan_and_pair(self.brief("FEATURE-2"), implementation_issue=3, action_id="plan-2")
        self.start()
        with self.assertRaisesRegex(RegistryConflict, "RUN_DEADLINE_REACHED"):
            self.register(second, feature="FEATURE-2", action="plan-2", seconds=3600)
        self.registry.set_dispatch_control(expected_revision=self.revision(), expected_mode="LIVE",
            new_mode="STOPPING", kill_switch_engaged=True, changed_at=self.stamp(30), reason="owner stop")
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            self.register(second, feature="FEATURE-2", action="plan-2", seconds=31)
        self.registry.set_dispatch_control(expected_revision=self.revision(), expected_mode="STOPPING",
            new_mode="PAUSED", kill_switch_engaged=True, changed_at=self.stamp(32), reason="drained")
        with self.assertRaises(RegistryConflict):
            self.register(second, feature="FEATURE-2", action="plan-2", seconds=33)
        self.assertEqual(len(self.registry.control_center_snapshot(observed_at=self.stamp(32)).work_packages), 2)

    def test_new_authorization_invalidates_prior_run_even_during_paused_bootstrap(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.authorize(run_id="run-2")
        before = self.revision()
        with self.assertRaises(RegistryConflict):
            self.register(pair)
        with self.assertRaises(RegistryConflict):
            self.registry.reserve_delivery_action("run-1", "FEATURE-1", "plan-old", "PLAN", {},
                owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(7))
        self.assertEqual(self.revision(), before)

    def test_sparse_contracts_do_not_consume_generation_or_create_packages(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        bad = replace(pair, implementation=replace(pair.implementation, provider_diagnostics={}))
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_(V2_SOURCE_REQUIRED|PLAN_BINDING_MISMATCH)"):
            self.register(bad)
        self.assertEqual(self.revision(), before)
        self.assertIsNone(self.registry.delivery_snapshot()["features"][0]["pair"])
        self.assertFalse(self.registry.control_center_snapshot(observed_at=self.stamp(7)).work_packages)

    def test_generation_budget_and_missing_rejection_cannot_be_bypassed(self):
        self.submit()
        self.authorize(max_generations=2)
        _, first = self.plan_and_pair()
        self.register(first)
        _, second = self.plan_and_pair(implementation_issue=3, action_id="plan-2", generation=1)
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_GENERATION_BUDGET_EXHAUSTED"):
            self.register(second, generation=2, action="plan-2", previous_review="TASK-2")
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_CORRECTION_REQUIRES_REJECTION"):
            self.register(second, generation=1, action="plan-2", previous_review="TASK-2")
        self.assertEqual(self.revision(), before)

    def test_two_coordinators_reserve_only_one_action_transactionally(self):
        self.submit()
        self.authorize()
        barrier = threading.Barrier(2)
        revision = self.revision()
        def reserve(index):
            adapter = SQLiteRegistry(self.database)
            barrier.wait(timeout=5)
            try:
                return adapter.reserve_delivery_action("run-1", "FEATURE-1", f"plan-{index}", "PLAN", {},
                    owner=f"coordinator-{index}", expected_revision=revision, recorded_at=self.stamp(1))
            except RegistryConflict as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (1, 2)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertTrue(any("REGISTRY_REVISION_CHANGED" in result for result in results if isinstance(result, str)))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTION_UNRESOLVED"):
            self.registry.reserve_delivery_action("run-1", "FEATURE-1", "plan-third", "PLAN", {},
                owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(2))
        actions = [record for key, record in self.registry.delivery_snapshot()["records"].items() if key.startswith("action:")]
        self.assertEqual(len(actions), 1)

    def test_uncertain_action_blocks_retry_until_reconciled_and_records_runtime(self):
        self.submit()
        self.authorize()
        self.registry.reserve_delivery_action("run-1", "FEATURE-1", "plan-1", "PLAN", {},
            owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(1))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTION_OWNER_MISMATCH"):
            self.registry.update_delivery_action("plan-1", owner="other", state="SUCCEEDED", result={},
                expected_revision=self.revision(), recorded_at=self.stamp(2))
        self.registry.update_delivery_action("plan-1", owner="orchestra", state="UNCERTAIN",
            result={"provider_session": "session-1"}, expected_revision=self.revision(), recorded_at=self.stamp(3))
        row = self.registry.delivery_snapshot()["features"][0]
        self.assertEqual((row["next_action"], row["reason"]), ("RECONCILE_ACTION", "plan-1"))
        self.assertIsNone(row["unresolved_actions"][0]["runtime_seconds"])
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTION_UNRESOLVED"):
            self.registry.reserve_delivery_action("run-1", "FEATURE-1", "plan-2", "PLAN", {},
                owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(4))
        result = self.registry.update_delivery_action("plan-1", owner="orchestra", state="FAILED",
            result={"provider_confirmed_stopped": True}, expected_revision=self.revision(), recorded_at=self.stamp(11))
        before = self.revision()
        self.assertEqual(self.registry.update_delivery_action("plan-1", owner="orchestra", state="FAILED",
            result={"provider_confirmed_stopped": True}, expected_revision=before - 1, recorded_at=self.stamp(12)), result)
        self.assertEqual(self.revision(), before)
        self.assertEqual(self.registry.delivery_snapshot()["records"]["action:plan-1"]["runtime_seconds"], 10)
        self.registry.reserve_delivery_action("run-1", "FEATURE-1", "plan-2", "PLAN", {},
            owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(12))

    def test_done_package_does_not_unlock_dependency_without_integration(self):
        first, second = self.brief(), self.brief("FEATURE-2", ("FEATURE-1",))
        self.submit(first)
        self.submit(second)
        self.authorize(("FEATURE-1", "FEATURE-2"))
        _, parent = self.plan_and_pair(action_id=None)
        # A historical DONE implementation is deliberately insufficient evidence.
        self.registry.register_work_package(replace(parent.implementation, status=TaskStatus.DONE))
        self.registry.register_work_package(replace(parent.review, status=TaskStatus.DONE))
        _, child = self.plan_and_pair(second, implementation_issue=3, dependencies={"FEATURE-1": "TASK-1"},
                                      action_id="plan-child")
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_DEPENDENCY_NOT_INTEGRATED"):
            self.register(child, feature="FEATURE-2", action="plan-child")
        row = next(row for row in self.registry.delivery_snapshot()["features"] if row["feature_id"] == "FEATURE-2")
        self.assertEqual(row["next_action"], "WAIT_DEPENDENCIES")
        self.assertEqual(row["reason"], "FEATURE-1")

    def test_registration_rejects_another_valid_plan_substituted_after_planning(self):
        self.submit()
        self.authorize()
        self.plan_and_pair()
        _, substituted = self.plan_and_pair(action_id=None, alternate_behavior=True)
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_PLAN"):
            self.register(substituted)
        self.assertEqual(self.revision(), before)

    def test_review_publication_requires_exact_ci_before_reviewer_can_claim(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        review_input, ci = self.finish_implementation(pair)
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_CI_ATTESTATION_MISMATCH"):
            self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", {**ci, "implementation_commit": self.base},
                expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.assertEqual(self.revision(), before)
        result = self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.assertEqual(self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=before, recorded_at=self.stamp(26)), result)
        self.assertIn("TASK-2", self.registry.dispatch_control()["bounded_run"]["package_ids"])
        self.finish_review(review_input)
        approval = self.registry.delivery_approval("FEATURE-1")
        self.assertEqual(approval["implementation_commit"], review_input.implementation_commit)
        self.assertEqual(approval["reviewed_pr_url"], review_input.pr_url)
        self.assertNotEqual(approval["reviewer_worker_id"], approval["implementer_worker_id"])
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][0]["next_action"], "INTEGRATE")
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(43))
        packages = {row["id"]: row for row in snapshot.work_packages}
        self.assertEqual(packages["TASK-1"]["status"], "VERIFY_REVIEW")
        self.assertEqual(packages["TASK-2"]["status"], "DONE")

    def test_changes_requested_unlocks_bounded_repair_but_never_integration(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        review_input, ci = self.finish_implementation(pair)
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.finish_review(review_input, verdict=ReviewOutcomeState.CHANGES_REQUESTED)
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][0]["next_action"], "REPAIR")
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_APPROVAL_REQUIRED"):
            self.registry.delivery_approval("FEATURE-1")
        _, correction = self.plan_and_pair(implementation_issue=3, action_id="repair-plan", seconds=43, generation=1)
        self.register(correction, generation=1, action="repair-plan", previous_review="TASK-2", seconds=50)
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(51))
        packages = {row["id"]: row for row in snapshot.work_packages}
        self.assertEqual(packages["TASK-3"]["status"], "READY")
        self.assertEqual(packages["TASK-4"]["status"], "ON_DECK")
        self.assertEqual(len(snapshot.review_outcomes), 1)
        self.assertEqual(snapshot.review_outcomes[0]["state"], "CHANGES_REQUESTED")
        binding = self.registry.delivery_repair_binding("TASK-3")
        self.assertEqual(binding["implementation_commit"], review_input.implementation_commit)
        self.assertEqual(binding["base_commit"], review_input.base_commit)
        self.assertEqual(binding["review_id"], "TASK-2")
        self.assertEqual(binding["outcome_id"], "verdict-1")
        self.assertEqual(binding["changes_requested"], ["Wire the missing button"])
        self.assertEqual(set(binding["paths"]), set(pair.implementation.provider_diagnostics["exclusive_paths"]))
        self.assertIsNone(self.registry.delivery_repair_binding("TASK-1"))

    def test_successful_review_process_without_verdict_never_unlocks_integration(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        _, ci = self.finish_implementation(pair)
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.registry.acquire_lease("TASK-2", "reviewer", acquired_at=self.stamp(31), expires_at=self.stamp(300))
        self.registry.begin_attempt_runtime("review-attempt", package_id="TASK-2", worker_id="reviewer",
            runner_pid=12346, started_at=self.stamp(32), expected_revision=self.revision())
        self.registry.finish_attempt_runtime("review-attempt", ended_at=self.stamp(40), outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW, reason="provider completed without structured verdict")
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][0]["next_action"], "WAIT_REVIEW")
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_APPROVAL_REQUIRED"):
            self.registry.delivery_approval("FEATURE-1")
        self.assertFalse(self.registry.control_center_snapshot(observed_at=self.stamp(41)).review_outcomes)

    def test_real_integrated_receipt_completes_parent_and_unlocks_dependent_feature(self):
        self.submit()
        self.submit(self.brief("FEATURE-2", ("FEATURE-1",)))
        self.authorize(("FEATURE-1", "FEATURE-2"))
        _, pair = self.plan_and_pair()
        self.register(pair)
        review_input, ci = self.finish_implementation(pair)
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.finish_review(review_input)
        candidate, publication, _, _ = self.publish_candidate()
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_INTEGRATION_BINDING_MISMATCH"):
            self.registry.record_delivery_integration("run-1", "FEATURE-1", "integrate-1",
                {**publication, "target_after": self.base}, expected_revision=before, recorded_at=self.stamp(46))
        self.assertEqual(self.revision(), before)
        result = self.registry.record_delivery_integration("run-1", "FEATURE-1", "integrate-1", publication,
            expected_revision=self.revision(), recorded_at=self.stamp(46))
        self.assertEqual(self.registry.record_delivery_integration("run-1", "FEATURE-1", "integrate-1", publication,
            expected_revision=before, recorded_at=self.stamp(47)), result)
        self.assertEqual(result["integration_commit"], candidate["target_after"])
        rows = {row["feature_id"]: row for row in self.registry.delivery_snapshot(run_id="run-1")["features"]}
        self.assertEqual(rows["FEATURE-1"]["next_action"], "COMPLETE")
        self.assertEqual(rows["FEATURE-2"]["next_action"], "PLAN")
        statuses = {row["id"]: row["status"] for row in self.registry.control_center_snapshot(observed_at=self.stamp(47)).work_packages}
        self.assertEqual(statuses["TASK-1"], "DONE")
        self.git("update-ref", "refs/heads/codex/delivery", candidate["target_after"], self.base)
        self.base = candidate["target_after"]
        _, successor = self.plan_and_pair(self.brief("FEATURE-2", ("FEATURE-1",)), implementation_issue=3,
            action_id="successor-plan", dependencies={"FEATURE-1": "TASK-1"}, seconds=47)
        self.register(successor, feature="FEATURE-2", action="successor-plan", seconds=52)
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(53))
        packages = {row["id"]: row for row in snapshot.work_packages}
        self.assertEqual(packages["TASK-3"]["status"], "READY")
        self.assertEqual(packages["TASK-4"]["status"], "ON_DECK")
        self.assertEqual(set(self.registry.dispatch_control()["bounded_run"]["package_ids"]),
                         {"TASK-1", "TASK-2", "TASK-3", "TASK-4"})

    def test_remote_push_before_crash_can_be_recorded_after_deadline_and_pause(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        review_input, ci = self.finish_implementation(pair)
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.finish_review(review_input)
        candidate, _, approval, policy = self.publish_candidate()
        # Publication happened but the coordinator died before recording it.
        self.registry.update_delivery_action("integrate-1", owner="orchestra", state="UNCERTAIN",
            result={"candidate": candidate}, expected_revision=self.revision(), recorded_at=self.stamp(46))
        self.registry.set_dispatch_control(expected_revision=self.revision(), expected_mode="LIVE",
            new_mode="STOPPING", kill_switch_engaged=True, changed_at=self.stamp(3600), reason="run deadline")
        self.registry.set_dispatch_control(expected_revision=self.revision(), expected_mode="STOPPING",
            new_mode="PAUSED", kill_switch_engaged=True, changed_at=self.stamp(3601), reason="drained")
        recovered = publish_integration(self.repository, candidate, approval, policy,
            before_publish=lambda: self.fail("Recovery cannot authorize another push after pause"))
        self.assertEqual(recovered["state"], "ALREADY_PUBLISHED")
        self.registry.record_delivery_integration("run-1", "FEATURE-1", "integrate-1", recovered,
            expected_revision=self.revision(), recorded_at=self.stamp(3602))
        self.assertEqual(self.registry.delivery_snapshot(run_id="run-1")["features"][0]["next_action"], "COMPLETE")
        control = self.registry.dispatch_control()
        self.assertEqual(control["dispatch_mode"], "PAUSED")
        self.assertTrue(control["kill_switch_engaged"])
        self.assertFalse(self.registry.runtime_orphans(observed_at=self.stamp(3603)))
        with self.assertRaises(RegistryConflict):
            self.registry.reserve_delivery_action("run-1", "FEATURE-1", "late-plan", "PLAN", {},
                owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(3603))

    def test_stale_plan_invalidation_preserves_original_and_prevents_registration(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        before = self.registry.delivery_snapshot()
        self.assertEqual(before["features"][0]["next_action"], "PROJECT")
        current = self.advance_target()
        result = self.registry.invalidate_delivery_plan("plan-1", current, "integration target advanced",
            expected_revision=self.revision(), recorded_at=self.stamp(7))
        revision = self.revision()
        self.assertEqual(self.registry.invalidate_delivery_plan("plan-1", current, "integration target advanced",
            expected_revision=revision - 1, recorded_at=self.stamp(8)), result)
        self.assertEqual(self.revision(), revision)
        after = self.registry.delivery_snapshot()
        self.assertEqual(before["records"]["action:plan-1"], after["records"]["action:plan-1"])
        self.assertEqual(after["features"][0]["next_action"], "PLAN")
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_VERIFIED_PLAN_REQUIRED"):
            self.register(pair)
        with self.assertRaises(RegistryConflict):
            self.registry.invalidate_delivery_plan("plan-1", current, "rewritten reason",
                expected_revision=self.revision(), recorded_at=self.stamp(9))

    def test_stale_unclaimed_pair_is_preserved_and_replaced_by_new_generation(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        self.start()
        baseline = self.registry.dispatch_control()["bounded_run"]
        current = self.advance_target()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_REGISTERED_PLAN_REQUIRES_RETIREMENT"):
            self.registry.invalidate_delivery_plan("plan-1", current, "target advanced",
                expected_revision=self.revision(), recorded_at=self.stamp(11))
        self.registry.retire_unclaimed_delivery_pair("run-1", "FEATURE-1", current,
            expected_revision=self.revision(), recorded_at=self.stamp(12))
        row = self.registry.delivery_snapshot(run_id="run-1")["features"][0]
        self.assertEqual((row["next_action"], row["generation"]), ("PLAN", 1))
        self.base = current
        _, refreshed = self.plan_and_pair(implementation_issue=3, action_id="fresh-plan", seconds=13, generation=1)
        self.register(refreshed, generation=1, action="fresh-plan", previous_review=None, seconds=18)
        snapshot = self.registry.control_center_snapshot(observed_at=self.stamp(19))
        packages = {row["id"]: row for row in snapshot.work_packages}
        self.assertEqual([packages[name]["status"] for name in ("TASK-1", "TASK-2", "TASK-3", "TASK-4")],
                         ["BLOCKED", "BLOCKED", "READY", "ON_DECK"])
        self.assertIn("DELIVERY_BASE_MOVED", packages["TASK-1"]["failure_detail"])
        self.assertIsNone(self.registry.delivery_repair_binding("TASK-3"))
        current_scope = self.registry.dispatch_control()["bounded_run"]
        self.assertTrue(self.registry.delivery_scope_extension_is_safe(baseline, current_scope))
        self.assertFalse(self.registry.delivery_scope_extension_is_safe(baseline, {**current_scope, "deadline": self.stamp(7200)}))
        self.assertFalse(self.registry.delivery_scope_extension_is_safe(baseline,
            {**current_scope, "package_ids": [*current_scope["package_ids"], "TASK-999"]}))
        self.assertFalse(self.registry.delivery_scope_extension_is_safe(baseline,
            {**current_scope, "package_ids": ["TASK-3", "TASK-4"]}))

    def test_pair_retirement_refuses_active_and_historical_ownership(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        self.registry.register_worker(Worker("builder", "Builder", ("implementation",), (Lane.FEATURE,)))
        self.start()
        lease = self.registry.acquire_lease("TASK-1", "builder", acquired_at=self.stamp(11), expires_at=self.stamp(300))
        current = self.advance_target()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_PAIR_ALREADY_CONSUMED"):
            self.registry.retire_unclaimed_delivery_pair("run-1", "FEATURE-1", current,
                expected_revision=self.revision(), recorded_at=self.stamp(12))
        self.registry.release_lease(lease.id, released_at=self.stamp(13), reason="worker recovered before launch",
                                    next_status=TaskStatus.READY)
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_PAIR_ALREADY_CONSUMED"):
            self.registry.retire_unclaimed_delivery_pair("run-1", "FEATURE-1", current,
                expected_revision=self.revision(), recorded_at=self.stamp(14))
        self.assertEqual(self.revision(), before)
        statuses = {row["id"]: row["status"] for row in self.registry.control_center_snapshot(observed_at=self.stamp(15)).work_packages}
        self.assertEqual((statuses["TASK-1"], statuses["TASK-2"]), ("READY", "ON_DECK"))

    def test_new_run_adopts_ready_pair_without_rewriting_original_provenance(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        self.start()
        original = self.registry.delivery_snapshot()["records"]["pair:FEATURE-1:0"]
        self.stop()
        self.authorize(run_id="run-2", seconds=52)
        records = self.registry.delivery_snapshot()["records"]
        self.assertEqual(records["pair:FEATURE-1:0"], original)
        self.assertEqual(records["membership:run-2:FEATURE-1:0"]["original_run_id"], "run-1")
        self.start(run="run-2", package_ids=["TASK-1", "TASK-2"], seconds=53)
        self.registry.register_worker(Worker("builder", "Builder", ("implementation",), (Lane.FEATURE,)))
        lease = self.registry.acquire_lease("TASK-1", "builder", acquired_at=self.stamp(54), expires_at=self.stamp(300))
        self.assertEqual(lease.package_id, "TASK-1")
        with self.assertRaisesRegex(RegistryConflict, "PACKAGE_NOT_READY"):
            self.registry.acquire_lease("TASK-2", "builder", acquired_at=self.stamp(54), expires_at=self.stamp(300))
        self.assertEqual(self.registry.dispatch_control()["bounded_run"]["run_id"], "run-2")

    def test_new_run_adopts_review_only_and_keeps_implementation_context_unclaimable(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        review_input, ci = self.finish_implementation(pair)
        self.stop()
        self.authorize(run_id="run-2", seconds=52)
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTIVATION_PACKAGE_MISMATCH"):
            self.start(run="run-2", package_ids=["TASK-1", "TASK-2"], seconds=53)
        self.start(run="run-2", package_ids=["TASK-2"], seconds=53)
        with self.assertRaisesRegex(RegistryConflict, "RUN_PACKAGE_NOT_ALLOWLISTED"):
            self.registry.acquire_lease("TASK-1", "builder", acquired_at=self.stamp(54), expires_at=self.stamp(300))
        with self.assertRaisesRegex(RegistryConflict, "PACKAGE_NOT_READY"):
            self.registry.acquire_lease("TASK-2", "reviewer", acquired_at=self.stamp(54), expires_at=self.stamp(300))
        self.registry.publish_delivery_review("run-2", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(55))
        self.assertEqual(self.registry.review_input("TASK-2")["implementation_commit"], review_input.implementation_commit)
        lease = self.registry.acquire_lease("TASK-2", "reviewer", acquired_at=self.stamp(56), expires_at=self.stamp(300))
        self.assertEqual(lease.package_id, "TASK-2")
        self.assertEqual(self.registry.delivery_snapshot()["records"]["pair:FEATURE-1:0"]["run_id"], "run-1")

    def test_rejected_history_never_becomes_claimable_in_a_correction_run(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        review_input, ci = self.finish_implementation(pair)
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.finish_review(review_input, verdict=ReviewOutcomeState.CHANGES_REQUESTED)
        # Even while these IDs remain in the old run scope, non-READY
        # implementation and DONE review history cannot satisfy the lease gate.
        for package_id, worker in (("TASK-1", "builder"), ("TASK-2", "reviewer")):
            with self.subTest(package_id=package_id), self.assertRaisesRegex(RegistryConflict, "PACKAGE_NOT_READY"):
                self.registry.acquire_lease(package_id, worker, acquired_at=self.stamp(43), expires_at=self.stamp(300))
        self.stop()
        self.authorize(run_id="run-2", seconds=52)
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTIVATION_PACKAGE_MISMATCH"):
            self.start(run="run-2", package_ids=["TASK-1", "TASK-2"], seconds=53)
        _, correction = self.plan_and_pair(implementation_issue=3, action_id="correction-plan", run_id="run-2",
                                            generation=1, seconds=54)
        self.register(correction, generation=1, run="run-2", action="correction-plan",
                      previous_review="TASK-2", seconds=59)
        self.start(run="run-2", package_ids=["TASK-3", "TASK-4"], seconds=60)
        for package_id, worker in (("TASK-1", "builder"), ("TASK-2", "reviewer")):
            with self.subTest(package_id=package_id), self.assertRaisesRegex(RegistryConflict, "RUN_PACKAGE_NOT_ALLOWLISTED"):
                self.registry.acquire_lease(package_id, worker, acquired_at=self.stamp(61), expires_at=self.stamp(300))
        statuses = {row["id"]: row["status"] for row in self.registry.control_center_snapshot(observed_at=self.stamp(61)).work_packages}
        self.assertEqual([statuses[key] for key in ("TASK-1", "TASK-2", "TASK-3", "TASK-4")],
                         ["VERIFY_REVIEW", "DONE", "READY", "ON_DECK"])
        self.assertEqual(self.registry.delivery_repair_binding("TASK-3")["review_id"], "TASK-2")

    def test_stopped_run_cannot_restart_without_a_new_authorization(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        self.start()
        self.stop()
        before = self.revision()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTIVATION_INVALID"):
            self.start(seconds=52)
        self.assertEqual(self.revision(), before)
        self.assertEqual(self.registry.delivery_snapshot()["records"]["run-state:run-1"]["state"], "STOPPED")
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")
        self.assertTrue(self.registry.dispatch_control()["kill_switch_engaged"])

    def test_failed_reviewer_is_explicitly_blocked_not_waiting_for_an_impossible_result(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        _, ci = self.finish_implementation(pair)
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.registry.acquire_lease("TASK-2", "reviewer", acquired_at=self.stamp(31), expires_at=self.stamp(300))
        self.registry.begin_attempt_runtime("review-attempt", package_id="TASK-2", worker_id="reviewer",
            runner_pid=12346, started_at=self.stamp(32), expected_revision=self.revision())
        self.registry.finish_attempt_runtime("review-attempt", ended_at=self.stamp(40), outcome="FAILED",
            next_status=TaskStatus.BLOCKED, reason="provider produced no structured verdict")
        row = self.registry.delivery_snapshot(run_id="run-1")["features"][0]
        self.assertEqual(row["next_action"], "BLOCKED")
        self.assertEqual(row["reason"], "provider produced no structured verdict")
        with self.assertRaisesRegex(RegistryConflict, "PACKAGE_NOT_READY"):
            self.registry.acquire_lease("TASK-2", "reviewer", acquired_at=self.stamp(41), expires_at=self.stamp(300))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_APPROVAL_REQUIRED"):
            self.registry.delivery_approval("FEATURE-1")

    def test_approved_only_continuation_has_empty_deny_all_worker_scope(self):
        self.submit()
        self.authorize()
        _, pair = self.plan_and_pair()
        self.register(pair)
        review_input, ci = self.finish_implementation(pair)
        self.registry.publish_delivery_review("run-1", "FEATURE-1", "TASK-2", ci,
            expected_revision=self.revision(), recorded_at=self.stamp(25))
        self.finish_review(review_input)
        self.stop()
        self.authorize(run_id="run-2", seconds=52)
        for ids, error in ((["TASK-1", "TASK-2"], "DELIVERY_ACTIVATION_PACKAGE_MISMATCH"),
                           (["TASK-2"], "DELIVERY_ACTIVATION_PACKAGE_MISMATCH")):
            with self.subTest(ids=ids), self.assertRaisesRegex(RegistryConflict, error):
                self.start(run="run-2", package_ids=ids, seconds=53)
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            self.registry.reserve_delivery_action("run-2", "FEATURE-1", "no-new-integration", "INTEGRATE", {},
                owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(54))
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")
        self.assertTrue(self.registry.dispatch_control()["kill_switch_engaged"])
        self.start(run="run-2", package_ids=[], seconds=55)
        scope = self.registry.dispatch_control()["bounded_run"]
        self.assertEqual(scope["package_ids"], [])
        self.assertTrue(self.registry.delivery_scope_extension_is_safe(scope, scope))
        with self.assertRaises(RegistryConflict):
            self.registry.acquire_lease("TASK-1", "builder", acquired_at=self.stamp(56), expires_at=self.stamp(300))
        self.registry.reserve_delivery_action("run-2", "FEATURE-1", "resumed-integration", "INTEGRATE", {},
            owner="orchestra", expected_revision=self.revision(), recorded_at=self.stamp(56))


if __name__ == "__main__":
    unittest.main()
