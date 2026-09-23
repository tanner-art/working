import json
import multiprocessing
import os
import pathlib
import tempfile
import time
import unittest

from runner import (EVENT_FIELDS, aggregate_numstat, append_event, claim,
                    child_slot_allowed, configured_slots, lane_key, paths_overlap,
                    recover_stale_claims, select, write_heartbeat)


def claim_worker(state, number, paths, queue):
    issue = {'number': number}
    body = {'paths': paths}
    result = claim(pathlib.Path(state), issue, 'codex-a', body)
    queue.put(None if result is None else result if result == 'deferred' else result['issue'])


def event_worker(state, number):
    append_event(pathlib.Path(state), issue=number, task_id='TASK-015',
                 title='safe title', agent='codex-a', status='agent',
                 base='abc123')


class ParallelDispatchTests(unittest.TestCase):
    def issue(self, agent):
        return {'author': {'login': 'owner'},
                'labels': [{'name': f'agent:{agent}'}],
                'body': '{"task":"TASK-015","paths":["docs/example.md"],"instructions":"x"}' }

    def test_lane_selection_is_restricted_to_requested_agent(self):
        self.assertEqual(select(self.issue('codex-a'), ['owner'])[0], 'codex-a')
        self.assertNotEqual(select(self.issue('claude'), ['owner'])[0], 'codex-a')

    def test_same_issue_has_one_atomic_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = multiprocessing.Queue()
            workers = [multiprocessing.Process(target=claim_worker,
                                                args=(directory, 1, ['src/a.ts'], queue))
                        for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(5)
            results = [queue.get() for _ in workers]
            self.assertEqual(results.count(1), 1)
            self.assertEqual(results.count(None), 1)
            record = json.loads((pathlib.Path(directory) / 'issue-1.json').read_text())
            self.assertEqual(record['paths'], ['src/a.ts'])

    def test_overlapping_active_paths_are_deferred(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            (state / 'issue-1.json').write_text(json.dumps({
                'issue': 1, 'status': 'agent', 'paths': ['src'],
            }))
            result = claim(state, {'number': 2}, 'codex-b', {'paths': ['src/a.ts']})
            self.assertEqual(result, 'deferred')
            self.assertFalse((state / 'issue-2.json').exists())

    def test_nonoverlapping_lanes_can_claim_concurrently(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = multiprocessing.Queue()
            workers = [multiprocessing.Process(target=claim_worker,
                                                args=(directory, number, [f'src/{number}.ts'], queue))
                        for number in (1, 2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(5)
            self.assertEqual(sorted(queue.get() for _ in workers), [1, 2])
            self.assertTrue(paths_overlap(['src'], ['src/a.ts']))
            self.assertFalse(paths_overlap(['src/a.ts'], ['src/b.ts']))

    def test_concurrent_event_writes_remain_parseable(self):
        with tempfile.TemporaryDirectory() as directory:
            workers = [multiprocessing.Process(target=event_worker,
                                                args=(directory, number))
                       for number in range(3)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(5)
                self.assertEqual(worker.exitcode, 0)
            lines = (pathlib.Path(directory) / 'events.jsonl').read_text().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertTrue(all(json.loads(line)['issue'] in range(3) for line in lines))

    def test_heartbeat_files_are_isolated_by_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            write_heartbeat(state, status='agent', issue=1, task_id='TASK-1',
                            start_time=10, agent='codex-a', usage_state='green',
                            effective_model='model-a')
            write_heartbeat(state, status='validation', issue=2, task_id='TASK-2',
                            start_time=20, agent='codex-b')
            self.assertEqual(json.loads((state / 'heartbeat-codex-a.json').read_text())['issue'], 1)
            heartbeat = json.loads((state / 'heartbeat-codex-a.json').read_text())
            self.assertEqual(heartbeat['usage_state'], 'green')
            self.assertEqual(heartbeat['effective_model'], 'model-a')
            self.assertEqual(json.loads((state / 'heartbeat-codex-b.json').read_text())['issue'], 2)

    def test_provider_child_lanes_have_stable_keys_and_bounded_slots(self):
        config = {'agents': {'codex-a': {'slots': 2}, 'claude': {}}}
        self.assertEqual(configured_slots(config, 'codex-a'), 2)
        self.assertEqual(configured_slots(config, 'claude'), 1)
        self.assertEqual(lane_key('codex-a', 1), 'codex-a')
        self.assertEqual(lane_key('codex-a', 2), 'codex-a-2')
        for invalid in (0, 4, True, '2'):
            with self.subTest(invalid=invalid):
                config['agents']['codex-a']['slots'] = invalid
                with self.assertRaises(ValueError):
                    configured_slots(config, 'codex-a')

    def test_extra_slot_requires_fresh_green_usage(self):
        self.assertTrue(child_slot_allowed(1, False, 'unknown'))
        self.assertTrue(child_slot_allowed(2, True, 'green'))
        for enabled, state in ((False, 'green'), (True, 'unknown'),
                               (True, 'slow'), (True, 'stop')):
            with self.subTest(enabled=enabled, state=state):
                self.assertFalse(child_slot_allowed(2, enabled, state))

    def test_child_lane_claim_records_provider_and_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            result = claim(state, {'number': 9}, 'claude',
                           {'paths': ['src/a.ts']}, worker='claude-2', slot=2)
            self.assertEqual(result['agent'], 'claude')
            self.assertEqual(result['worker'], 'claude-2')
            self.assertEqual(result['slot'], 2)

    def test_child_lane_event_keeps_direct_provider_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            append_event(state, issue=9, task_id='TASK-999', title='child',
                         agent='claude', worker='claude-2',
                         parent_agent='claude', slot=2, status='agent')
            event = json.loads((state / 'events.jsonl').read_text())
            self.assertEqual(event['agent'], 'claude')
            self.assertEqual(event['worker'], 'claude-2')
            self.assertEqual(event['parent_agent'], 'claude')
            self.assertEqual(event['slot'], 2)

    def test_heartbeat_restores_local_runner_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = write_heartbeat(pathlib.Path(directory), status='polling', worker='serial')
            self.assertEqual(heartbeat['pid'], os.getpid())

    def test_stale_dead_claim_is_preserved_and_no_longer_blocks_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            record = state / 'issue-1.json'
            old = time.time() - 100
            record.write_text(json.dumps({
                'issue': 1, 'status': 'agent', 'paths': ['src'],
                'runner_pid': 99999999, 'time': old, 'updated_at': old,
                'agent_process_group_state': 'recorded', 'agent_pgid': 99999999,
                'worktree': str(state / 'worktree'), 'branch': 'runner/one',
                'log': str(state / 'attempt.log'),
            }))
            result = claim(state, {'number': 2}, 'codex-b', {'paths': ['src/a.ts']},
                           stale_claim_seconds=10)
            self.assertEqual(result['issue'], 2)
            # The stale issue remains failed so an ordinary poll cannot retry it.
            stale = json.loads(record.read_text())
            self.assertEqual(stale['status'], 'failed')
            self.assertTrue(stale['preserved'])
            self.assertTrue(list(state.glob('issue-1-failed-*.json')))
            self.assertIsNone(claim(state, {'number': 1}, 'codex-a', {'paths': ['src']}))

    def test_stale_claim_with_uncertain_agent_group_requires_manual_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            old = time.time() - 100
            record = state / 'issue-1.json'
            record.write_text(json.dumps({
                'issue': 1, 'status': 'agent', 'paths': ['src'],
                'runner_pid': 99999999, 'time': old, 'updated_at': old,
                'agent_process_group_state': 'unknown',
            }))
            result = claim(state, {'number': 2}, 'codex-b', {'paths': ['src/a.ts']},
                           stale_claim_seconds=10)
            self.assertEqual(result, 'deferred')
            self.assertEqual(json.loads(record.read_text())['status'], 'agent')

    def test_stale_claim_with_live_agent_group_is_not_reclaimed(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            old = time.time() - 100
            record = state / 'issue-1.json'
            record.write_text(json.dumps({
                'issue': 1, 'status': 'agent', 'paths': ['src'],
                'runner_pid': 99999999, 'time': old, 'updated_at': old,
                'agent_process_group_state': 'recorded', 'agent_pgid': 123,
            }))
            with patch('runner._process_group_alive', return_value=True):
                result = claim(state, {'number': 2}, 'codex-b', {'paths': ['src/a.ts']},
                               stale_claim_seconds=10)
            self.assertEqual(result, 'deferred')
            self.assertEqual(json.loads(record.read_text())['status'], 'agent')

    def test_events_have_only_safe_allowlisted_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            append_event(pathlib.Path(directory), issue=1, task_id='TASK-1',
                         title='title', agent='codex-a', status='review',
                         base='abc', validation_result='passed')
            event = json.loads((pathlib.Path(directory) / 'events.jsonl').read_text())
            self.assertEqual(set(event), EVENT_FIELDS & set(event))
            self.assertNotIn('instructions', event)
            self.assertNotIn('command_output', event)
            self.assertNotIn('used_percent', event)

    def test_numstat_aggregation_handles_binary_files(self):
        stats = aggregate_numstat('4\t2\ttext.py\n-\t-\timage.png\n')
        self.assertEqual(stats, {'files_changed': 2, 'additions': 4, 'deletions': 2})


if __name__ == '__main__':
    unittest.main()
