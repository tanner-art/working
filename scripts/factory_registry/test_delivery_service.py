"""Installed-service account binding without provider or live operations."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from scripts.factory_registry import delivery_service as service
from scripts.factory_registry import test_delivery_registry as fixtures
from scripts.factory_registry import test_delivery_coordinator as coordinator_fixtures
from scripts.factory_registry.models import Lane, ReviewOutcomeState, Worker
from scripts.factory_registry.delivery_runtime import readonly_planner_command
from scripts.factory_registry.operator import EXPECTED_USAGE_POLICY, OperatorError
from scripts.factory_registry.repository import RegistryConflict


class DeliveryServiceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DeliveryRegistryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.submit()
        self.fixture.authorize()
        self.release = Path(service.__file__).resolve().parents[2]
        self.pool = 'a' * 64
        self.worker('codex-b')
        self.worker('orchestra', role='ORCHESTRA')
        self.auth_home = str(self.fixture.root / 'auth-b')
        self.path = self.fixture.root / 'config.json'
        agents = {}
        for name in ('codex-a', 'codex-b'):
            agents[name] = {'provider': 'openai', 'slots': 1, 'capacity_mode': 'percentage',
                'capacity_scopes': ['short_window', 'weekly_window'],
                'command': ['/opt/homebrew/bin/codex', 'exec', '--disable', 'multi_agent', '-'],
                'env': {'CODEX_HOME': self.auth_home if name == 'codex-b' else str(self.fixture.root / 'auth-a')}}
        agents['claude'] = {'provider': 'anthropic', 'slots': 1, 'capacity_mode': 'provider_signal',
            'capacity_scopes': ['provider_signal'], 'env': {},
            'command': [sys.executable, str(self.release / 'scripts/runner/claude_keychain.py'),
                        'exec', '/opt/homebrew/bin/claude', '-p', '--tools', 'Read,Glob,Grep']}
        self.config = {'repo': str(self.fixture.repository), 'state': str(self.fixture.root / 'state'),
            'worktrees': str(self.fixture.root / 'worktrees'), 'path': '/usr/bin:/bin',
            'registry_database': str(self.fixture.database), 'registry_lease_seconds': 2100,
            'registry_renew_interval_seconds': 30, 'usage_policy': deepcopy(EXPECTED_USAGE_POLICY),
            'gh': str(self.release / 'scripts/runner/github.py'), 'github': 'example/app', 'agents': agents,
            'capacity_collectors': {'codex-b': {'executable': '/opt/homebrew/bin/codex',
                'codex_home': self.auth_home, 'shared_account_aliases': ['orchestra'],
                'environment': {'CODEX_HOME': self.auth_home}}},
            'delivery': {'run_id': 'run-1', 'planner_agent': 'codex-b', 'coordinator_worker_id': 'orchestra',
                         'validation_commands': [['pnpm', 'check'], ['pnpm', 'build']]}}
        self.write()

    def worker(self, name, *, role='WORKER', pool=None):
        self.fixture.registry.register_worker(Worker(name, name, ('coordination',) if role == 'ORCHESTRA' else ('implementation',),
            (Lane.FEATURE,), role=role, provider_diagnostics={'capacity_pool': self.pool if pool is None else pool}))

    def write(self):
        self.path.write_text(json.dumps(self.config))
        self.path.chmod(0o600)

    def load(self):
        self.write()
        return service.load_coordinator(self.path, self.fixture.database)

    def test_loader_uses_configured_account_and_shared_pool_without_launching_anything(self):
        revision = self.fixture.revision()
        with patch.object(service.RunnerRegistryControl, 'refresh_configured_capacity') as refresh, \
                patch('scripts.factory_registry.delivery_runtime.subprocess.run') as execute:
            coordinator = self.load()
        self.assertEqual(coordinator.planner.worker_id, 'orchestra')
        self.assertEqual(coordinator.planner.capacity_pool, self.pool)
        self.assertEqual(coordinator.planner.environment['CODEX_HOME'], self.auth_home)
        self.assertEqual(coordinator.planner.command, tuple(self.config['agents']['codex-b']['command']))
        self.assertEqual(coordinator.integration.target_branch, 'codex/delivery')
        self.assertEqual(coordinator.integration.validation_commands, (('pnpm', 'check'), ('pnpm', 'build')))
        self.assertEqual(coordinator.github.command, [str(self.release / 'scripts/runner/github.py')])
        self.assertEqual(self.fixture.revision(), revision)
        refresh.assert_not_called()
        execute.assert_not_called()

    def test_installed_native_agent_disable_flag_is_compatible_with_readonly_planner(self):
        coordinator = self.load()
        schema = self.fixture.root / 'schema.json'
        schema.write_text('{"type":"object"}')
        command = readonly_planner_command(coordinator.planner.provider, coordinator.planner.command,
                                           schema_path=schema)
        self.assertEqual(command[:2], ['/opt/homebrew/bin/codex', 'exec'])
        self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
        self.assertIn('--ignore-user-config', command)
        self.assertIn('multi_agent', command)

    def test_loader_requires_private_owned_non_symlink_config(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_PRIVATE_CONFIG_REQUIRED'):
            service.load_coordinator(self.path, self.fixture.database)
        self.path.chmod(0o600)
        link = self.path.with_name('linked.json')
        link.symlink_to(self.path)
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_PRIVATE_CONFIG_REQUIRED'):
            service.load_coordinator(link, self.fixture.database)
        with patch.object(service.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_PRIVATE_CONFIG_REQUIRED'):
                service.load_coordinator(self.path, self.fixture.database)

    def test_account_home_executable_and_collector_environment_must_match(self):
        original = deepcopy(self.config)
        for mutation in ('home', 'executable', 'collector-environment', 'agent-environment'):
            with self.subTest(mutation=mutation):
                self.config = deepcopy(original)
                collector = self.config['capacity_collectors']['codex-b']
                if mutation == 'home':
                    collector['codex_home'] = str(self.fixture.root / 'different-account')
                elif mutation == 'executable':
                    collector['executable'] = '/different/bin/codex'
                elif mutation == 'collector-environment':
                    collector['environment']['OPENAI_ORG_ID'] = 'different-organization'
                else:
                    self.config['agents']['codex-b']['env']['OPENAI_BASE_URL'] = 'https://different.example.invalid'
                with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_PLANNER_ACCOUNT_SOURCE_MISMATCH'):
                    self.load()

    def test_matching_auth_environment_is_preserved_but_never_inherited_from_host(self):
        self.config['agents']['codex-b']['env']['OPENAI_ORG_ID'] = 'configured-organization'
        self.config['capacity_collectors']['codex-b']['environment']['OPENAI_ORG_ID'] = 'configured-organization'
        with patch.dict(os.environ, {'OPENAI_ORG_ID': 'ambient-wrong-organization', 'OPENAI_API_KEY': 'ambient-do-not-copy'}):
            coordinator = self.load()
        self.assertEqual(coordinator.planner.environment['OPENAI_ORG_ID'], 'configured-organization')
        self.assertNotIn('OPENAI_API_KEY', coordinator.planner.environment)
        self.assertNotIn('OPENAI_ORG_ID', coordinator.github.environment)

    def test_missing_alias_or_different_capacity_pool_fails_without_rebinding(self):
        self.config['capacity_collectors']['codex-b']['shared_account_aliases'] = []
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_SHARED_ACCOUNT_ALIAS_REQUIRED'):
            self.load()
        self.config['capacity_collectors']['codex-b']['shared_account_aliases'] = ['orchestra']
        self.worker('orchestra', role='ORCHESTRA', pool='b' * 64)
        revision = self.fixture.revision()
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_PLANNER_ACCOUNT_UNBOUND'):
            self.load()
        self.assertEqual(self.fixture.revision(), revision)

    def test_inline_secrets_and_wrong_authoritative_database_are_rejected(self):
        self.config['agents']['codex-b']['env']['OPENAI_API_KEY'] = 'never-persist-provider-secret'
        with self.assertRaisesRegex(OperatorError, 'secret-shaped'):
            self.load()
        del self.config['agents']['codex-b']['env']['OPENAI_API_KEY']
        self.config['registry_database'] = str(self.fixture.root / 'wrong.sqlite3')
        with self.assertRaisesRegex(OperatorError, 'authoritative Registry'):
            self.load()
        self.assertFalse((self.fixture.root / 'wrong.sqlite3').exists())

    def test_service_cannot_override_authorized_coordinator_or_target_main(self):
        self.config['delivery']['coordinator_worker_id'] = 'codex-b'
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_AUTHORIZATION_REQUIRED'):
            self.load()
        self.config['delivery']['coordinator_worker_id'] = 'orchestra'
        self.config['delivery']['run_id'] = 'main-run'
        self.fixture.registry.authorize_delivery_run({'run_id': 'main-run', 'feature_ids': ['FEATURE-1'],
            'deadline': self.fixture.stamp(3600), 'base_ref': 'main', 'parent_limit': 2, 'max_generations': 3,
            'coordinator_worker_id': 'orchestra'}, expected_revision=self.fixture.revision(), recorded_at=self.fixture.stamp())
        with self.assertRaisesRegex(RegistryConflict, 'MAIN_INTEGRATION_NOT_AUTHORIZED'):
            self.load()

    def test_telemetry_refresh_requires_real_shared_account_observation(self):
        coordinator = self.load()
        with patch.object(service.RunnerRegistryControl, 'refresh_configured_capacity', return_value=(
                {'worker_id': 'codex-b', 'observations': [{'state': 'GREEN'}]},
                {'worker_id': 'orchestra', 'observations': (), 'error_class': 'Unavailable'},
        )) as refresh, patch.object(service.RunnerRegistryControl, 'observe_worker_heartbeat') as heartbeat:
            with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_COORDINATOR_TELEMETRY_UNAVAILABLE'):
                coordinator.health_refresh()
            heartbeat.assert_not_called()
            refresh.assert_called_once()

    def test_refresh_cadence_preserves_observation_age_and_updates_only_own_heartbeat(self):
        coordinator = self.load()
        with patch.object(service.RunnerRegistryControl, 'refresh_configured_capacity', return_value=(
                {'worker_id': 'orchestra', 'observations': [{'state': 'GREEN'}]},
        )) as refresh, patch.object(service.RunnerRegistryControl, 'observe_worker_heartbeat') as heartbeat, \
                patch.object(service.time, 'monotonic', side_effect=[100.0, 120.0, 161.0]):
            coordinator.health_refresh()
            coordinator.health_refresh()
            coordinator.health_refresh()
        self.assertEqual(refresh.call_count, 2)
        self.assertEqual(heartbeat.call_count, 3)
        self.assertTrue(all(call.args == ('orchestra',) for call in heartbeat.call_args_list))


class DeliveryServiceModeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = coordinator_fixtures.DeliveryCoordinatorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.authorize()

    def coordinator(self, *, prepare=False, run_id='run-1'):
        original = self.fixture.coordinator
        return service._ServiceCoordinator(original.registry, repository=original.repository,
            run_id=run_id, state_directory=original.state, planner=original.planner,
            github=original.github, integration=original.integration, clock=original.clock,
            planner_runner=original.planner_runner, prepare=prepare)

    def test_run_at_load_before_activation_never_bootstraps_or_creates_state(self):
        coordinator = self.coordinator()
        before = self.fixture.fx.revision()
        result = coordinator.tick()
        self.assertEqual((result['state'], result['factory_mode']), ('WAITING', 'PAUSED'))
        self.assertFalse(coordinator.state.exists())
        self.assertFalse(coordinator.registry.database.with_suffix('.delivery.lock').exists())
        self.assertEqual(self.fixture.fx.revision(), before)
        self.assertEqual(self.fixture.planner_calls, [])

    def test_supervised_guard_never_borrows_paused_bootstrap_during_a_pass(self):
        coordinator = self.coordinator()
        with self.assertRaisesRegex(RegistryConflict, 'DISPATCH_PAUSED'):
            coordinator._guard(bootstrap=True)
        original = coordinator.registry.dispatch_control()
        with patch.object(coordinator.registry, 'dispatch_control', side_effect=[
                {**original, 'dispatch_mode': 'LIVE', 'kill_switch_engaged': False}, original]):
            result = coordinator.tick()
        self.assertEqual(result['state'], 'WAITING')
        self.assertEqual(self.fixture.planner_calls, [])

    def test_explicit_prepare_only_plans_and_projects_fresh_paused_authorization(self):
        coordinator = self.coordinator(prepare=True)
        self.assertEqual(coordinator.tick()['results'][0]['action'], 'PLAN')
        self.fixture.seconds += 1
        self.assertEqual(coordinator.tick()['results'][0]['action'], 'PROJECT')
        before = self.fixture.fx.revision()
        self.fixture.seconds += 1
        result = coordinator.tick()
        self.assertEqual(result['results'][0], {'feature_id': 'FEATURE-1',
            'action': 'WAIT_IMPLEMENTATION', 'state': 'WAITING'})
        self.assertEqual(self.fixture.fx.revision(), before)
        self.assertEqual(len(self.fixture.planner_calls), 1)
        self.assertEqual(self.fixture.registry.dispatch_control()['dispatch_mode'], 'PAUSED')
        self.assertEqual(self.fixture.registry.active_attempt_runtimes(), ())

    def test_prepare_rejects_live_stopped_and_expired_authorizations(self):
        coordinator = self.coordinator(prepare=True)
        coordinator.tick()
        self.fixture.seconds += 1
        coordinator.tick()
        self.fixture.fx.start()
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_PREPARATION_NOT_AUTHORIZED'):
            coordinator.tick()
        self.fixture.fx.stop(seconds=60)
        with self.assertRaisesRegex(RegistryConflict, 'DELIVERY_PREPARATION_NOT_AUTHORIZED'):
            coordinator.tick()
        self.fixture.fx.authorize(run_id='run-2')
        fresh = self.coordinator(prepare=True, run_id='run-2')
        self.fixture.seconds = 3601
        with self.assertRaisesRegex(RegistryConflict, 'RUN_DEADLINE_REACHED'):
            fresh.tick()

    def test_prepare_does_not_execute_approved_only_integration(self):
        self.fixture.tick()
        self.fixture.tick()
        source = self.fixture.implement()
        self.fixture.tick(seconds=30)
        self.fixture.fx.finish_review(source)
        self.fixture.fx.stop(seconds=60)
        self.fixture.fx.authorize(run_id='run-2')
        coordinator = self.coordinator(prepare=True, run_id='run-2')
        before = self.fixture.fx.revision()
        with patch.object(coordinator, '_integrate') as integrate:
            result = coordinator.tick()
        integrate.assert_not_called()
        self.assertEqual(result['results'][0], {'feature_id': 'FEATURE-1', 'action': 'INTEGRATE', 'state': 'WAITING'})
        self.assertEqual(self.fixture.fx.revision(), before)

    def test_prepare_can_plan_bounded_correction_after_prior_run_rejected_review(self):
        self.fixture.tick()
        self.fixture.tick()
        source = self.fixture.implement()
        self.fixture.tick(seconds=30)
        self.fixture.fx.finish_review(source, verdict=ReviewOutcomeState.CHANGES_REQUESTED)
        self.fixture.fx.stop(seconds=60)
        self.fixture.fx.authorize(run_id='run-2')
        coordinator = self.coordinator(prepare=True, run_id='run-2')
        result = coordinator.tick()
        self.assertEqual(result['results'][0], {'feature_id': 'FEATURE-1', 'action': 'REPAIR', 'state': 'OBSERVED'})
        self.assertEqual(self.fixture.registry.delivery_snapshot(run_id='run-2')['features'][0]['next_action'], 'PROJECT')
        self.assertEqual(self.fixture.registry.dispatch_control()['dispatch_mode'], 'PAUSED')
        self.assertEqual(self.fixture.registry.active_attempt_runtimes(), ())

    def test_prepare_recovers_only_prior_planning_and_projection_actions(self):
        coordinator = self.coordinator(prepare=True)
        feature = coordinator.snapshot()['features'][0]
        action = coordinator._reserve(feature, 'PLAN', {'generation': 0, 'base_commit': self.fixture.fx.base})
        result = coordinator.tick()
        self.assertEqual(result['results'][0]['action'], 'RECONCILE_ACTION')
        self.assertEqual(coordinator.snapshot()['records']['action:' + action['action_id']]['state'], 'FAILED')
        self.assertEqual(self.fixture.planner_calls, [])
        coordinator.tick()
        feature = coordinator.snapshot()['features'][0]
        action = coordinator._reserve(feature, 'PROJECT', {
            'plan_action_id': feature['prepared_plan']['action_id'], 'generation': feature['generation']})
        result = coordinator.tick()
        self.assertEqual(result['results'][0], {'feature_id': 'FEATURE-1', 'action': 'RECONCILE_ACTION', 'state': 'OBSERVED'})
        self.assertEqual(coordinator.snapshot()['records']['action:' + action['action_id']]['state'], 'SUCCEEDED')
        self.assertEqual(coordinator.snapshot()['features'][0]['next_action'], 'WAIT_IMPLEMENTATION')


if __name__ == '__main__':
    unittest.main()
