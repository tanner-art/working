"""Adversarial restart tests: no worker scope is not unrestricted authority."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.factory_registry import bounded_run_guard
from scripts.factory_registry import delivery_coordinator
from scripts.factory_registry import test_delivery_coordinator as fixtures
from scripts.factory_registry.models import ReviewOutcomeState
from scripts.factory_registry.operator import coordinator_continuation_gate, OperatorError
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.shadow_dispatch import decide_shadow
from scripts.factory_registry.test_shadow_dispatch import package, snapshot, worker
from scripts.runner.registry_control import scope_dispatch_snapshot


class DeliveryContinuationTests(unittest.TestCase):
    def setUp(self):
        self.loop = fixtures.DeliveryCoordinatorTests()
        self.loop.setUp()
        self.addCleanup(self.loop.doCleanups)
        self.fx, self.registry = self.loop.fx, self.loop.registry

    def approved_stop(self, *, dependent=False, verdict=ReviewOutcomeState.APPROVED):
        self.loop.authorize(dependent=dependent)
        self.loop.tick(seconds=1)
        self.loop.tick(seconds=2)
        source = self.loop.implement()
        self.loop.tick(seconds=25)
        self.fx.finish_review(source, verdict=verdict)
        self.fx.stop()
        self.fx.authorize(features=("FEATURE-1", "FEATURE-2") if dependent else ("FEATURE-1",),
                          run_id="run-2", seconds=52)
        self.scope = {"run_id": "run-2", "package_ids": [], "deadline": self.fx.stamp(3600),
                      "base_ref": "codex/delivery", "parent_limit": 2}
        self.loop.coordinator.run_id = "run-2"
        return source

    def preflight(self):
        return self.registry.delivery_activation_preflight(self.scope, observed_at=self.fx.stamp(53))

    def interrupted_integration(self, *, published=False):
        self.loop.authorize(dependent=True)
        self.loop.tick(seconds=1)
        self.loop.tick(seconds=2)
        source = self.loop.implement()
        self.loop.tick(seconds=25)
        self.fx.finish_review(source)
        before = self.loop.remote_sha()
        prepare = delivery_coordinator.prepare_integration
        def prepare_then_stop(*args, **kwargs):
            candidate = prepare(*args, **kwargs)
            self.fx.stop(seconds=49)
            return candidate
        if published:
            with patch.object(self.registry, 'record_delivery_integration', side_effect=OSError('lost acknowledgement')):
                self.loop.tick(seconds=50)
            self.fx.stop(seconds=50)
        else:
            with patch.object(delivery_coordinator, 'prepare_integration', prepare_then_stop):
                self.loop.tick(seconds=50)
            self.assertEqual(self.loop.remote_sha(), before)
        feature = self.registry.delivery_snapshot(run_id='run-1')['features'][0]
        action = feature['unresolved_actions'][0]
        self.assertEqual(action['state'], 'UNCERTAIN')
        return source, action

    def resume_authorization(self):
        self.fx.authorize(features=('FEATURE-1', 'FEATURE-2'), run_id='run-2', seconds=52)
        self.scope = {'run_id': 'run-2', 'package_ids': [], 'deadline': self.fx.stamp(3600),
                      'base_ref': 'codex/delivery', 'parent_limit': 2}
        self.loop.coordinator.run_id = 'run-2'

    def test_stopped_unpublished_candidate_resumes_exact_action_without_reimplementation(self):
        source, original = self.interrupted_integration()
        self.resume_authorization()
        certificate = self.preflight()
        self.assertEqual(certificate['integration_resumes'][0]['action_id'], original['action_id'])
        snapshot = self.registry.delivery_snapshot(run_id='run-2')
        self.assertEqual(snapshot['records']['action:' + original['action_id']], original)
        self.assertIsNone(snapshot['features'][0]['integration'])
        self.fx.start(run='run-2', package_ids=[], seconds=54)
        baseline = self.registry.dispatch_control()['bounded_run']
        self.assertTrue(bounded_run_guard._scope_matches(self.fx.database, baseline, baseline))
        with patch.object(delivery_coordinator, 'prepare_integration', side_effect=AssertionError('must reuse candidate')):
            result = self.loop.tick(seconds=55)
        self.assertTrue(all(row['state'] == 'OBSERVED' for row in result['results']), result)
        self.loop.tick(seconds=56)
        snapshot = self.registry.delivery_snapshot(run_id='run-2')
        first, second = snapshot['features']
        self.assertEqual(first['next_action'], 'COMPLETE')
        self.assertEqual(first['integration']['implementation_commit'], source.implementation_commit)
        self.assertEqual(first['integration']['integration_commit'], original['checkpoint']['candidate']['target_after'])
        self.assertEqual(second['implementation_status'], 'READY')
        action = snapshot['records']['action:' + original['action_id']]
        self.assertEqual(action['run_id'], 'run-1')
        self.assertEqual(action['state'], 'SUCCEEDED')
        self.assertIsNone(action['runtime_seconds'], 'paused time is not execution time')
        with self.registry._connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 2)

    def test_already_published_candidate_is_reconciled_without_a_second_push(self):
        _, original = self.interrupted_integration(published=True)
        published = self.loop.remote_sha()
        self.resume_authorization()
        self.fx.start(run='run-2', package_ids=[], seconds=54)
        from scripts.factory_registry import delivery_integration
        git = delivery_integration._git
        def no_push(repo, policy, *args, **kwargs):
            self.assertNotIn('push', args)
            return git(repo, policy, *args, **kwargs)
        with patch.object(delivery_integration, '_git', no_push):
            self.loop.tick(seconds=55)
        snapshot = self.registry.delivery_snapshot(run_id='run-2')
        self.assertEqual(snapshot['features'][0]['integration']['publication']['state'], 'ALREADY_PUBLISHED')
        self.assertEqual(self.loop.remote_sha(), published)

    def test_resume_does_not_allow_old_run_to_publish_or_clear_uncertainty(self):
        _, original = self.interrupted_integration()
        before = self.loop.remote_sha()
        self.resume_authorization()
        self.loop.coordinator.run_id = 'run-1'
        result = self.loop.tick(seconds=53)
        self.assertEqual(result['results'][0]['state'], 'BLOCKED')
        self.assertEqual(self.loop.remote_sha(), before)
        snapshot = self.registry.delivery_snapshot(run_id='run-1')
        self.assertEqual(snapshot['records']['action:' + original['action_id']]['state'], 'UNCERTAIN')
        self.assertIsNone(snapshot['features'][0]['integration'])
        self.assertEqual(snapshot['control']['dispatch_mode'], 'PAUSED')

    def test_changed_action_after_authorization_fails_before_live(self):
        _, action = self.interrupted_integration()
        self.resume_authorization()
        self.registry.update_delivery_action(action['action_id'], owner=action['owner'], state='UNCERTAIN',
            result={**action['checkpoint'], 'code': 'changed after authorization'},
            expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(53))
        before = self.fx.revision()
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_ACTION_UNRESOLVED'):
            self.fx.start(run='run-2', package_ids=[], seconds=54)
        self.assertEqual(self.fx.revision(), before)
        self.assertEqual(self.registry.dispatch_control()['dispatch_mode'], 'PAUSED')

    def test_missing_or_invalid_candidate_cannot_be_adopted(self):
        _, action = self.interrupted_integration()
        from scripts.factory_registry.sqlite_delivery import digest
        failed = {**action['checkpoint']['candidate'], 'validation': [{'returncode': 1}]}
        failed['receipt_sha256'] = digest({key: value for key, value in failed.items() if key != 'receipt_sha256'})
        variants = [
            ('missing', 'UNCERTAIN', {}),
            ('failed-validation', 'UNCERTAIN', {**action['checkpoint'], 'candidate': failed}),
            ('tampered', 'UNCERTAIN', {**action['checkpoint'], 'candidate': {
                **action['checkpoint']['candidate'], 'target_after': '0' * 40}}),
        ]
        for index, (name, state, checkpoint) in enumerate(variants):
            with self.subTest(name=name):
                self.registry.update_delivery_action(action['action_id'], owner=action['owner'], state=state,
                    result=checkpoint, expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(52 + index))
                before = self.fx.revision()
                with self.assertRaises(RegistryConflict):
                    self.fx.authorize(features=('FEATURE-1', 'FEATURE-2'), run_id='run-2', seconds=55 + index)
                self.assertEqual(self.fx.revision(), before)
                self.assertNotIn('authorization:run-2', self.registry.delivery_snapshot()['records'])

    def test_stopped_running_integration_with_durable_candidate_can_resume(self):
        _, action = self.interrupted_integration()
        # A crash can leave the durable candidate RUNNING rather than reaching
        # the exception checkpoint. This is not a running implementation attempt.
        self.registry.update_delivery_action(action['action_id'], owner=action['owner'], state='RUNNING',
            result={'candidate': action['checkpoint']['candidate']},
            expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(51))
        self.resume_authorization()
        self.fx.start(run='run-2', package_ids=[], seconds=54)
        result = self.loop.tick(seconds=55)
        self.assertEqual(result['results'][0]['state'], 'OBSERVED', result)
        self.assertEqual(self.registry.delivery_snapshot(run_id='run-2')['features'][0]['next_action'], 'COMPLETE')

    def test_cross_target_and_failed_native_review_cannot_be_adopted(self):
        _, action = self.interrupted_integration()
        auth = self.registry.delivery_snapshot(run_id='run-1')['authorization']
        spec = {key: auth[key] for key in ('feature_ids', 'deadline', 'parent_limit', 'max_generations', 'coordinator_worker_id')}
        spec.update(run_id='run-2', base_ref='codex/other-target')
        before = self.fx.revision()
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_ACTION_UNRESOLVED'):
            self.registry.authorize_delivery_run(spec, expected_revision=before, recorded_at=self.fx.stamp(52))
        self.assertEqual(self.fx.revision(), before)
        with self.registry._connection() as connection:
            connection.execute("UPDATE attempts SET outcome='FAILED' WHERE id='review-attempt'")
        with self.assertRaisesRegex(RegistryConflict, 'NATIVE_ATTEMPT_REQUIRED'):
            self.resume_authorization()
        self.assertEqual(self.fx.revision(), before)

    def test_moved_target_revalidates_without_repeating_implementation_or_review(self):
        _, original = self.interrupted_integration()
        self.fx.advance_target()
        self.fx.git('push', 'origin', 'codex/delivery')
        self.fx.git('checkout', 'codex/implementation')
        self.resume_authorization()
        self.fx.start(run='run-2', package_ids=[], seconds=54)
        result = self.loop.tick(seconds=55)
        self.assertTrue(all(row['state'] == 'OBSERVED' for row in result['results']), result)
        snapshot = self.registry.delivery_snapshot(run_id='run-2')
        receipt = snapshot['features'][0]['integration']
        self.assertNotEqual(receipt['integration_commit'], original['checkpoint']['candidate']['target_after'])
        self.assertEqual(receipt['candidate']['approval'], original['checkpoint']['candidate']['approval'])
        self.assertEqual(receipt['publication']['state'], 'PUBLISHED')

    def test_real_integration_after_restart_unlocks_and_certifies_successor(self):
        source = self.approved_stop(dependent=True)
        before = self.fx.revision()
        certificate = self.preflight()
        self.assertEqual(self.fx.revision(), before)
        self.assertEqual(certificate["approved_bindings"][0]["implementation_commit"], source.implementation_commit)
        self.fx.start(run="run-2", package_ids=[], seconds=54)
        baseline = self.registry.dispatch_control()["bounded_run"]
        self.assertTrue(bounded_run_guard._scope_matches(self.fx.database, baseline, baseline))
        self.loop.tick(seconds=55)
        self.loop.tick(seconds=56)
        snapshot = self.registry.delivery_snapshot(run_id="run-2")
        self.assertEqual(snapshot["features"][0]["next_action"], "COMPLETE")
        self.assertEqual(snapshot["features"][1]["implementation_status"], "READY")
        current = self.registry.dispatch_control()["bounded_run"]
        self.assertEqual(set(current["package_ids"]), {"TASK-3", "TASK-4"})
        self.assertTrue(bounded_run_guard._scope_matches(self.fx.database, baseline, current))
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, baseline,
            {**current, "package_ids": current["package_ids"] + ["TASK-999"]}))
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, baseline,
            {**current, "deadline": self.fx.stamp(7200)}))
        stored = snapshot["records"]["run-state:run-2"]["continuation_certificate"]
        self.assertEqual(stored, certificate)
        self.fx.stop(seconds=60)
        self.assertFalse(self.registry.active_attempt_runtimes())
        self.assertFalse(self.registry.active_unbound_leases())

    def test_unknown_run_empty_scope_is_rejected_atomically(self):
        before = self.fx.revision()
        with self.assertRaisesRegex(RegistryConflict, "CONTINUATION_NOT_AUTHORIZED"):
            self.fx.start(run="unknown-run", package_ids=[])
        self.assertEqual(self.fx.revision(), before)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_rejection_is_not_a_continuation_approval(self):
        self.approved_stop(verdict=ReviewOutcomeState.CHANGES_REQUESTED)
        with self.assertRaisesRegex(RegistryConflict, "CONTINUATION_NOT_AUTHORIZED"):
            self.preflight()
        with self.assertRaises(RegistryConflict):
            self.fx.start(run="run-2", package_ids=[], seconds=54)

    def test_missing_packet_or_expired_authorization_fails_before_live(self):
        source = self.approved_stop()
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTIVATION_INVALID"):
            self.registry.delivery_activation_preflight(self.scope, observed_at=self.fx.stamp(3600))
        Path(source.validation_evidence["review_packet"]["path"], "contract.json").unlink()
        with self.assertRaises(RegistryConflict):
            self.fx.start(run="run-2", package_ids=[], seconds=54)
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "PAUSED")

    def test_uncertified_empty_scope_never_satisfies_guard(self):
        self.approved_stop()
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, self.scope, self.scope))

    def test_empty_worker_scope_hides_even_unrelated_ready_packages(self):
        self.approved_stop()
        self.fx.start(run="run-2", package_ids=[], seconds=54)
        with self.registry._connection() as connection:
            for package_id in ("TASK-1", "TASK-2", "TASK-999"):
                with self.subTest(package_id=package_id), self.assertRaisesRegex(RegistryConflict, "RUN_PACKAGE_NOT_ALLOWLISTED"):
                    self.registry._assert_scope_membership(connection, package_id, self.fx.stamp(55))
        dispatch = snapshot(packages=(package("TASK-999", capabilities=("implementation",)),),
                            workers=(worker("builder", capabilities=("implementation",)),))
        scoped = scope_dispatch_snapshot(dispatch, [], 2)
        self.assertFalse(decide_shadow(scoped).proposed_assignments)

    def test_unresolved_preparation_blocks_continuation(self):
        self.approved_stop()
        self.registry.reserve_delivery_action("run-2", "FEATURE-1", "pending-plan", "PLAN", {},
            owner="orchestra", expected_revision=self.fx.revision(), recorded_at=self.fx.stamp(53))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_ACTION_UNRESOLVED"):
            self.fx.start(run="run-2", package_ids=[], seconds=54)

    def test_failed_native_attempt_cannot_supply_continuation_certificate(self):
        self.approved_stop()
        with self.registry._connection() as connection:
            connection.execute("UPDATE attempts SET outcome='FAILED' WHERE id='review-attempt'")
        with self.assertRaisesRegex(RegistryConflict, "NATIVE_ATTEMPT_REQUIRED"):
            self.fx.start(run="run-2", package_ids=[], seconds=54)

    def test_certificate_corruption_and_changed_brief_fail_closed(self):
        self.approved_stop()
        self.fx.start(run="run-2", package_ids=[], seconds=54)
        scope = self.registry.dispatch_control()["bounded_run"]
        # Direct writes only in the isolated fault-injection fixture.
        with self.registry._connection() as connection:
            row = connection.execute("SELECT value FROM registry_metadata WHERE key='delivery:run-state:run-2'").fetchone()
            record = json.loads(row[0])
            record["continuation_certificate"]["approved_bindings"] = []
            connection.execute("UPDATE registry_metadata SET value=? WHERE key='delivery:run-state:run-2'", (json.dumps(record),))
        self.assertFalse(bounded_run_guard._scope_matches(self.fx.database, scope, scope))
        self.fx.stop(seconds=55)
        self.fx.authorize(run_id="run-3", seconds=57)
        with self.registry._connection() as connection:
            row = connection.execute("SELECT value FROM registry_metadata WHERE key='delivery:request:FEATURE-1'").fetchone()
            record = json.loads(row[0])
            record["brief"]["user_experience"] = "Unapproved changed intent"
            connection.execute("UPDATE registry_metadata SET value=? WHERE key='delivery:request:FEATURE-1'", (json.dumps(record),))
        with self.assertRaisesRegex(RegistryConflict, "DELIVERY_REQUEST_CHANGED"):
            self.fx.start(run="run-3", package_ids=[], seconds=58)

    def test_operator_requires_exact_service_and_fresh_coordinator_capacity(self):
        self.approved_stop()
        dispatch = self.registry.dispatch_snapshot(observed_at=self.fx.stamp(53))
        loader = "scripts.factory_registry.delivery_service.load_coordinator"
        with patch(loader, return_value=self.loop.coordinator) as load:
            result = coordinator_continuation_gate(self.registry, dispatch, self.scope, self.fx.root / "config.json")
            self.assertEqual(result["run_package_ids"], [])
            load.assert_called_once()
            self.loop.coordinator.run_id = "wrong-run"
            with self.assertRaisesRegex(OperatorError, "service binding mismatch"):
                coordinator_continuation_gate(self.registry, dispatch, self.scope, self.fx.root / "config.json")
            self.loop.coordinator.run_id = "run-2"
            for seconds, error in ((181, "HEARTBEAT_INVALID"), (1000, "CAPACITY_BLOCKED")):
                with self.subTest(seconds=seconds), self.assertRaisesRegex(OperatorError, error):
                    coordinator_continuation_gate(self.registry, replace(dispatch, observed_at=self.fx.stamp(seconds)),
                                                 self.scope, self.fx.root / "config.json")
            self.loop.telemetry(consumed=90, observed_seconds=53)
            with self.assertRaisesRegex(OperatorError, "CAPACITY_BLOCKED"):
                coordinator_continuation_gate(self.registry, self.registry.dispatch_snapshot(observed_at=self.fx.stamp(53)),
                                             self.scope, self.fx.root / "config.json")


if __name__ == "__main__":
    unittest.main()
