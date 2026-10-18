import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from runner import build_agent_prompt, correction_handoff, materialize_delivery_correction
from registry_control import RunnerRegistryControl
from scripts.factory_registry.delivery_repair import CorrectionError
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry import test_delivery_repair as repair_fixtures
from scripts.factory_registry import test_delivery_registry as registry_fixtures
from scripts.runner.task_readiness import check_packet


class RunnerCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = repair_fixtures.DeliveryRepairTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.record = self.fixture.repo.parent / (self.fixture.repo.name + '-attempt.json')
        self.addCleanup(lambda: self.record.unlink(missing_ok=True))
        self.data = {'registry_attempt_id': 'attempt-correction', 'task': 'TASK-503'}
        self.body = {'task': 'TASK-503', 'kind': 'PARENT', 'paths': self.fixture.paths,
                     'instructions': 'Deliver the original behavior and address the requested changes.'}
        self.registry = SimpleNamespace(delivery_repair_binding=Mock(return_value=self.fixture.binding))
        self.control = SimpleNamespace(registry=self.registry)
        self.fetch = Mock()

    def materialize(self, control=None, body=None):
        return materialize_delivery_correction(self.control if control is None else control,
                                               self.body if body is None else body,
                                               self.fixture.base, self.fixture.repo,
                                               record=self.record, data=self.data, fetch_commit=self.fetch)

    def test_rejected_code_and_findings_are_present_before_provider_handoff(self):
        evidence = self.materialize()
        prompt = build_agent_prompt(503, self.body, readiness_handoff='Exact proof verified',
                                    correction_handoff=correction_handoff(evidence))
        observed = {}

        def provider_stub(worker_prompt):
            observed['content'] = (self.fixture.repo / 'src/nested/feature.ts').read_text()
            observed['prompt'] = worker_prompt

        provider_stub(prompt)
        self.assertEqual(observed['content'], 'complete rejected behavior\n')
        self.assertIn(self.fixture.binding['changes_requested'][0], observed['prompt'])
        self.assertIn(self.fixture.implementation, observed['prompt'])
        self.assertIn('already staged', observed['prompt'])
        self.assertIn('Exact proof verified', observed['prompt'])
        self.registry.delivery_repair_binding.assert_called_once_with('TASK-503')
        self.fetch.assert_not_called()
        saved = json.loads(self.record.read_text())['provider_diagnostics']['delivery_correction']
        self.assertEqual(saved['state'], 'APPLIED')
        self.assertEqual(saved['evidence_sha256'], evidence['evidence_sha256'])

    def test_checkpoint_precedes_materialization_and_replay_never_applies_twice(self):
        from runner import materialize_correction as real_materialize
        checkpoints = []

        def inspect_checkpoint(*args):
            checkpoints.append(json.loads(self.record.read_text())['provider_diagnostics']['delivery_correction']['state'])
            return real_materialize(*args)

        with patch('runner.materialize_correction', side_effect=inspect_checkpoint) as materializer:
            self.materialize()
            before = self.fixture.snapshot()
            with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_REPAIR_RECONCILIATION_REQUIRED'):
                self.materialize()
            self.assertEqual(materializer.call_count, 1)
        self.assertEqual(checkpoints, ['MATERIALIZING'])
        self.assertEqual(self.fixture.snapshot(), before)

    def test_legacy_implementation_and_review_have_no_correction_side_effect(self):
        self.assertIsNone(materialize_delivery_correction(None, self.body, self.fixture.base, self.fixture.repo,
                                                          record=self.record, data=self.data, fetch_commit=self.fetch))
        self.assertIsNone(self.materialize(body={**self.body, 'kind': 'REVIEW'}))
        self.registry.delivery_repair_binding.assert_not_called()
        self.registry.delivery_repair_binding.return_value = None
        self.assertIsNone(self.materialize(body={**self.body, 'repair_binding': self.fixture.binding}))
        self.fetch.assert_not_called()
        self.assertFalse(self.record.exists())
        self.assertEqual(correction_handoff(None), '')
        self.assertEqual(self.fixture.git('status', '--porcelain'), '')

    def test_invalid_registry_binding_fails_before_fetch_or_materialization(self):
        self.registry.delivery_repair_binding.return_value = {**self.fixture.binding, 'implementation_commit': '--upload-pack=evil'}
        with patch('runner.materialize_correction') as apply:
            with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_REPAIR_BINDING_INVALID'):
                self.materialize()
            apply.assert_not_called()
        self.fetch.assert_not_called()
        self.assertEqual(self.fixture.git('status', '--porcelain'), '')

    def test_missing_exact_object_fetches_only_the_registry_bound_sha(self):
        original = subprocess.run
        missing_once = [True]

        def local_lookup(*args, **kwargs):
            argv = args[0]
            if missing_once[0] and 'cat-file' in argv:
                missing_once[0] = False
                return subprocess.CompletedProcess(argv, 1, b'', b'missing')
            return original(*args, **kwargs)

        with patch('runner.subprocess.run', side_effect=local_lookup):
            self.materialize()
        self.fetch.assert_called_once_with(self.fixture.implementation)

    def test_fetch_or_apply_failure_records_evidence_and_prevents_provider_work(self):
        self.registry.delivery_repair_binding.return_value = {**self.fixture.binding, 'paths': ['src/App.tsx']}
        provider = Mock()
        with self.assertRaisesRegex(CorrectionError, 'REPAIR_PATH_OWNERSHIP_MISMATCH'):
            evidence = self.materialize()
            provider(correction_handoff(evidence))
        provider.assert_not_called()
        self.assertEqual(self.fixture.git('status', '--porcelain'), '')
        saved = json.loads(self.record.read_text())['provider_diagnostics']['delivery_correction']
        self.assertEqual(saved['state'], 'FAILED')
        self.assertEqual(saved['error_code'], 'REPAIR_PATH_OWNERSHIP_MISMATCH')
        self.assertIn('changed_paths', saved['evidence'])

    def test_existing_materializing_checkpoint_requires_reconciliation(self):
        self.data['provider_diagnostics'] = {'delivery_correction': {'state': 'MATERIALIZING'}}
        with patch('runner.materialize_correction') as apply:
            with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_REPAIR_RECONCILIATION_REQUIRED'):
                self.materialize()
            apply.assert_not_called()
        self.fetch.assert_not_called()


class DeliveryReservationRaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.control = RunnerRegistryControl(Path(temp.name) / 'unused.sqlite3')
        self.baseline = {
            'revision': 10, 'lease_id': 'lease-1', 'lease_expires_at': '2026-10-16T15:00:00Z',
            'package_id': 'TASK-501', 'worker_id': 'builder', 'package_status': 'ACTIVE',
            'bounded_run': {'run_id': 'delivery', 'package_ids': ['TASK-501', 'TASK-502'],
                            'deadline': '2026-10-16T15:00:00Z', 'base_ref': 'codex/delivery', 'parent_limit': 2},
            'deadline': '2026-10-16T15:00:00Z', 'eligible': True,
        }

    def reserve(self, current, *, certified):
        with patch.object(self.control, '_reservation_facts', side_effect=(self.baseline, current)), \
                patch.object(self.control.registry, 'begin_attempt_runtime', side_effect=[RegistryConflict('DISPATCH_NOT_AUTHORIZED'), None]) as begin, \
                patch.object(self.control.registry, 'delivery_scope_extension_is_safe', create=True, return_value=certified) as validate:
            self.control.reserve_attempt('attempt', package_id='TASK-501', worker_id='builder',
                                         expected_revision=10, lease_id='lease-1')
            return begin, validate

    def test_certified_monotonic_extension_retries_once_without_provider_execution(self):
        current = {**self.baseline, 'revision': 11,
                   'bounded_run': {**self.baseline['bounded_run'], 'package_ids': ['TASK-501', 'TASK-502', 'TASK-503', 'TASK-504']}}
        begin, validate = self.reserve(current, certified=True)
        self.assertEqual(begin.call_count, 2)
        self.assertEqual(begin.call_args.kwargs['expected_revision'], 11)
        validate.assert_called_once_with(self.baseline['bounded_run'], current['bounded_run'])

    def test_uncertified_legacy_scope_change_is_not_retried(self):
        current = {**self.baseline, 'revision': 11,
                   'bounded_run': {**self.baseline['bounded_run'], 'package_ids': ['TASK-501', 'TASK-502', 'TASK-503']}}
        for certification in (False, None, 'true'):
            with self.subTest(certification=certification), self.assertRaisesRegex(RegistryConflict, 'DISPATCH_NOT_AUTHORIZED'):
                self.reserve(current, certified=certification)

    def test_heartbeat_only_revision_keeps_legacy_behavior_without_extension_call(self):
        begin, validate = self.reserve({**self.baseline, 'revision': 11}, certified=False)
        self.assertEqual(begin.call_count, 2)
        validate.assert_not_called()

    def test_scope_certificate_cannot_override_changed_lease_deadline_or_eligibility(self):
        for key, value in (('lease_id', 'lease-2'), ('lease_expires_at', 'later'),
                           ('deadline', 'later'), ('worker_id', 'other'), ('package_status', 'READY'),
                           ('eligible', False)):
            with self.subTest(key=key), self.assertRaises(RegistryConflict):
                self.reserve({**self.baseline, 'revision': 11, key: value}, certified=True)


class DeliveryReviewReadinessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = registry_fixtures.DeliveryRegistryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.now = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.fixture.submit()
        self.fixture.authorize()
        _, self.pair = self.fixture.plan_and_pair()
        self.fixture.register(self.pair)
        self.source, ci = self.fixture.finish_implementation(self.pair)
        self.fixture.registry.publish_delivery_review('run-1', 'FEATURE-1', 'TASK-2', ci,
            expected_revision=self.fixture.revision(), recorded_at=self.fixture.stamp(30))
        self.advanced = self.fixture.advance_target()
        self.control = RunnerRegistryControl(self.fixture.database, self.fixture.repository)

    def pre_claim(self, package='TASK-2', worker='reviewer', contract=None, issue=2):
        # This suite isolates provenance/readiness from capacity scoring. The
        # real Registry input packet, contracts, Git history and revision gate
        # are retained; ordinary scheduler tests cover its proposal itself.
        decision = SimpleNamespace(proposed_assignments=[SimpleNamespace(package_id=package, worker_id=worker)])
        with patch('registry_control.decide_shadow', return_value=decision):
            return self.control.pre_claim(package, worker, task_contract=contract or self.pair.review_contract,
                                          github_issue=issue)

    def test_native_review_keeps_exact_input_when_sibling_advances_target(self):
        revision = self.fixture.revision()
        self.assertNotEqual(self.advanced, self.source.base_commit)
        self.assertEqual(self.pre_claim(), revision)
        source = self.control.registry.review_input('TASK-2')
        self.assertEqual(source['implementation_commit'], self.source.implementation_commit)
        self.assertEqual(source['base_commit'], self.source.base_commit)
        self.assertEqual(source['contract'], self.pair.implementation_contract)
        self.assertEqual(self.fixture.revision(), revision)

    def test_implementation_still_requires_current_target_tip(self):
        with self.assertRaisesRegex(RegistryConflict, 'BASE_REF_CHANGED'):
            self.pre_claim('TASK-1', 'builder', self.pair.implementation_contract, 1)

    def test_review_separation_survives_historical_base_path(self):
        with self.assertRaisesRegex(RegistryConflict, 'REVIEW_INDEPENDENCE_REQUIRED'):
            self.pre_claim(worker='builder')

    def test_legacy_review_does_not_opt_into_historical_base(self):
        snapshot = self.control._run_snapshot(self.fixture.stamp(50))
        packages = deepcopy(snapshot.work_packages)
        for package in packages:
            if package['id'] == 'TASK-2':
                package['provider_diagnostics'].pop('delivery_feature_id')
        with patch.object(self.control, '_run_snapshot', return_value=replace(snapshot, work_packages=packages)):
            with self.assertRaisesRegex(RegistryConflict, 'BASE_REF_CHANGED'):
                self.pre_claim()

    def test_false_native_binding_or_changed_planning_proof_is_rejected(self):
        original = self.control.registry.review_input('TASK-2')
        mutations = (
            {'target_package_id': 'TASK-999'},
            {'review_package_id': 'TASK-999'},
            {'base_commit': self.advanced},
            {'contract_sha256': 'f' * 64},
            {'contract': {**original['contract'], 'instructions': 'Different owner scope'}},
            {'external_integration': {'id': 'historical'}},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), \
                    patch.object(self.control.registry, 'review_input', return_value={**original, **mutation}):
                with self.assertRaisesRegex(RegistryConflict, 'NATIVE_DELIVERY_REVIEW_BINDING_INVALID'):
                    self.pre_claim()
        snapshot = self.control._run_snapshot(self.fixture.stamp(50))
        packages = deepcopy(snapshot.work_packages)
        for package in packages:
            if package['id'] == 'TASK-2':
                package['provider_diagnostics']['readiness_proof']['planning_sha256']['docs/PLAN.md'] = 'f' * 64
        with patch.object(self.control, '_run_snapshot', return_value=replace(snapshot, work_packages=packages)):
            with self.assertRaisesRegex(RegistryConflict, 'NATIVE_DELIVERY_REVIEW_BINDING_INVALID'):
                self.pre_claim()

    def test_tampering_persisted_implementation_sha_cannot_redirect_review(self):
        # Even a different descendant of the same planning base is not the
        # artifact named by the immutable packet and native CI receipt.
        with sqlite3.connect(self.fixture.database) as connection:
            row = connection.execute("SELECT metadata_json FROM evidence WHERE id=?",
                                     (self.source.id,)).fetchone()
            metadata = json.loads(row[0])
            metadata['implementation_commit'] = self.advanced
            connection.execute("UPDATE evidence SET metadata_json=? WHERE id=?",
                               (json.dumps(metadata), self.source.id))
        with self.assertRaises(RegistryConflict):
            self.pre_claim()

    def test_unrelated_implementation_or_rewritten_target_is_not_compatible(self):
        self.fixture.git('checkout', '--orphan', 'codex/unrelated')
        self.fixture.git('add', '.')
        self.fixture.git('commit', '-m', 'unrelated history')
        unrelated = self.fixture.git('rev-parse', 'HEAD')
        original = self.control.registry.review_input('TASK-2')
        with patch.object(self.control.registry, 'review_input', return_value={**original, 'implementation_commit': unrelated}):
            with self.assertRaisesRegex(RegistryConflict, 'NATIVE_DELIVERY_REVIEW_ANCESTRY_MISMATCH'):
                self.pre_claim()
        self.fixture.git('update-ref', 'refs/heads/codex/delivery', unrelated)
        with self.assertRaisesRegex(RegistryConflict, 'NATIVE_DELIVERY_REVIEW_ANCESTRY_MISMATCH'):
            self.pre_claim()

    def test_raw_check_cannot_opt_in_a_legacy_or_implementation_package(self):
        snapshot = self.control._run_snapshot(self.fixture.stamp(50))
        implementation = next(item for item in snapshot.work_packages if item['id'] == 'TASK-1')
        result = check_packet(self.pair.implementation_contract, repository=self.fixture.repository,
            run_base='codex/delivery', package=implementation, snapshot=snapshot, github_issue=1,
            review_input=self.control.registry.review_input('TASK-2'))
        self.assertEqual(result.state, 'BLOCKED')
        self.assertIn('NATIVE_DELIVERY_REVIEW_BINDING_INVALID', result.reasons)


if __name__ == '__main__':
    unittest.main()
