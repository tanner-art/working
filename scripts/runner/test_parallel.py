import json
import multiprocessing
import pathlib
import tempfile
import unittest

from runner import claim, paths_overlap, select


def claim_worker(state, number, paths, queue):
    issue = {'number': number}
    body = {'paths': paths}
    result = claim(pathlib.Path(state), issue, 'codex-a', body)
    queue.put(None if result is None else result if result == 'deferred' else result['issue'])


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


if __name__ == '__main__':
    unittest.main()
