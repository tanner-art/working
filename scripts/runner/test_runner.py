import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from runner import (build_agent_environment, build_agent_prompt,
                    preserve_interrupted_attempt, publish_completion_telemetry,
                    recover_stale_claims, refresh_queue_snapshot,
                    RegistryAttemptLifecycle, run,
                    run_repository_validation, select, usage_policy_enabled)
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

    def test_usage_gating_is_explicit(self):
        self.assertFalse(usage_policy_enabled({'agents': {'codex-a': {'model': 'm'}}}))
        self.assertTrue(usage_policy_enabled({'usage': {}}))
        self.assertTrue(usage_policy_enabled({'usage_file': 'usage.json'}))

    def test_agent_environment_is_allowlisted(self):
        with patch('runner.os.getuid', return_value=501), \
                patch('runner.pwd.getpwuid', return_value=SimpleNamespace(pw_name='launch-owner')):
            env = build_agent_environment(
                {'PATH': 'old', 'HOME': '/home', 'TMPDIR': '/tmp',
                 'USER': 'inherited-impostor', 'OPENAI_API_KEY': 'inherited-secret'},
                {'CODEX_HOME': '/agent-home', 'USER': 'configured-impostor'}, '/runner/bin')
        self.assertEqual(env, {'PATH': '/runner/bin', 'HOME': '/home',
                               'TMPDIR': '/tmp', 'CODEX_HOME': '/agent-home',
                               'USER': 'launch-owner'})

    def test_agent_environment_rejects_configured_claude_credentials(self):
        for configured_env, message in (
            ({'CLAUDE_CODE_OAUTH_TOKEN': 'not-a-token'},
             'CLAUDE_CODE_OAUTH_TOKEN'),
            ({'RENAMED_SECRET': 'sk-ant-oat01-not-a-real-token'},
             'raw Claude setup token'),
        ):
            with self.subTest(configured_env=configured_env):
                with self.assertRaisesRegex(ValueError, message):
                    build_agent_environment(
                        {'HOME': '/home', 'TMPDIR': '/tmp'},
                        configured_env, '/runner/bin',
                    )

    def test_agent_prompt_reserves_full_validation_for_runner(self):
        prompt = build_agent_prompt(17, {
            'task': 'TASK-117', 'paths': ['src/example.ts'],
            'instructions': 'Make the scoped change.',
        })
        self.assertIn('Run only focused checks that directly cover your changes.',
                      prompt)
        self.assertIn('Do not run the full pnpm check', prompt)
        self.assertIn('runner owns that final shared-lock validation', prompt)
        self.assertNotIn('Run pnpm check.', prompt)
        self.assertIn('Read AGENTS.md', prompt)
        self.assertIn('Leave changes for the runner', prompt)

