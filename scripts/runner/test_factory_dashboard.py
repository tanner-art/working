import http.client
import json
import pathlib
import tempfile
import threading
import time
import unittest

import factory_dashboard as fd


def write_json(path, data):
    path.write_text(json.dumps(data))


def write_lines(path, lines):
    path.write_text('\n'.join(json.dumps(line) if not isinstance(line, str) else line for line in lines) + '\n')


class RedactionTests(unittest.TestCase):
    def test_usage_markup_matches_api_worker_schema(self):
        markup = fd.HTML_PATH.read_text(encoding='utf-8')
        self.assertIn('usage.workers', markup)
        self.assertNotIn('usage.accounts', markup)
        for field in ('a.worker', 'a.account', 'a.used_percent', 'a.observed_at'):
            self.assertIn(field, markup)

    def test_report_redacts_config_and_state_paths(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'private-host-state'
            state.mkdir()
            report = fd.build_report('/Users/alice/private/config.json', {'state': str(state)}, now=1000.0)
            dumped = json.dumps(report)
            self.assertIsNone(report['config_path'])
            self.assertIsNone(report['state_dir'])
            self.assertNotIn('/Users/alice/private/config.json', dumped)
            self.assertNotIn(str(state), dumped)

    def test_report_sanitizes_issue_and_worker_errors(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'issue-1.json', {
                'issue': 1, 'status': 'failed', 'agent': 'codex-a', 'time': 900.0,
                'error': 'pnpm failed at /Users/alice/repo; token https://host.internal/x?secret=yes',
            })
            report = fd.build_report('cfg.json', {'state': str(state), 'agents': {'codex-a': {}}}, now=1000.0)
            dumped = json.dumps(report)
            self.assertEqual(report['issues'][0]['error'], 'validation failed')
            self.assertEqual(report['workers'][0]['last_failure']['error'], 'validation failed')
            self.assertNotIn('/Users/alice/repo', dumped)
            self.assertNotIn('host.internal', dumped)
            self.assertNotIn('secret=yes', dumped)

    def test_only_canonical_https_github_pr_urls_are_retained(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'issue-1.json', {
                'issue': 1, 'status': 'review', 'pr': 'https://github.com/acme/app/pull/7?token=secret#top',
            })
            write_json(state / 'issue-2.json', {
                'issue': 2, 'status': 'review', 'pr': 'https://evil.example/acme/app/pull/8',
            })
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            self.assertEqual(report['issues'][0]['pr'], 'https://github.com/acme/app/pull/7')
            self.assertIsNone(report['issues'][1]['pr'])
            self.assertNotIn('token=secret', json.dumps(report))

    def test_path_like_display_identifiers_become_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            config = {'state': str(state), 'agents': {
                '/Users/alice/worker': {
                    'provider': '/opt/provider', 'model': 'gpt-5-codex', 'label': '/private/label'
                }
            }}
            report = fd.build_report('cfg.json', config, now=1000.0)
            self.assertEqual(report['workers'], [])
            write_json(state / 'usage.json', {
                '/Users/alice/worker': {'provider': '/opt/provider', 'model': '/private/model', 'used_percent': 10}
            })
            usage = fd.load_usage(state, fd.usage_policy({}))
            self.assertEqual(usage['workers'][0]['worker'], 'unknown-worker')
            self.assertIsNone(usage['workers'][0]['provider'])
            self.assertIsNone(usage['workers'][0]['model'])

    def test_report_never_includes_agent_command_or_env(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            config = {
                'state': str(state),
                'repo': '/Users/someone/secret-repo-path',
                'gh': '/usr/bin/gh',
                'git': '/usr/bin/git',
                'allowed_authors': ['someone'],
                'agents': {
                    'codex-a': {
                        'provider': 'openai',
                        'model': 'gpt-5-codex',
                        'command': ['/opt/homebrew/bin/codex', '--secret-flag'],
                        'env': {'CODEX_HOME': '/Users/someone/.codex-a', 'OPENAI_API_KEY': 'sk-should-not-leak'},
                    }
                },
            }
            report = fd.build_report('cfg.json', config, now=1000.0)
            dumped = json.dumps(report)
            for forbidden in ('secret-flag', 'sk-should-not-leak', 'CODEX_HOME', '/opt/homebrew/bin/codex',
                               'secret-repo-path', '/usr/bin/gh', 'allowed_authors'):
                self.assertNotIn(forbidden, dumped)
            self.assertEqual(report['workers'][0]['provider'], 'openai')
            self.assertEqual(report['workers'][0]['model'], 'gpt-5-codex')

    def test_report_never_includes_log_file_contents_or_paths(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            secret_marker = 'THIS_IS_LOG_CONTENT_MARKER'
            (state / 'issue-1-999.log').write_text(secret_marker)
            write_json(state / 'issue-1.json', {
                'issue': 1, 'status': 'failed', 'agent': 'codex-b',
                'log': str(state / 'issue-1-999.log'),
                'worktree': '/Users/someone/worktrees/issue-1',
            })
            config = {'state': str(state)}
            report = fd.build_report('cfg.json', config, now=1000.0)
            dumped = json.dumps(report)
            self.assertNotIn(secret_marker, dumped)
            self.assertNotIn('worktrees/issue-1', dumped)

    def test_report_never_includes_usage_json_extra_fields(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'usage.json', {
                'codex-a': {
                    'provider': 'openai', 'model': 'gpt-5-codex', 'used_percent': 10,
                    'observed_at': '2026-01-01T00:00:00Z',
                    'api_key': 'sk-leak-me-not', 'secret': 'nope',
                }
            })
            config = {'state': str(state)}
            report = fd.build_report('cfg.json', config, now=1000.0)
            dumped = json.dumps(report)
            self.assertNotIn('sk-leak-me-not', dumped)
            self.assertNotIn('secret', dumped)

    def test_canonical_nested_usage_preserves_worker_and_account_rows(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'usage.json', {'workers': {
                'codex-a': {
                    'primary': {'provider': 'openai', 'model': 'gpt-5-codex', 'used_percent': 10,
                                'observed_at': '1970-01-01T00:16:20Z'},
                    'fallback': {'provider': 'openai', 'model': 'gpt-5-mini', 'used_percent': 75,
                                 'observed_at': '1970-01-01T00:16:10Z'},
                },
            }})
            workers = fd.build_report('cfg.json', {'state': str(state), 'usage_policy': {'stale_after_seconds': 600}}, now=1000.0)['usage']['workers']
            self.assertEqual([(item['worker'], item['account']) for item in workers],
                             [('codex-a', 'fallback'), ('codex-a', 'primary')])
            self.assertEqual([item['state'] for item in workers], ['slow', 'green'])

    def test_stale_or_future_usage_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'usage.json', {'workers': {
                'codex-a': {
                    'stale': {'provider': 'openai', 'model': 'gpt-5-codex', 'used_percent': 10,
                              'observed_at': '1970-01-01T00:00:00Z'},
                    'future': {'provider': 'openai', 'model': 'gpt-5-codex', 'used_percent': 10,
                               'observed_at': '1970-01-01T00:30:00Z'},
                },
            }})
            workers = fd.build_report('cfg.json', {'state': str(state), 'usage_policy': {'stale_after_seconds': 600}}, now=1000.0)['usage']['workers']
            self.assertEqual({item['account']: item['state'] for item in workers},
                             {'stale': 'unknown', 'future': 'unknown'})


class MissingOrCorruptDataTests(unittest.TestCase):
    def test_sanitized_queue_snapshot_supplies_staged_counts_and_age(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'queue.json', {'entries': [
                {'number': 1, 'title': 'Ready', 'agent': 'codex-a', 'readiness': True, 'status': 'ready', 'created_at': '1970-01-01T00:00:10Z', 'dependencies': {'items': [], 'count': 0}},
                {'number': 2, 'title': 'Review', 'agent': 'codex-b', 'readiness': False, 'status': 'review', 'created_at': '1970-01-01T00:00:20Z', 'dependencies': {'items': [4], 'count': 1}},
                {'number': 3, 'title': 'Running', 'agent': 'claude', 'readiness': False, 'status': 'running', 'created_at': None, 'dependencies': {'items': [], 'count': 0}},
            ]})
            report = fd.build_report('cfg.json', {'state': str(state)}, now=100.0)
            queue = report['queue']
            self.assertEqual(queue['source'], 'queue.json')
            self.assertEqual(queue['staged_count'], 3)
            self.assertEqual(queue['ready_count'], 1)
            self.assertEqual(queue['review_count'], 1)
            self.assertEqual(queue['queue_age_seconds'], 90.0)

    def test_unassignable_ready_snapshot_entry_does_not_count_as_ready(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'queue.json', {'entries': [
                {'number': 1, 'title': 'Unassigned', 'agent': None, 'readiness': False, 'status': 'ready', 'created_at': None, 'dependencies': {'items': [], 'count': 0}},
            ]})
            queue = fd.build_report('cfg.json', {'state': str(state)}, now=100.0)['queue']
            self.assertEqual(queue['source'], 'queue.json')
            self.assertEqual(queue['staged_count'], 1)
            self.assertEqual(queue['ready_count'], 0)

    def test_malformed_queue_entries_fall_back_to_issue_records(self):
        for malformed in (
            {'number': 1, 'title': 'Bad status', 'agent': 'codex-a', 'readiness': False, 'status': 'invented', 'created_at': None, 'dependencies': {'items': [], 'count': 0}},
            {'number': 2, 'title': 'Bad dependencies', 'agent': 'codex-a', 'readiness': True, 'status': 'ready', 'created_at': None, 'dependencies': {'items': [2, 2], 'count': 2}},
        ):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as d:
                state = pathlib.Path(d) / 'state'
                state.mkdir()
                write_json(state / 'queue.json', {'entries': [malformed]})
                write_json(state / 'issue-4.json', {'issue': 4, 'status': 'ready', 'time': 90.0})
                queue = fd.build_report('cfg.json', {'state': str(state)}, now=100.0)['queue']
                self.assertEqual(queue['source'], 'issue-records')
                self.assertIn('corrupt', queue['snapshot_error'])
                self.assertEqual(queue['ready_count'], 1)

    def test_duplicate_snapshot_issue_numbers_fall_back_without_inflated_counts(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            entry = {'number': 1, 'title': 'Duplicate', 'agent': 'codex-a', 'readiness': True, 'status': 'ready', 'created_at': '1970-01-01T00:00:10Z', 'dependencies': {'items': [], 'count': 0}}
            write_json(state / 'queue.json', {'entries': [entry, entry]})
            write_json(state / 'issue-4.json', {'issue': 4, 'status': 'ready', 'time': 90.0})
            queue = fd.build_report('cfg.json', {'state': str(state)}, now=100.0)['queue']
            self.assertEqual(queue['source'], 'issue-records')
            self.assertEqual(queue['staged_count'], 1)
            self.assertEqual(queue['ready_count'], 1)

    def test_unparseable_snapshot_timestamp_falls_back_without_inaccurate_age(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'queue.json', {'entries': [
                {'number': 1, 'title': 'Bad timestamp', 'agent': 'codex-a', 'readiness': True, 'status': 'ready', 'created_at': 'not-an-iso-timestamp', 'dependencies': {'items': [], 'count': 0}},
            ]})
            write_json(state / 'issue-4.json', {'issue': 4, 'status': 'ready', 'time': 80.0})
            queue = fd.build_report('cfg.json', {'state': str(state)}, now=100.0)['queue']
            self.assertEqual(queue['source'], 'issue-records')
            self.assertEqual(queue['queue_age_seconds'], 20.0)

    def test_corrupt_queue_snapshot_falls_back_to_issue_records(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            (state / 'queue.json').write_text('{bad json')
            write_json(state / 'issue-4.json', {'issue': 4, 'status': 'ready', 'time': 90.0})
            report = fd.build_report('cfg.json', {'state': str(state)}, now=100.0)
            self.assertEqual(report['queue']['source'], 'issue-records')
            self.assertIn('corrupt', report['queue']['snapshot_error'])
            self.assertEqual(report['queue']['ready_count'], 1)

    def test_everything_missing_degrades_to_unknown(self):
        report = fd.build_report('cfg.json', {'state': '/nonexistent/state/dir'}, now=1000.0)
        self.assertFalse(report['state_dir_found'])
        self.assertFalse(report['heartbeat']['found'])
        self.assertEqual(report['queue']['total_records'], 0)
        self.assertIsNone(report['utilization']['total']['value'])
        self.assertIsNone(report['utilization']['nine_day']['value'])
        self.assertIsNone(report['longest_blocked_duration']['value'])
        self.assertFalse(report['usage']['found'])
        self.assertIsNotNone(report['usage']['note'])
        self.assertEqual(report['workers'], [])

    def test_corrupt_heartbeat_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            (state / 'heartbeat.json').write_text('{not valid json')
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            self.assertTrue(report['heartbeat']['found'])
            self.assertIn('corrupt', report['heartbeat']['error'])

    def test_corrupt_issue_record_counted_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            (state / 'issue-1.json').write_text('{not valid json')
            write_json(state / 'issue-2.json', {'issue': 2, 'status': 'review', 'agent': 'claude'})
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            self.assertEqual(report['queue']['corrupt_records'], 1)
            self.assertEqual(len(report['issues']), 1)

    def test_corrupt_events_line_is_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            (state / 'events.jsonl').write_text(
                '{"timestamp": 1000.0, "status": "agent", "agent": "codex-a"}\n'
                'not json at all\n'
                '{"timestamp": "not-a-number", "status": "agent"}\n'
                '{"status": "agent"}\n'
            )
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1010.0)
            self.assertTrue(report['utilization']['events_found'])
            self.assertEqual(report['utilization']['events_corrupt_lines'], 3)

    def test_missing_events_jsonl_explains_what_is_needed(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            self.assertFalse(report['utilization']['events_found'])
            self.assertIn('events.jsonl', report['utilization']['total']['reason'])
            self.assertIn('events.jsonl', report['longest_blocked_duration']['reason'])

    def test_corrupt_usage_json_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            (state / 'usage.json').write_text('{not valid json')
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            self.assertTrue(report['usage']['found'])
            self.assertIn('corrupt', report['usage']['error'])

    def test_usage_json_bad_account_entries_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'usage.json', {
                'codex-a': {'provider': 'openai', 'model': 'gpt-5-codex', 'used_percent': 50,
                            'observed_at': '2026-01-01T00:00:00Z'},
                'codex-b': 'not-a-dict',
                '': {'provider': 'openai', 'used_percent': 10, 'observed_at': '2026-01-01T00:00:00Z'},
            })
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            self.assertEqual(len(report['usage']['workers']), 1)
            self.assertEqual(report['usage']['corrupt_workers'], 2)

    def test_missing_diff_stat_explains_what_is_needed(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'issue-5.json', {'issue': 5, 'status': 'review', 'agent': 'codex-a', 'time': 900.0})
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            issue = report['issues'][0]
            self.assertIsNone(issue['diff_stat'])
            self.assertIn('issue #5', issue['diff_stat_reason'])


class UtilizationMathTests(unittest.TestCase):
    def test_fully_busy_window_is_one_full_worker(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 0.0, 'status': 'agent', 'agent': 'codex-a'},
        ]}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        self.assertAlmostEqual(result['value'], 1.0)
        self.assertAlmostEqual(result['percent_of_capacity'], 1.0 / 3.0)

    def test_fully_idle_window_is_zero_active_workers(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 0.0, 'status': 'idle', 'agent': 'codex-a'},
        ]}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        self.assertAlmostEqual(result['value'], 0.0)
        self.assertAlmostEqual(result['percent_of_capacity'], 0.0)

    def test_mixed_intervals_compute_exact_average(self):
        # idle [0,10), agent [10,40) -> busy 30s, idle [40,50) -> busy 0, agent [50,100) -> busy 50s
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 0.0, 'status': 'idle', 'agent': 'codex-a'},
            {'time': 10.0, 'status': 'agent', 'agent': 'codex-a'},
            {'time': 40.0, 'status': 'idle', 'agent': 'codex-a'},
            {'time': 50.0, 'status': 'validation', 'agent': 'codex-a'},
        ]}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        # busy seconds = (40-10) + (100-50) = 80 out of 100
        self.assertAlmostEqual(result['value'], 0.8)
        self.assertAlmostEqual(result['percent_of_capacity'], 0.8 / 3.0)

    def test_unsorted_events_are_sorted_before_computing(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 40.0, 'status': 'idle', 'agent': 'codex-a'},
            {'time': 0.0, 'status': 'agent', 'agent': 'codex-a'},
        ]}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        # agent [0,40) busy=40, idle [40,100) busy=0 -> 40/100
        self.assertAlmostEqual(result['value'], 0.4)

    def test_window_before_first_event_is_clamped_to_first_event(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 50.0, 'status': 'agent', 'agent': 'codex-a'},
        ]}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        # effective window is [50,100), fully busy
        self.assertAlmostEqual(result['value'], 1.0)
        self.assertEqual(result['window_start'], 50.0)

    def test_window_entirely_before_first_event_is_unknown(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 500.0, 'status': 'agent', 'agent': 'codex-a'},
        ]}
        result = fd.average_active_workers_for_window(
            events_result, now=1000.0, window_start=0.0, window_end=100.0, total_workers=3)
        self.assertIsNone(result['value'])
        self.assertIn('window', result['reason'])

    def test_no_events_file_is_unknown_with_reason(self):
        events_result = {'found': False, 'error': None, 'corrupt_lines': 0, 'events': []}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        self.assertIsNone(result['value'])
        self.assertIn('events.jsonl', result['reason'])

    def test_empty_events_file_is_unknown_with_reason(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': []}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        self.assertIsNone(result['value'])
        self.assertIn('empty', result['reason'])

    def test_events_error_propagates_as_unknown(self):
        events_result = {'found': True, 'error': 'unreadable: OSError', 'corrupt_lines': 0, 'events': []}
        result = fd.average_active_workers_for_window(
            events_result, now=100.0, window_start=0.0, window_end=100.0, total_workers=3)
        self.assertIsNone(result['value'])
        self.assertIn('unreadable', result['reason'])

    def test_last_event_extends_to_now(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 0.0, 'status': 'agent', 'agent': 'codex-a'},
        ]}
        result = fd.average_active_workers_for_window(
            events_result, now=60.0, window_start=0.0, window_end=60.0, total_workers=3)
        self.assertAlmostEqual(result['value'], 1.0)

    def test_end_to_end_nine_day_and_total_via_build_report(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            now = 100.0 * 86400  # far enough that a 9-day window is well inside history
            events = [
                {'timestamp': now - (20 * 86400), 'status': 'idle', 'agent': 'codex-a'},
                {'timestamp': now - (5 * 86400), 'status': 'agent', 'agent': 'codex-a'},  # busy last 5 days
            ]
            write_lines(state / 'events.jsonl', events)
            report = fd.build_report('cfg.json', {'state': str(state)}, now=now, utilization_window_days=9)
            nine_day = report['utilization']['nine_day']
            # busy 5 of the last 9 days, against a default capacity of 3 workers
            self.assertAlmostEqual(nine_day['value'], 5.0 / 9.0, places=6)
            self.assertAlmostEqual(nine_day['percent_of_capacity'], (5.0 / 9.0) / 3.0, places=6)
            total = report['utilization']['total']
            # busy 5 of the full 20-day history
            self.assertAlmostEqual(total['value'], 5.0 / 20.0, places=6)


class ProducerIntegrationTests(unittest.TestCase):
    def test_overlapping_worker_intervals_average_two_active_workers(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            now = 1_000_000.0
            events = [
                {'timestamp': now - 100.0, 'status': 'agent', 'agent': 'codex-a'},
                {'timestamp': now - 100.0, 'status': 'agent', 'agent': 'codex-b'},
            ]
            write_lines(state / 'events.jsonl', events)
            config = {'state': str(state), 'agents': {'codex-a': {}, 'codex-b': {}}}
            report = fd.build_report('cfg.json', config, now=now)
            total = report['utilization']['total']
            self.assertAlmostEqual(total['value'], 2.0, places=6)
            self.assertAlmostEqual(total['percent_of_capacity'], 1.0, places=6)

    def test_canonical_usage_percent_thresholds_slow_and_stop(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'usage.json', {
                'codex-a': {'provider': 'openai', 'model': 'gpt-5-codex',
                            'used_percent': 70.0, 'observed_at': '1970-01-01T00:16:00Z'},
                'codex-b': {'provider': 'openai', 'model': 'gpt-5-codex',
                            'used_percent': 80.0, 'observed_at': '1970-01-01T00:16:00Z'},
            })
            report = fd.build_report('cfg.json', {'state': str(state)}, now=1000.0)
            workers = {w['worker']: w for w in report['usage']['workers']}
            self.assertEqual(workers['codex-a']['state'], 'slow')
            self.assertEqual(workers['codex-b']['state'], 'stop')


class LongestBlockedDurationTests(unittest.TestCase):
    def test_no_events_is_unknown(self):
        events_result = {'found': False, 'error': None, 'corrupt_lines': 0, 'events': []}
        result = fd.longest_blocked_duration(events_result, now=100.0)
        self.assertIsNone(result['value'])
        self.assertIn('events.jsonl', result['reason'])

    def test_no_blocked_events_is_unknown(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 0.0, 'status': 'agent', 'agent': 'codex-a'},
            {'time': 10.0, 'status': 'idle', 'agent': 'codex-a'},
        ]}
        result = fd.longest_blocked_duration(events_result, now=20.0)
        self.assertIsNone(result['value'])
        self.assertIn('waiting/blocked', result['reason'])

    def test_finds_the_longest_of_several_blocked_intervals(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 0.0, 'status': 'waiting', 'agent': 'codex-a'},   # blocked for 5s
            {'time': 5.0, 'status': 'agent', 'agent': 'codex-a'},
            {'time': 10.0, 'status': 'waiting', 'agent': 'codex-a'},  # blocked for 40s (longest)
            {'time': 50.0, 'status': 'review', 'agent': 'codex-a'},
        ]}
        result = fd.longest_blocked_duration(events_result, now=200.0)
        self.assertAlmostEqual(result['value'], 40.0)

    def test_still_blocked_extends_to_now(self):
        events_result = {'found': True, 'error': None, 'corrupt_lines': 0, 'events': [
            {'time': 0.0, 'status': 'waiting', 'agent': 'codex-a'},
        ]}
        result = fd.longest_blocked_duration(events_result, now=75.0)
        self.assertAlmostEqual(result['value'], 75.0)


