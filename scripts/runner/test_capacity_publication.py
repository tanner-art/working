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