class ProcessTests(unittest.TestCase):
    def test_registry_terminal_mutation_is_attempted_exactly_once(self):
        control = Mock()
        success = RegistryAttemptLifecycle(control, 'attempt-success')
        self.assertTrue(success.succeed())
        self.assertFalse(success.fail('late failure'))
        control.succeed.assert_called_once_with('attempt-success')
        control.fail.assert_not_called()

        failure = RegistryAttemptLifecycle(control, 'attempt-failure')
        self.assertTrue(failure.fail('provider failed'))
        self.assertFalse(failure.fail('duplicate'))
        control.fail.assert_called_once_with('attempt-failure', 'provider failed')

    def test_registry_terminal_failure_is_not_retried_after_mutation_error(self):
        control = Mock()
        control.fail.side_effect = RuntimeError('registry unavailable')
        lifecycle = RegistryAttemptLifecycle(control, 'attempt-error')
        with self.assertRaisesRegex(RuntimeError, 'registry unavailable'):
            lifecycle.fail('provider failed')
        self.assertTrue(lifecycle.finish_attempted)
        self.assertFalse(lifecycle.finish_completed)
        self.assertFalse(lifecycle.fail('late retry'))
        control.fail.assert_called_once_with('attempt-error', 'provider failed')

    def test_failed_process_binding_synchronously_reaps_new_group(self):
        process = Mock(pid=901)
        process.wait.return_value = 1
        with patch('runner.subprocess.Popen', return_value=process), \
                patch('runner.os.killpg') as killpg:
            with self.assertRaisesRegex(RuntimeError, 'gate changed'):
                run(['provider'], on_start=lambda _pid: (_ for _ in ()).throw(
                    RuntimeError('gate changed')
                ), launch_barrier=True)
        self.assertEqual(
            killpg.call_args_list,
            [call(901, __import__('signal').SIGTERM),
             call(901, __import__('signal').SIGKILL)],
        )
        process.wait.assert_called_once_with(timeout=10)

    def test_provider_cannot_execute_before_durable_bind_releases_barrier(self):
        import pathlib, sys, tempfile
        with tempfile.TemporaryDirectory() as directory:
            marker = pathlib.Path(directory) / 'provider-ran'
            command = [
                sys.executable, '-c',
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            ]

            def reject_bind(_pid):
                self.assertFalse(marker.exists())
                raise RuntimeError('Registry rejected PID binding')

            with self.assertRaisesRegex(RuntimeError, 'rejected PID binding'):
                run(command, on_start=reject_bind, launch_barrier=True)
            self.assertFalse(marker.exists())

            bound = []
            run(command, on_start=bound.append, launch_barrier=True)
            self.assertTrue(bound)
            self.assertEqual(marker.read_text(), 'ran')

    def test_runtime_monitor_failure_stops_provider_before_completion(self):
        import pathlib, sys, tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            started, completed = root / 'started', root / 'completed'
            command = [
                sys.executable, '-c',
                (
                    "from pathlib import Path; import time; "
                    f"Path({str(started)!r}).write_text('started'); "
                    "time.sleep(5); "
                    f"Path({str(completed)!r}).write_text('completed')"
                ),
            ]
            checks = []

            def fail_monitor():
                checks.append(True)
                if not started.exists():
                    return
                raise RuntimeError('lease revoked')

            with self.assertRaisesRegex(RuntimeError, 'lease revoked'):
                run(
                    command, launch_barrier=True, on_start=lambda _pid: None,
                    monitor=fail_monitor, monitor_interval=0.1, timeout=10,
                )
            self.assertTrue(checks)
            self.assertTrue(started.exists())
            self.assertFalse(completed.exists())

    def test_worker_disappearance_finishes_registry_attempt_before_local_recovery(self):
        import json, pathlib, tempfile
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            record = state / 'issue-1.json'
            record.write_text(json.dumps({
                'issue': 1, 'status': 'agent', 'updated_at': 1,
                'runner_pid': 900, 'agent_pgid': 901,
                'agent_process_group_state': 'recorded',
                'registry_attempt_id': 'attempt-1',
            }))
            callback = Mock()
            with patch('runner.time.time', return_value=1000), \
                    patch('runner._pid_alive', return_value=False), \
                    patch('runner._process_group_alive', return_value=False):
                recover_stale_claims(state, 10, callback)
            callback.assert_called_once()
            self.assertEqual(callback.call_args.args[0]['registry_attempt_id'], 'attempt-1')
            current = __import__('json').loads(record.read_text())
            self.assertEqual(current['status'], 'failed')
            self.assertTrue(current['preserved'])
            recovered = list(state.glob('issue-1-failed-*.json'))
            self.assertEqual(len(recovered), 1)

    def test_worker_disappearance_keeps_claim_when_registry_finish_fails(self):
        import json, pathlib, tempfile
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            record = state / 'issue-1.json'
            record.write_text(json.dumps({
                'issue': 1, 'status': 'agent', 'updated_at': 1,
                'runner_pid': 900, 'agent_pgid': 901,
                'agent_process_group_state': 'recorded',
                'registry_attempt_id': 'attempt-1',
            }))
            with patch('runner.time.time', return_value=1000), \
                    patch('runner._pid_alive', return_value=False), \
                    patch('runner._process_group_alive', return_value=False):
                recover_stale_claims(
                    state, 10, Mock(side_effect=RuntimeError('registry unavailable'))
                )
            preserved = __import__('json').loads(record.read_text())
            self.assertTrue(preserved['registry_recovery_required'])
            self.assertEqual(preserved['status'], 'agent')

    def test_worker_disappearance_callback_covers_lease_only_setup_gap(self):
        import json, pathlib, tempfile
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            record = state / 'issue-1.json'
            record.write_text(json.dumps({
                'issue': 1, 'status': 'starting', 'updated_at': 1,
                'runner_pid': 900, 'registry_lease_id': 'lease-1',
            }))
            callback = Mock()
            with patch('runner.time.time', return_value=1000), \
                    patch('runner._pid_alive', return_value=False):
                recover_stale_claims(state, 10, callback)
            callback.assert_called_once()
            self.assertEqual(callback.call_args.args[0]['registry_lease_id'], 'lease-1')
            self.assertEqual(
                __import__('json').loads(record.read_text())['status'], 'failed'
            )

    def test_shared_validation_gate_serializes_checks_but_not_agent_stages(self):
        import pathlib, tempfile, threading, time
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            state.mkdir()
            agent_barrier = threading.Barrier(2)
            counter_lock = threading.Lock()
            counts = {'agent': 0, 'agent_peak': 0,
                      'validation': 0, 'validation_peak': 0}
            failures = []

            def validate(args, **kwargs):
                self.assertEqual(args, ['pnpm', 'check'])
                with counter_lock:
                    counts['validation'] += 1
                    counts['validation_peak'] = max(
                        counts['validation_peak'], counts['validation'])
                time.sleep(0.04)
                with counter_lock:
                    counts['validation'] -= 1

            def lane(name):
                try:
                    with counter_lock:
                        counts['agent'] += 1
                        counts['agent_peak'] = max(counts['agent_peak'],
                                                   counts['agent'])
                    agent_barrier.wait(timeout=1)
                    time.sleep(0.02)
                    with counter_lock:
                        counts['agent'] -= 1
                    run_repository_validation(
                        state, 'pnpm', pathlib.Path(directory) / name,
                        {'PATH': '/bin'}, state / f'{name}.log', validate)
                except BaseException as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=lane, args=(name,))
                       for name in ('codex-a', 'claude')]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(failures, [])
            self.assertEqual(counts['agent_peak'], 2)
            self.assertEqual(counts['validation_peak'], 1)

    def test_validation_gate_releases_lock_after_check_failure(self):
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            def fail(*args, **kwargs):
                raise RuntimeError('validation failed')
            with self.assertRaisesRegex(RuntimeError, 'validation failed'):
                run_repository_validation(state, 'pnpm', state, {},
                                          state / 'first.log', fail)
            calls = []
            run_repository_validation(
                state, 'pnpm', state, {}, state / 'second.log',
                lambda args, **kwargs: calls.append(args))
            self.assertEqual(calls, [['pnpm', 'check']])

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
    def test_queue_snapshot_stages_only_whitelisted_open_issue_metadata(self):
        from unittest.mock import patch
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as d, patch('runner.write_queue_snapshot') as write:
            refresh_queue_snapshot(pathlib.Path(d), lambda: __import__('json').dumps([{
                'number': 7, 'title': 'Visible', 'labels': [{'name': 'runner:ready'}],
                'createdAt': '2026-09-22T10:00:00Z', 'body': 'do not persist',
            }]))
        write.assert_called_once_with(pathlib.Path(d), [{
            'number': 7, 'title': 'Visible', 'labels': [{'name': 'runner:ready'}],
            'created_at': '2026-09-22T10:00:00Z',
        }])

    def test_queue_snapshot_failure_is_ignored_without_retaining_error_output(self):
        from unittest.mock import patch
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as d, patch('runner.write_queue_snapshot', side_effect=OSError('secret output')):
            refresh_queue_snapshot(pathlib.Path(d), lambda: '[{"number": 1}]')
            self.assertEqual(list(pathlib.Path(d).iterdir()), [])

    def test_dry_run_never_stages_a_queue_snapshot(self):
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
            issue = {'number': 1, 'title': 'test', 'author': {'login': 'owner'},
                     'labels': [{'name': 'runner:ready'}, {'name': 'agent:codex-a'}],
                     'body': '{"task":"TASK-015","paths":["docs/example.md"],"instructions":"Write a note"}'}
            def fake_run(args, **_kwargs):
                return json.dumps([issue]) if args[:3] == ['gh', 'issue', 'list'] else ''
            with patch.object(runner, 'run', side_effect=fake_run), patch.object(runner, 'write_queue_snapshot') as write, \
                 patch('sys.argv', ['runner', '--config', str(configfile), '--dry-run']), contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            write.assert_not_called()

    def test_live_runner_fails_closed_without_registry_configuration(self):
        import json, pathlib, tempfile
        from unittest.mock import patch
        import runner
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config = {
                'repo': directory, 'state': str(root / 'state'),
                'worktrees': str(root / 'trees'), 'path': '/usr/bin:/bin',
                'gh': 'gh', 'git': 'git', 'pnpm': 'pnpm',
                'github': 'owner/repo', 'allowed_authors': ['owner'],
                'agents': {},
            }
            configfile = root / 'config.json'
            configfile.write_text(json.dumps(config))
            with patch('sys.argv', ['runner', '--config', str(configfile)]):
                with self.assertRaisesRegex(ValueError, 'registry_database'):
                    runner.main()

    def test_lane_dry_run_only_reports_its_assigned_provider(self):
        import contextlib, io, json, pathlib, tempfile
        from unittest.mock import patch
        import runner
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            config = {'repo': d, 'state': str(root/'state'), 'worktrees': str(root/'trees'),
                      'path': '/usr/bin:/bin', 'gh': 'gh', 'git': 'git', 'pnpm': 'pnpm',
                      'github': 'owner/repo', 'allowed_authors': ['owner'],
                      'agents': {
                          'codex-a': {'command': ['agent'], 'slots': 2, 'model': 'codex-model'},
                          'claude': {'command': ['agent'], 'model': 'claude-model'},
                      }}
            configfile = root/'config.json'; configfile.write_text(json.dumps(config))
            def issue(number, agent):
                return {
                    'number': number, 'title': agent, 'author': {'login': 'owner'},
                    'labels': [{'name': 'runner:ready'}, {'name': f'agent:{agent}'}],
                    'body': json.dumps({'task': f'TASK-{number:03d}',
                                        'paths': [f'docs/{agent}.md'],
                                        'instructions': 'Write a note'}),
                }
            issues = [issue(1, 'claude'), issue(2, 'codex-a')]
            def fake_run(args, **_kwargs):
                return json.dumps(issues) if args[:3] == ['gh', 'issue', 'list'] else ''
            output = io.StringIO()
            with patch.object(runner, 'run', side_effect=fake_run), \
                 patch('sys.argv', ['runner', '--config', str(configfile), '--agent',
                                    'codex-a', '--slot', '2', '--dry-run']), \
                 contextlib.redirect_stdout(output):
                runner.main()
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            issue_records = [record for record in records if 'issue' in record]
            self.assertEqual([record['issue'] for record in issue_records], [2])
            self.assertEqual(issue_records[0]['agent'], 'codex-a')
            self.assertEqual(issue_records[0]['worker'], 'codex-a-2')

    def test_interrupted_attempt_is_failed_even_when_telemetry_fails(self):
        import pathlib, tempfile
        from unittest.mock import patch
        import runner
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d)
            record = state / 'issue-1.json'
            data = {'issue': 1, 'status': 'agent', 'runner_pid': 123,
                    'worktree': str(state / 'worktree')}
            record.write_text('{}')
            with patch.object(runner, 'write_heartbeat', side_effect=OSError('heartbeat')), \
                 patch.object(runner, 'append_event', side_effect=OSError('event')):
                preserve_interrupted_attempt(
                    state, record, data, issue=1, task_id='TASK-1', title='t',
                    agent='codex-a', heartbeat_agent=None, worker='serial',
                    started_at=1, error='signal')
            saved = __import__('json').loads(record.read_text())
            self.assertEqual(saved['status'], 'failed')
            self.assertTrue(saved['preserved'])
            self.assertTrue(saved['interrupted'])
            self.assertGreater(saved['updated_at'], 1)

    def test_completion_telemetry_failure_does_not_change_review_outcome(self):
        import pathlib, tempfile
        from unittest.mock import patch
        import runner
        with tempfile.TemporaryDirectory() as d:
            with patch.object(runner, 'write_heartbeat', side_effect=OSError('heartbeat')), \
                 patch.object(runner, 'append_event', side_effect=OSError('event')):
                errors = publish_completion_telemetry(
                    pathlib.Path(d), issue=1, task_id='TASK-1', title='t',
                    agent='codex-a', base='base', worktree_path='wt',
                    commit='commit', pr='pr', validation_result='passed',
                    elapsed_seconds=1, stats={}, heartbeat_kwargs={'status': 'review'},
                    github_callback=lambda: (_ for _ in ()).throw(RuntimeError('secret')))
            self.assertEqual({error['operation'] for error in errors},
                             {'heartbeat', 'event', 'issue-label'})
            self.assertTrue(all(set(error) == {'operation', 'error_class'}
                                for error in errors))
            telemetry = pathlib.Path(d) / 'telemetry-errors.jsonl'
            self.assertTrue(telemetry.exists())
            self.assertNotIn('secret', telemetry.read_text())

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

    def exercise_poll(
        self, blocked=False, preclaim_error=False, snapshot_failure=False,
        kind='PARENT',
    ):
        import contextlib, io, json, pathlib, tempfile
        from unittest.mock import patch
        import runner
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            config = {'repo': d, 'state': str(root/'state'), 'worktrees': str(root/'trees'),
                      'path': '/usr/bin:/bin', 'gh': 'gh', 'git': 'git', 'pnpm': 'pnpm',
                      'github': 'owner/repo', 'allowed_authors': ['owner'],
                      'agents': {'codex-a': ({'command': ['agent'], 'account': ''}
                                             if preclaim_error else {'command': ['agent']})}}
            if preclaim_error:
                config['usage_policy'] = {}
            configfile = root/'config.json'; configfile.write_text(json.dumps(config))
            body = {
                'task': 'TASK-015', 'paths': ['docs/example.md'],
                'instructions': 'Write a note',
                'depends_on': [2] if blocked else [], 'kind': kind,
                'lane': 'ASSURANCE' if kind == 'REVIEW' else 'FEATURE',
            }
            issue = {'number': 1, 'title': 'test', 'author': {'login': 'owner'},
                     'labels': [{'name': 'runner:ready'}, {'name': 'agent:codex-a'}], 'body': json.dumps(body)}
            calls = []; branch = None; validated = False
            if preclaim_error:
                (root / 'state').mkdir()
                (root / 'state' / 'issue-1.json').write_text(json.dumps({
                    'issue': 1, 'status': 'agent', 'paths': ['other.py'],
                    'runner_pid': 123,
                }))
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
                if args == ['agent'] and kwargs.get('on_start'):
                    calls.append(['provider', 'started'])
                    kwargs['on_start'](901)
                return ''
            snapshot = (patch.object(runner, 'write_queue_snapshot', side_effect=OSError('secret snapshot output'))
                        if snapshot_failure else contextlib.nullcontext())
            registry = Mock()
            registry.pre_claim.side_effect = lambda *args, **kwargs: (
                calls.append(['registry', 'pre-claim']) or 1
            )
            registry.claim_package.side_effect = lambda *args, **kwargs: (
                calls.append(['registry', 'claim']) or 'lease-1'
            )
            registry.pre_launch.side_effect = lambda: (
                calls.append(['registry', 'pre-launch']) or 2
            )
            registry.reserve_attempt.side_effect = lambda *args, **kwargs: calls.append(
                ['registry', 'reserve']
            )
            registry.renew_runtime.side_effect = lambda *args, **kwargs: calls.append(
                ['registry', 'renew']
            )
            registry.record_process.side_effect = lambda *args, **kwargs: calls.append(
                ['registry', 'bind']
            )
            with patch.object(runner, 'run', side_effect=fake_run), snapshot, \
                 patch.object(runner.RunnerRegistryControl, 'from_config', return_value=registry), \
                 patch.object(runner.os, 'getpgid', return_value=901), \
                 patch('sys.argv', ['runner', '--config', str(configfile)]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                runner.main()
            record = root/'state'/'issue-1.json'
            return calls, json.loads(record.read_text()) if record.exists() else None

    def test_validation_cannot_stage_out_of_scope_change(self):
        calls, record = self.exercise_poll()
        self.assertEqual(record['status'], 'failed')
        self.assertIn('outside allowed paths', record['error'])
        self.assertIn(['pnpm', 'check'], calls)
        self.assertNotIn(['git', 'commit'], [c[:2] for c in calls])
        self.assertNotIn(['git', 'push'], [c[:2] for c in calls])
        self.assertLess(calls.index(['registry', 'pre-claim']),
                        calls.index(['registry', 'claim']))
        self.assertLess(calls.index(['registry', 'claim']),
                        calls.index(['registry', 'reserve']))
        self.assertLess(calls.index(['registry', 'reserve']),
                        calls.index(['registry', 'renew']))
        self.assertGreaterEqual(calls.count(['registry', 'renew']), 5)
        prelaunches = [index for index, value in enumerate(calls)
                       if value == ['registry', 'pre-launch']]
        self.assertEqual(len(prelaunches), 2)
        self.assertLess(prelaunches[-1], calls.index(['provider', 'started']))
        self.assertLess(calls.index(['provider', 'started']),
                        calls.index(['registry', 'bind']))

    def test_open_dependency_waits_without_failure_or_claim(self):
        calls, record = self.exercise_poll(blocked=True)
        self.assertIsNone(record)
        self.assertNotIn(['gh', 'issue', 'edit'], [c[:3] for c in calls])
        self.assertNotIn(['git', 'worktree', 'add'], [c[:3] for c in calls])

    def test_registry_review_dependency_defers_to_verify_review_preclaim(self):
        calls, record = self.exercise_poll(blocked=True, kind='REVIEW')
        self.assertEqual(record['status'], 'failed')
        self.assertIn(['registry', 'pre-claim'], calls)
        self.assertNotIn(['gh', 'issue', 'view'], [call[:3] for call in calls])

    def test_preclaim_error_does_not_overwrite_existing_claim(self):
        calls, record = self.exercise_poll(preclaim_error=True)
        self.assertEqual(record['status'], 'agent')
        self.assertEqual(record['paths'], ['other.py'])
        self.assertNotIn(['gh', 'issue', 'edit'], [c[:3] for c in calls])

    def test_snapshot_write_failure_does_not_prevent_a_claim(self):
        calls, record = self.exercise_poll(snapshot_failure=True)
        self.assertEqual(record['status'], 'failed')
        self.assertIn('outside allowed paths', record['error'])
        self.assertIn(['gh', 'issue', 'edit'], [call[:3] for call in calls])

if __name__ == '__main__':
    unittest.main()