class DiffStatTests(unittest.TestCase):
    def test_prefers_record_level_diff_stat(self):
        record = {'issue': 1, 'diff_stat': {'additions': 3, 'deletions': 1, 'files_changed': 2}}
        stat, reason = fd._diff_stat_for_issue(record, events=[])
        self.assertEqual(stat, {'additions': 3, 'deletions': 1, 'files_changed': 2})
        self.assertIsNone(reason)

    def test_falls_back_to_latest_matching_event(self):
        record = {'issue': 7, 'diff_stat': None}
        events = [
            {'time': 1.0, 'issue': 7, 'diff_stat': {'additions': 1, 'deletions': 0, 'files_changed': 1}},
            {'time': 2.0, 'issue': 7, 'diff_stat': {'additions': 5, 'deletions': 2, 'files_changed': 3}},
            {'time': 3.0, 'issue': 8, 'diff_stat': {'additions': 99, 'deletions': 99, 'files_changed': 99}},
        ]
        stat, reason = fd._diff_stat_for_issue(record, events)
        self.assertEqual(stat, {'additions': 5, 'deletions': 2, 'files_changed': 3})
        self.assertIsNone(reason)

    def test_unknown_when_nothing_available(self):
        record = {'issue': 9, 'diff_stat': None}
        stat, reason = fd._diff_stat_for_issue(record, events=[])
        self.assertIsNone(stat)
        self.assertIn('issue #9', reason)


