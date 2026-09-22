import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import factory_status as fs


class HeartbeatTests(unittest.TestCase):
    def test_missing_heartbeat_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            result = fs.heartbeat_status(pathlib.Path(d), 180, time_now(1000))
            self.assertFalse(result['found'])
            self.assertIsNone(result['error'])
            self.assertIsNone(result['stale'])

    def test_fresh_heartbeat_is_not_stale(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'heartbeat.json', {'time': 1000.0, 'pid': 123, 'status': 'idle'})
            result = fs.heartbeat_status(state, 180, 1050.0)
            self.assertTrue(result['found'])
            self.assertIsNone(result['error'])
            self.assertEqual(result['status'], 'idle')
            self.assertAlmostEqual(result['age_seconds'], 50.0)
            self.assertFalse(result['stale'])

    def test_old_heartbeat_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'heartbeat.json', {'time': 1000.0, 'pid': 123, 'status': 'polling'})
            result = fs.heartbeat_status(state, 180, 1000.0 + 181)
            self.assertTrue(result['stale'])

    def test_configurable_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'heartbeat.json', {'time': 1000.0, 'pid': 1, 'status': 'idle'})
            self.assertFalse(fs.heartbeat_status(state, 10, 1005.0)['stale'])
            self.assertTrue(fs.heartbeat_status(state, 4, 1005.0)['stale'])

    def test_corrupt_heartbeat_json_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            (state / 'heartbeat.json').write_text('{not valid json')
            result = fs.heartbeat_status(state, 180, 1000.0)
            self.assertTrue(result['found'])
            self.assertIn('corrupt', result['error'])
            self.assertIsNone(result['stale'])

    def test_heartbeat_missing_time_field_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'heartbeat.json', {'pid': 1, 'status': 'idle'})
            result = fs.heartbeat_status(state, 180, 1000.0)
            self.assertTrue(result['found'])
            self.assertIn('corrupt', result['error'])


class IssueRecordSummaryTests(unittest.TestCase):
    def test_missing_state_dir_is_empty_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            missing = pathlib.Path(d) / 'does-not-exist'
            result = fs.issue_record_summary(missing)
            self.assertEqual(result, {'total_records': 0, 'corrupt_records': 0, 'by_status': {}, 'by_agent': {}})

    def test_counts_by_status_and_agent(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'issue-1.json', {'issue': 1, 'status': 'review', 'agent': 'codex-a'})
            write_json(state / 'issue-2.json', {'issue': 2, 'status': 'failed', 'agent': 'codex-b'})
            write_json(state / 'issue-3.json', {'issue': 3, 'status': 'review', 'agent': 'codex-a'})
            result = fs.issue_record_summary(state)
            self.assertEqual(result['total_records'], 3)
            self.assertEqual(result['corrupt_records'], 0)
            self.assertEqual(result['by_status'], {'review': 2, 'failed': 1})
            self.assertEqual(result['by_agent'], {'codex-a': 2, 'codex-b': 1})

    def test_record_without_agent_counts_as_unassigned(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'issue-9.json', {'issue': 9, 'status': 'starting'})
            result = fs.issue_record_summary(state)
            self.assertEqual(result['by_agent'], {'unassigned': 1})

    def test_corrupt_record_is_counted_and_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'issue-1.json', {'issue': 1, 'status': 'review', 'agent': 'claude'})
            (state / 'issue-2.json').write_text('{broken')
            result = fs.issue_record_summary(state)
            self.assertEqual(result['total_records'], 2)
            self.assertEqual(result['corrupt_records'], 1)
            self.assertEqual(result['by_status'], {'review': 1})

    def test_non_issue_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            write_json(state / 'issue-1.json', {'issue': 1, 'status': 'review', 'agent': 'claude'})
            (state / 'runner.lock').write_text('')
            (state / 'issue-1-12345.log').write_text('SECRET_TOKEN=abc123\nsome source code diff')
            (state / 'heartbeat.json').write_text('{}')
            result = fs.issue_record_summary(state)
            self.assertEqual(result['total_records'], 1)


class ConfigTests(unittest.TestCase):
    def test_missing_config_raises_clear_error(self):
        with self.assertRaises(ValueError):
            fs.load_config('/nonexistent/path/config.json')

    def test_corrupt_config_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'config.json'
            path.write_text('{not json')
            with self.assertRaises(ValueError):
                fs.load_config(str(path))

    def test_config_missing_state_field_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'config.json'
            write_json(path, {'repo': '/somewhere'})
            with self.assertRaises(ValueError):
                fs.load_config(str(path))


class UtilizationTests(unittest.TestCase):
    def test_defaults_used_when_agents_missing(self):
        section = fs.utilization_section({}, 9, 2.5)
        self.assertEqual(section['window_days'], 9)
        self.assertEqual(section['target_workers'], 2.5)
        self.assertEqual(section['total_workers'], fs.DEFAULT_UTILIZATION_TOTAL_WORKERS)
        self.assertEqual(section['observed_utilization'], 'unknown')

    def test_total_workers_derived_from_configured_agents(self):
        section = fs.utilization_section({'agents': {'codex-a': {}, 'codex-b': {}, 'claude': {}}}, 9, 2.5)
        self.assertEqual(section['total_workers'], 3)

    def test_never_invents_an_observed_number(self):
        section = fs.utilization_section({'agents': {'codex-a': {}}}, 9, 2.5)
        self.assertEqual(section['observed_utilization'], 'unknown')
        self.assertIsInstance(section['observed_utilization_reason'], str)
        self.assertTrue(section['observed_utilization_reason'])


