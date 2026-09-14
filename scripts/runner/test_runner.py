import unittest
from runner import select
class QueueTests(unittest.TestCase):
    def issue(self,body=None):
        return {'author':{'login':'owner'},'labels':[{'name':'agent:codex-a'}], 'body':body or '{"task":"TASK-015","paths":["docs/example.md"],"instructions":"Write a note"}'}
    def test_valid(self): self.assertEqual(select(self.issue(),['owner'])[0],'codex-a')
    def test_untrusted_author(self):
        with self.assertRaises(ValueError): select(self.issue(),['someone'])
    def test_traversal(self):
        with self.assertRaises(ValueError): select(self.issue('{"task":"TASK-015","paths":["../secret"],"instructions":"x"}'),['owner'])
    def test_two_agents(self):
        i=self.issue();i['labels'].append({'name':'agent:claude'})
        with self.assertRaises(ValueError): select(i,['owner'])
    def test_completed_not_repeated(self):
        i=self.issue();i['labels'].append({'name':'runner:review'})
        with self.assertRaises(ValueError): select(i,['owner'])

class ProcessTests(unittest.TestCase):
    def test_timeout_preserves_output(self):
        import tempfile,pathlib,sys
        from runner import run
        with tempfile.TemporaryDirectory() as d:
            log=pathlib.Path(d)/'log'
            with self.assertRaisesRegex(RuntimeError,'timed out'):
                run([sys.executable,'-u','-c','import time;print("started");time.sleep(30)'],timeout=0.1,log=log)
            self.assertIn('started',log.read_text())
    def test_failure_stops_pipeline(self):
        import sys
        from runner import run
        with self.assertRaises(RuntimeError):
            run([sys.executable,'-c','raise SystemExit(4)'])

class LifecycleTests(unittest.TestCase):
    def test_sigterm_reaps_active_child(self):
        import os, pathlib, signal, subprocess, sys, tempfile, time
        with tempfile.TemporaryDirectory() as d:
            pidfile = pathlib.Path(d) / 'child.pid'
            child_code = f'import os,pathlib,time;pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(30)'
            parent_code = f'from runner import run;run({[sys.executable, "-c", child_code]!r})'
            parent = subprocess.Popen([sys.executable, '-c', parent_code], cwd=pathlib.Path(__file__).parent)
            child = None
            try:
                deadline = time.monotonic() + 5
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(pidfile.exists(), 'child failed to start')
                child = int(pidfile.read_text())
                parent.terminate()
                self.assertEqual(parent.wait(timeout=12), 128 + signal.SIGTERM)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if parent.poll() is None:
                    parent.kill(); parent.wait()
                if child is not None:
                    try: os.killpg(child, signal.SIGKILL)
                    except ProcessLookupError: pass

    def exercise_poll(self, blocked=False):
        import contextlib, io, json, pathlib, tempfile
        from unittest.mock import patch
        import runner
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            config = {'repo': d, 'state': str(root/'state'), 'worktrees': str(root/'trees'),
                      'path': '/usr/bin:/bin', 'gh': 'gh', 'git': 'git', 'pnpm': 'pnpm',
                      'github': 'owner/repo', 'allowed_authors': ['owner'],
                      'agents': {'codex-a': {'command': ['agent']}}}
            configfile = root/'config.json'; configfile.write_text(json.dumps(config))
            body = {'task': 'TASK-015', 'paths': ['docs/example.md'], 'instructions': 'Write a note',
                    'depends_on': [2] if blocked else []}
            issue = {'number': 1, 'title': 'test', 'author': {'login': 'owner'},
                     'labels': [{'name': 'runner:ready'}, {'name': 'agent:codex-a'}], 'body': json.dumps(body)}
            calls = []; branch = None; validated = False
            def fake_run(args, **kwargs):
                nonlocal branch, validated
                calls.append(args)
                if args[:3] == ['gh', 'issue', 'list']: return json.dumps([issue])
                if args[:3] == ['gh', 'issue', 'view']: return '{"state":"OPEN"}'
                if args[:3] == ['git', 'worktree', 'add']: branch = args[4]
                if args[:3] == ['git', 'branch', '--show-current']: return branch
                if args[:2] == ['git', 'rev-parse']: return 'base-sha'
                if args[:3] == ['git', 'diff', '--name-only']: return 'docs/example.md'
                if args[:4] == ['git', 'diff', '--cached', '--name-only']:
                    return 'outside.txt' if validated else ''
                if args == ['pnpm', 'check']: validated = True
                return ''
            with patch.object(runner, 'run', side_effect=fake_run), patch('sys.argv', ['runner', '--config', str(configfile)]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                runner.main()
            record = root/'state'/'issue-1.json'
            return calls, json.loads(record.read_text()) if record.exists() else None

    def test_validation_cannot_stage_out_of_scope_change(self):
        calls, record = self.exercise_poll()
        self.assertEqual(record['status'], 'failed')
        self.assertIn('outside allowed paths', record['error'])
        self.assertNotIn(['git', 'commit'], [c[:2] for c in calls])
        self.assertNotIn(['git', 'push'], [c[:2] for c in calls])

    def test_open_dependency_waits_without_failure_or_claim(self):
        calls, record = self.exercise_poll(blocked=True)
        self.assertIsNone(record)
        self.assertNotIn(['gh', 'issue', 'edit'], [c[:3] for c in calls])
        self.assertNotIn(['git', 'worktree', 'add'], [c[:3] for c in calls])

if __name__ == '__main__':
    unittest.main()