class CompletionTimingTests(unittest.TestCase):
    def test_review_issue_has_fixed_completion_time_without_running_elapsed(self):
        record = {'issue': 2, 'status': 'review', 'time': 500.0, 'agent': 'claude',
                  'branch': None, 'commit': 'abc123', 'pr': 'https://example.invalid/pr/2',
                  'error': None, 'diff_stat': None}
        issue = fd.build_issue_views({2: record}, events=[], now=10_000.0)[0]
        self.assertIsNone(issue['elapsed_seconds'])
        self.assertIsNone(issue['elapsed_human'])
        self.assertEqual(issue['completed_at_iso'], '1970-01-01T00:08:20+00:00')

    def test_review_worker_preserves_completion_metadata_without_elapsed_accrual(self):
        agent_defs = {'claude': {'key': 'claude', 'provider': None, 'model': None, 'label': None}}
        records = {2: {'issue': 2, 'status': 'review', 'time': 500.0, 'agent': 'claude',
                       'branch': None, 'commit': 'abc123', 'pr': 'https://example.invalid/pr/2',
                       'error': None, 'diff_stat': None}}
        worker = fd.build_worker_views(agent_defs, records, events=[], heartbeat={}, now=10_000.0)[0]
        self.assertEqual(worker['state'], 'review')
        self.assertIsNone(worker['elapsed_seconds'])
        self.assertEqual(worker['last_completion']['issue'], 2)
        self.assertEqual(worker['last_completion']['commit'], 'abc123')