class BuildReportTests(unittest.TestCase):
    def test_report_over_populated_state_dir(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'heartbeat.json', {'time': 1000.0, 'pid': 1, 'status': 'idle'})
            write_json(state / 'issue-1.json', {'issue': 1, 'status': 'review', 'agent': 'codex-a'})
            config = {'state': str(state), 'agents': {'codex-a': {}, 'codex-b': {}, 'claude': {}}}
            report = fs.build_report('cfg.json', config, now=1010.0)
            self.assertTrue(report['state_dir_found'])
            self.assertFalse(report['heartbeat']['stale'])
            self.assertEqual(report['issues']['total_records'], 1)
            self.assertIn('serial', report['capacity_note'])
            self.assertEqual(report['utilization']['observed_utilization'], 'unknown')

    def test_report_over_missing_state_dir_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            missing_state = pathlib.Path(d) / 'nope'
            config = {'state': str(missing_state)}
            report = fs.build_report('cfg.json', config, now=1010.0)
            self.assertFalse(report['state_dir_found'])
            self.assertFalse(report['heartbeat']['found'])
            self.assertEqual(report['issues']['total_records'], 0)

    def test_report_never_contains_credential_like_keys(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            config = {'state': str(state), 'gh': '/usr/bin/gh', 'github': 'owner/repo'}
            report = fs.build_report('cfg.json', config, now=1010.0)
            dumped = json.dumps(report)
            for forbidden in ('GH_TOKEN', 'GITHUB_TOKEN', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'password'):
                self.assertNotIn(forbidden, dumped)
            self.assertNotIn('gh', report)
            self.assertNotIn('github', report)

    def test_report_never_includes_log_file_contents(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            secret_marker = 'THIS_IS_LOG_CONTENT_MARKER'
            (state / 'issue-1-999.log').write_text(secret_marker)
            write_json(state / 'issue-1.json', {'issue': 1, 'status': 'failed', 'agent': 'codex-b'})
            config = {'state': str(state)}
            report = fs.build_report('cfg.json', config, now=1010.0)
            self.assertNotIn(secret_marker, json.dumps(report))


class FormatTextTests(unittest.TestCase):
    def test_format_text_runs_on_missing_everything(self):
        report = fs.build_report('cfg.json', {'state': '/nonexistent'}, now=1010.0)
        text = fs.format_text(report)
        self.assertIn('missing', text)
        self.assertIsInstance(text, str)

    def test_format_text_marks_stale_heartbeat(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'heartbeat.json', {'time': 1000.0, 'pid': 1, 'status': 'idle'})
            report = fs.build_report('cfg.json', {'state': str(state)}, now=1000.0 + 500)
            text = fs.format_text(report)
            self.assertIn('STALE', text)


class MainCliTests(unittest.TestCase):
    def test_json_output_is_valid_and_complete(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'heartbeat.json', {'time': time_now(0), 'pid': 1, 'status': 'idle'})
            write_json(state / 'issue-1.json', {'issue': 1, 'status': 'review', 'agent': 'claude'})
            config_path = pathlib.Path(d) / 'config.json'
            write_json(config_path, {'state': str(state)})
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = fs.main(['--config', str(config_path), '--json'])
            self.assertEqual(rc, 0)
            parsed = json.loads(buf.getvalue())
            for key in ('generated_at', 'heartbeat', 'issues', 'utilization', 'capacity_note'):
                self.assertIn(key, parsed)

    def test_text_output_runs_without_error(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            config_path = pathlib.Path(d) / 'config.json'
            write_json(config_path, {'state': str(state)})
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = fs.main(['--config', str(config_path)])
            self.assertEqual(rc, 0)
            self.assertIn('Factory health report', buf.getvalue())

    def test_missing_config_file_reports_error_without_traceback(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fs.main(['--config', '/nonexistent/config.json', '--json'])
        self.assertEqual(rc, 1)
        parsed = json.loads(buf.getvalue())
        self.assertIn('error', parsed)

    def test_stale_threshold_flag_is_honored(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / 'state'
            state.mkdir()
            write_json(state / 'heartbeat.json', {'time': 1000.0, 'pid': 1, 'status': 'idle'})
            config_path = pathlib.Path(d) / 'config.json'
            write_json(config_path, {'state': str(state)})
            with patch('time.time', return_value=1000.0 + 10):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    fs.main(['--config', str(config_path), '--json', '--stale-after-seconds', '5'])
                parsed = json.loads(buf.getvalue())
                self.assertTrue(parsed['heartbeat']['stale'])


def write_json(path, data):
    path.write_text(json.dumps(data))


def time_now(offset):
    return 2_000_000_000.0 + offset


if __name__ == '__main__':
    unittest.main()
