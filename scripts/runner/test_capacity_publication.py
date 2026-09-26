"""Collector output must be accepted by the runner's real usage consumer."""
import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock

from runner import RegistryLeaseMonitor, write_collected_usage
from usage_policy import validate_usage
from scripts.factory_registry.codex_capacity import normalize_buckets


class CapacityPublicationTests(unittest.TestCase):
    def test_roundtrip_preserves_other_accounts_and_original_sample_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'usage.json'
            preserved = {'reviewer': {'default': {'provider': 'anthropic', 'model': 'sonnet',
                'used_percent': 10, 'observed_at': '2026-09-26T10:00:00Z'}}}
            path.write_text(json.dumps(preserved))
            sample = {'ordinary_usage_allowed': True, 'account_identity_sha256': 'pool-a',
                'observed_at': '2026-09-26T10:01:00Z',
                'primary': {'usedPercent': 11, 'windowDurationMins': 300},
                'secondary': {'usedPercent': 20, 'windowDurationMins': 10080}}
            config = {'agents': {'codex-a': {'model': 'gpt-5.6-terra', 'account': 'agent-a',
                'capacity_scopes': ['short_window', 'weekly_window']}}}
            write_collected_usage(path, config, [{'worker_id': 'codex-a',
                'observations': normalize_buckets('codex-a', sample)}])
            result = validate_usage(json.loads(path.read_text()))
            self.assertEqual(result['reviewer'], validate_usage(preserved)['reviewer'])
            self.assertEqual(set(result['codex-a']['agent-a']['scopes']), {'short_window', 'weekly_window'})
            self.assertEqual(result['codex-a']['agent-a']['scopes']['short_window']['observed_at'],
                '2026-09-26T10:01:00+00:00')

    def test_busy_attempt_monitor_refreshes_capacity_separately_from_renewal(self):
        control, capacity = Mock(), Mock()
        monitor = RegistryLeaseMonitor(control, 'attempt', 'lease', 300,
            worker_id='codex-a', capacity_refresh=capacity)
        monitor.check()
        control.renew_runtime.assert_called_once()
        control.observe_worker_heartbeat.assert_called_once_with('codex-a')
        capacity.assert_called_once_with()

    def test_provider_signal_publishes_without_fabricating_a_percentage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'usage.json'
            config = {'agents': {'claude': {'model': 'sonnet', 'account': 'review',
                'capacity_mode': 'provider_signal', 'capacity_scopes': ['provider_signal']}}}
            observation = {'worker_id': 'claude', 'observed_at': '2026-09-26T10:01:00Z',
                'consumed_percent': None, 'reset_at': None, 'provider_diagnostics': {
                    'capacity_mode': 'provider_signal', 'capacity_scope': 'provider_signal',
                    'service_state': 'unhealthy', 'authentication_state': 'valid',
                    'live_invocation_state': 'failed', 'limit_signal': 'RATE_LIMIT'}}
            write_collected_usage(path, config, [{'worker_id': 'claude', 'observations': (observation,)}])
            result = validate_usage(json.loads(path.read_text()))
            self.assertEqual(result['claude']['review']['limit_signal'], 'RATE_LIMIT')

    def test_failed_collection_does_not_redate_existing_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'usage.json'
            prior = {'workers': {'codex-a': {'agent-a': {'provider': 'openai', 'model': 'gpt',
                'capacity_mode': 'percentage', 'scopes': {'short_window': {
                    'used_percent': 10, 'observed_at': '2026-09-26T10:00:00Z'}}}}}}
            path.write_text(json.dumps(prior))
            config = {'agents': {'codex-a': {'model': 'gpt', 'account': 'agent-a'}}}
            write_collected_usage(path, config, [{'worker_id': 'codex-a', 'observations': (),
                                                  'error_class': 'CapacityCollectorError'}])
            result = validate_usage(json.loads(path.read_text()))
            self.assertEqual(result['codex-a']['agent-a']['scopes']['short_window']['observed_at'],
                             '2026-09-26T10:00:00+00:00')

    def test_registry_only_alias_does_not_block_configured_usage_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'usage.json'
            measured_at = '2026-09-26T10:01:00Z'
            percentage = lambda worker_id: ({
                'worker_id': worker_id, 'observed_at': measured_at,
                'consumed_percent': 11, 'reset_at': None,
                'provider_diagnostics': {
                    'capacity_mode': 'percentage', 'capacity_scope': 'short_window',
                    'capacity_pool': 'verified-account-hash',
                },
            },)
            claude = ({
                'worker_id': 'claude', 'observed_at': measured_at,
                'consumed_percent': None, 'reset_at': None,
                'provider_diagnostics': {
                    'capacity_mode': 'provider_signal', 'capacity_scope': 'provider_signal',
                    'service_state': 'healthy', 'authentication_state': 'valid',
                    'live_invocation_state': 'succeeded', 'limit_signal': 'NONE',
                },
            },)
            config = {'agents': {
                'codex-a': {'model': 'gpt-5.6-terra', 'account': 'agent-a',
                            'capacity_scopes': ['short_window']},
                'codex-b': {'model': 'gpt-5.6-terra', 'account': 'agent-b',
                            'capacity_scopes': ['short_window']},
                'claude': {'model': 'sonnet', 'account': 'review',
                           'capacity_mode': 'provider_signal'},
            }}
            write_collected_usage(path, config, [
                {'worker_id': 'codex-a', 'observations': percentage('codex-a')},
                {'worker_id': 'codex-b', 'observations': percentage('codex-b')},
                {'worker_id': 'orchestra-agent-b',
                 'observations': percentage('orchestra-agent-b')},
                {'worker_id': 'claude', 'observations': claude},
            ])
            published = json.loads(path.read_text())['workers']
            self.assertEqual(set(published), {'codex-a', 'codex-b', 'claude'})
            self.assertNotIn('orchestra-agent-b', published)
            self.assertEqual(
                published['codex-a']['agent-a']['scopes']['short_window']['observed_at'],
                measured_at,
            )
            self.assertEqual(
                published['codex-b']['agent-b']['scopes']['short_window']['observed_at'],
                measured_at,
            )
            self.assertEqual(published['claude']['review']['observed_at'], measured_at)