class WorkerStateTests(unittest.TestCase):
    def test_active_worker_shows_current_issue_and_elapsed(self):
        agent_defs = {'codex-a': {'key': 'codex-a', 'provider': 'openai', 'model': 'gpt-5-codex', 'label': None}}
        records = {5: {'issue': 5, 'status': 'agent', 'time': 900.0, 'agent': 'codex-a',
                       'branch': None, 'commit': None, 'pr': None, 'error': None, 'diff_stat': None}}
        workers = fd.build_worker_views(agent_defs, records, events=[], heartbeat={}, now=1000.0)
        self.assertEqual(workers[0]['state'], 'active')
        self.assertEqual(workers[0]['current_issue'], 5)
        self.assertAlmostEqual(workers[0]['elapsed_seconds'], 100.0)

    def test_review_worker_state(self):
        agent_defs = {'claude': {'key': 'claude', 'provider': None, 'model': None, 'label': None}}
        records = {2: {'issue': 2, 'status': 'review', 'time': 500.0, 'agent': 'claude',
                       'branch': None, 'commit': 'abc123', 'pr': 'https://example.invalid/pr/2',
                       'error': None, 'diff_stat': None}}
        workers = fd.build_worker_views(agent_defs, records, events=[], heartbeat={}, now=600.0)
        self.assertEqual(workers[0]['state'], 'review')

    def test_failed_worker_is_idle_with_last_failure(self):
        agent_defs = {'codex-b': {'key': 'codex-b', 'provider': None, 'model': None, 'label': None}}
        records = {3: {'issue': 3, 'status': 'failed', 'time': 500.0, 'agent': 'codex-b',
                       'branch': None, 'commit': None, 'pr': None, 'error': 'pnpm check failed (1); see log',
                       'diff_stat': None}}
        workers = fd.build_worker_views(agent_defs, records, events=[], heartbeat={}, now=600.0)
        self.assertEqual(workers[0]['state'], 'idle')
        self.assertEqual(workers[0]['last_failure']['issue'], 3)
        self.assertEqual(workers[0]['last_failure']['error'], 'validation failed')

    def test_worker_with_no_activity_is_idle_with_reason(self):
        agent_defs = {'codex-a': {'key': 'codex-a', 'provider': None, 'model': None, 'label': None}}
        workers = fd.build_worker_views(agent_defs, records={}, events=[], heartbeat={}, now=1000.0)
        self.assertEqual(workers[0]['state'], 'idle')
        self.assertIsNotNone(workers[0]['reason'])

    def test_blocked_state_from_events_overrides_stale_issue_record(self):
        agent_defs = {'codex-a': {'key': 'codex-a', 'provider': None, 'model': None, 'label': None}}
        records = {4: {'issue': 4, 'status': 'agent', 'time': 100.0, 'agent': 'codex-a',
                       'branch': None, 'commit': None, 'pr': None, 'error': None, 'diff_stat': None}}
        events = [{'time': 200.0, 'status': 'waiting', 'agent': 'codex-a', 'issue': 4}]
        workers = fd.build_worker_views(agent_defs, records, events, heartbeat={}, now=300.0)
        self.assertEqual(workers[0]['state'], 'blocked')
        self.assertAlmostEqual(workers[0]['elapsed_seconds'], 100.0)


