import json
import multiprocessing
import pathlib
import tempfile
import unittest

from runner import (EVENT_FIELDS, aggregate_numstat, append_event, claim,
                    paths_overlap, select, write_heartbeat)


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
                            start_time=10, agent='codex-a')
            write_heartbeat(state, status='validation', issue=2, task_id='TASK-2',
                            start_time=20, agent='codex-b')
            self.assertEqual(json.loads((state / 'heartbeat-codex-a.json').read_text())['issue'], 1)
            self.assertEqual(json.loads((state / 'heartbeat-codex-b.json').read_text())['issue'], 2)

    def test_events_have_only_safe_allowlisted_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            append_event(pathlib.Path(directory), issue=1, task_id='TASK-1',
                         title='title', agent='codex-a', status='review',
                         base='abc', validation_result='passed')
            event = json.loads((pathlib.Path(directory) / 'events.jsonl').read_text())
            self.assertEqual(set(event), EVENT_FIELDS & set(event))
            self.assertNotIn('instructions', event)
            self.assertNotIn('command_output', event)

    def test_numstat_aggregation_handles_binary_files(self):
        stats = aggregate_numstat('4\t2\ttext.py\n-\t-\timage.png\n')
        self.assertEqual(stats, {'files_changed': 2, 'additions': 4, 'deletions': 2})


if __name__ == '__main__':
    unittest.main()
