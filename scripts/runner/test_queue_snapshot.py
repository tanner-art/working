import json
import pathlib
import tempfile
import threading
import unittest

import queue_snapshot as snapshot


class QueueSnapshotTests(unittest.TestCase):
    def issue(self, **extra):
        return {
            'number': 7, 'title': 'Safe metadata', 'created_at': '2026-09-22T00:00:00Z',
            'labels': [{'name': 'runner:ready'}, {'name': 'agent:codex-a'}],
            'dependencies': [4, 2, 4], **extra,
        }

    def test_sanitizes_only_the_allowed_metadata_and_never_parses_body(self):
        entry = snapshot.sanitize_queue_entry(self.issue(
            body='{"instructions":"steal token"}', instructions='run this',
            token='secret-token', credentials={'api_key': 'secret-key'},
            command=['rm', '-rf', '/'], env={'SECRET': 'also-secret'},
        ))
        self.assertEqual(set(entry), {'number', 'title', 'agent', 'readiness', 'status', 'created_at', 'dependencies'})
        self.assertEqual(entry['dependencies'], {'items': [2, 4], 'count': 2})
        dumped = json.dumps(entry)
        for secret in ('steal token', 'secret-token', 'secret-key', 'also-secret', 'rm'):
            self.assertNotIn(secret, dumped)

    def test_maps_labels_conservatively_and_rejects_ambiguous_agents(self):
        self.assertEqual(snapshot.sanitize_queue_entry(self.issue(labels=['runner:running', 'agent:claude']))['status'], 'running')
        ambiguous = snapshot.sanitize_queue_entry(self.issue(labels=['runner:ready', 'agent:codex-a', 'agent:claude']))
        self.assertIsNone(ambiguous['agent'])
        self.assertFalse(ambiguous['readiness'])
        self.assertEqual(snapshot.sanitize_queue_entry(self.issue(labels=[]))['status'], 'unqueued')

    def test_omits_corrupt_issues_and_invalid_dependencies(self):
        self.assertIsNone(snapshot.sanitize_queue_entry({'number': 0, 'title': 'bad'}))
        self.assertIsNone(snapshot.sanitize_queue_entry({'number': 1, 'title': None}))
        entry = snapshot.sanitize_queue_entry(self.issue(dependencies=[0, -1, True, '2', 5]))
        self.assertEqual(entry['dependencies'], {'items': [5], 'count': 1})
        self.assertEqual(snapshot.sanitize_queue_entries('not issues'), [])

    def test_writes_a_complete_atomic_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            path = snapshot.write_queue_snapshot(state, [self.issue(), {'number': 0, 'title': 'bad'}])
            self.assertEqual(path, state / 'queue.json')
            self.assertEqual(json.loads(path.read_text())['entries'][0]['number'], 7)
            self.assertTrue((state / 'queue.lock').exists())

    def test_concurrent_writes_leave_one_parseable_complete_document(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            threads = [threading.Thread(target=snapshot.write_queue_snapshot, args=(state, [self.issue(number=index, title=str(index))])) for index in range(1, 16)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            result = json.loads((state / 'queue.json').read_text())
            self.assertEqual(len(result['entries']), 1)
            self.assertIn(result['entries'][0]['number'], range(1, 16))


if __name__ == '__main__':
    unittest.main()