class ValidationResultTests(unittest.TestCase):
    def test_pending_before_validation(self):
        self.assertEqual(fd.validation_result({'status': 'starting', 'commit': None}), 'pending')
        self.assertEqual(fd.validation_result({'status': 'agent', 'commit': None}), 'pending')

    def test_running_during_validation(self):
        self.assertEqual(fd.validation_result({'status': 'validation', 'commit': None}), 'running')

    def test_passed_on_review_or_commit_present(self):
        self.assertEqual(fd.validation_result({'status': 'review', 'commit': 'abc'}), 'passed')
        self.assertEqual(fd.validation_result({'status': 'review', 'commit': None}), 'passed')

    def test_failed_status_is_failed(self):
        self.assertEqual(fd.validation_result({'status': 'failed', 'commit': None}), 'failed')

    def test_failed_status_with_local_commit_is_still_failed(self):
        self.assertEqual(fd.validation_result({'status': 'failed', 'commit': 'local-commit'}), 'failed')


class UsagePolicyTests(unittest.TestCase):
    def test_defaults_when_not_configured(self):
        policy = fd.usage_policy({})
        self.assertEqual(policy['slowdown_threshold_pct'], 70.0)
        self.assertEqual(policy['stop_threshold_pct'], 80.0)
        self.assertFalse(policy['stop_threshold_clamped_to_max'])

    def test_config_overrides_defaults(self):
        policy = fd.usage_policy({'usage_policy': {'slowdown_percent': 50, 'stop_percent': 60}})
        self.assertEqual(policy['slowdown_percent'], 50.0)
        self.assertEqual(policy['stop_percent'], 60.0)
        self.assertEqual(policy['slowdown_threshold_pct'], 50.0)
        self.assertEqual(policy['stop_threshold_pct'], 60.0)

    def test_canonical_thresholds_win_over_legacy_aliases(self):
        policy = fd.usage_policy({'usage_policy': {
            'slowdown_percent': 71, 'stop_percent': 79,
            'slowdown_threshold_pct': 11, 'stop_threshold_pct': 12,
        }})
        self.assertEqual(policy['slowdown_percent'], 71.0)
        self.assertEqual(policy['stop_percent'], 79.0)

    def test_legacy_threshold_aliases_remain_supported(self):
        policy = fd.usage_policy({'usage_policy': {'slowdown_threshold_pct': 50, 'stop_threshold_pct': 60}})
        self.assertEqual(policy['slowdown_percent'], 50.0)
        self.assertEqual(policy['stop_percent'], 60.0)

    def test_stop_threshold_is_clamped_to_max_80(self):
        policy = fd.usage_policy({'usage_policy': {'stop_threshold_pct': 95}})
        self.assertEqual(policy['stop_threshold_pct'], 80.0)
        self.assertTrue(policy['stop_threshold_clamped_to_max'])

    def test_cli_overrides_take_precedence_over_config(self):
        policy = fd.usage_policy({'usage_policy': {'slowdown_threshold_pct': 50}}, slowdown_override=65)
        self.assertEqual(policy['slowdown_threshold_pct'], 65.0)

    def test_classify_usage_state(self):
        policy = {'slowdown_threshold_pct': 70.0, 'stop_threshold_pct': 80.0}
        self.assertEqual(fd.classify_usage_state(10, policy), 'green')
        self.assertEqual(fd.classify_usage_state(75, policy), 'slow')
        self.assertEqual(fd.classify_usage_state(85, policy), 'stop')
        self.assertEqual(fd.classify_usage_state(None, policy), 'unknown')
        self.assertEqual(fd.classify_usage_state('not-a-number', policy), 'unknown')


class AgentDefinitionsTests(unittest.TestCase):
    def test_data_driven_from_config_not_hardcoded(self):
        config = {'agents': {'custom-worker': {'provider': 'anthropic', 'model': 'claude-x'}}}
        defs = fd.agent_definitions(config)
        self.assertEqual(defs['custom-worker']['provider'], 'anthropic')
        self.assertEqual(defs['custom-worker']['model'], 'claude-x')

    def test_missing_provider_model_is_unknown_none(self):
        config = {'agents': {'codex-a': {}}}
        defs = fd.agent_definitions(config)
        self.assertIsNone(defs['codex-a']['provider'])
        self.assertIsNone(defs['codex-a']['model'])

    def test_no_agents_configured_is_empty(self):
        self.assertEqual(fd.agent_definitions({}), {})


class FormatDurationTests(unittest.TestCase):
    def test_none_is_none(self):
        self.assertIsNone(fd.format_duration(None))

    def test_seconds_only(self):
        self.assertEqual(fd.format_duration(45), '45s')

    def test_hours_minutes_seconds(self):
        self.assertEqual(fd.format_duration(3725), '1h 2m 5s')

    def test_days(self):
        self.assertEqual(fd.format_duration(90061), '1d 1h 1m 1s')


class HttpRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        state = pathlib.Path(cls.tempdir.name) / 'state'
        state.mkdir()
        write_json(state / 'heartbeat.json', {'time': time.time(), 'pid': 1, 'status': 'idle'})
        write_json(state / 'issue-1.json', {'issue': 1, 'status': 'review', 'agent': 'claude'})
        config = {'state': str(state), 'agents': {'claude': {'provider': 'anthropic', 'model': 'claude-x'}}}
        cls.server = fd.make_server('127.0.0.1', 0, 'cfg.json', config)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tempdir.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            conn.request('GET', path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, resp.getheader('Content-Type'), body
        finally:
            conn.close()

    def test_root_serves_html(self):
        status, content_type, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', content_type)
        self.assertIn(b'Threadline Factory Dashboard', body)

    def test_api_status_serves_valid_json_with_expected_keys(self):
        status, content_type, body = self._get('/api/status')
        self.assertEqual(status, 200)
        self.assertIn('application/json', content_type)
        parsed = json.loads(body)
        for key in ('generated_at', 'heartbeat', 'workers', 'queue', 'issues', 'utilization',
                    'longest_blocked_duration', 'usage', 'capacity_note'):
            self.assertIn(key, parsed)
        self.assertEqual(parsed['workers'][0]['provider'], 'anthropic')
        self.assertIsNone(parsed['config_path'])
        self.assertIsNone(parsed['state_dir'])

    def test_unknown_route_is_404(self):
        status, content_type, body = self._get('/does-not-exist')
        self.assertEqual(status, 404)

    def test_default_bind_host_is_loopback(self):
        parser = fd.build_arg_parser()
        args = parser.parse_args(['--config', 'cfg.json'])
        self.assertEqual(args.host, '127.0.0.1')
        self.assertEqual(args.port, fd.DEFAULT_PORT)


class MainCliTests(unittest.TestCase):
    def test_missing_config_reports_error_without_traceback(self):
        rc = fd.main(['--config', '/nonexistent/config.json'])
        self.assertEqual(rc, 1)


if __name__ == '__main__':
    unittest.main()
