import json
import os
import pathlib
import plistlib
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import install_launchd as installer


class LaunchdInstallerTests(unittest.TestCase):
    def config(self, state):
        agents = {}
        for agent in installer.LANE_AGENTS:
            if agent.startswith('codex-'):
                command = ['codex', 'exec', '--disable', 'multi_agent', '-']
            else:
                command = ['claude', '-p', '--tools', 'Read,Edit,Write,Glob,Grep']
            agents[agent] = {
                'command': command,
                'fallback_command': list(command),
                'env': {'SECRET': 'do-not-copy'},
            }
        return {
            'state': str(state), 'path': '/usr/bin:/bin',
            'agents': agents,
        }

    def plan(self, state, mode='serial', live=False, port=8787):
        return installer.service_plan(self.config(state), state / 'config.json', pathlib.Path(__file__).parent, mode, live, port)

    @staticmethod
    def absent_run(calls):
        def run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 1)
        return run

    def test_serial_default_preserves_existing_label_arguments_interval_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            label, data = self.plan(state)[0]
            self.assertEqual(label, 'life.threadline.runner')
            self.assertEqual(data['ProgramArguments'][-1], '--dry-run')
            self.assertEqual(data['StartInterval'], 60)
            self.assertEqual(data['StandardOutPath'], str(state / 'launchd.log'))
            self.assertEqual(data['StandardErrorPath'], str(state / 'launchd-error.log'))

    def test_lane_plan_is_deterministic_localhost_and_never_copies_agent_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            plan = self.plan(state, mode='lanes')
            self.assertEqual([label for label, _ in plan], [
                'life.threadline.runner.codex-a', 'life.threadline.runner.codex-b',
                'life.threadline.runner.claude', 'life.threadline.factory-dashboard',
            ])
            for agent, (_, data) in zip(installer.LANE_AGENTS, plan[:3]):
                self.assertEqual(data['ProgramArguments'][-2:], ['--agent', agent])
                self.assertIn('--dry-run', data['ProgramArguments'])
                self.assertEqual(data['StandardOutPath'], str(state / f'launchd-{agent}.log'))
                self.assertEqual(data['Umask'], 0o077)
            dashboard = plan[-1][1]
            self.assertEqual(dashboard['ProgramArguments'][-4:], ['--host', '127.0.0.1', '--port', '8787'])
            self.assertNotIn('StartInterval', dashboard)
            dumped = plistlib.dumps(dashboard).decode()
            self.assertNotIn('do-not-copy', dumped)
            self.assertNotIn('agent codex-a', dumped)
            self.assertEqual(dashboard['Umask'], 0o077)

    def test_lane_slots_preserve_slot_one_and_add_bounded_child_services(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            config = self.config(state)
            config['agents']['codex-a']['slots'] = 2
            config['agents']['codex-b']['slots'] = 1
            config['agents']['claude']['slots'] = 3

            plan = installer.service_plan(
                config, state / 'config.json', pathlib.Path(__file__).parent, 'lanes'
            )

            self.assertEqual([label for label, _ in plan], [
                'life.threadline.runner.codex-a',
                'life.threadline.runner.codex-a-2',
                'life.threadline.runner.codex-b',
                'life.threadline.runner.claude',
                'life.threadline.runner.claude-2',
                'life.threadline.runner.claude-3',
                'life.threadline.factory-dashboard',
            ])
            services = dict(plan)
            self.assertEqual(
                services['life.threadline.runner.codex-a']['ProgramArguments'][-2:],
                ['--agent', 'codex-a'],
            )
            self.assertEqual(
                services['life.threadline.runner.codex-a-2']['ProgramArguments'][-4:],
                ['--agent', 'codex-a', '--slot', '2'],
            )
            self.assertEqual(
                services['life.threadline.runner.claude-3']['ProgramArguments'][-4:],
                ['--agent', 'claude', '--slot', '3'],
            )
            self.assertEqual(
                services['life.threadline.runner.codex-a']['StandardOutPath'],
                str(state / 'launchd-codex-a.log'),
            )
            self.assertEqual(
                services['life.threadline.runner.codex-a-2']['StandardOutPath'],
                str(state / 'launchd-codex-a-2.log'),
            )
            self.assertEqual(
                services['life.threadline.runner.claude-3']['StandardErrorPath'],
                str(state / 'launchd-claude-3-error.log'),
            )

    def test_lane_slots_default_to_one_and_reject_values_outside_one_through_three(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            config = self.config(state)
            plan = installer.service_plan(
                config, state / 'config.json', pathlib.Path(__file__).parent, 'lanes'
            )
            self.assertEqual(len(plan), len(installer.LANE_AGENTS) + 1)

            for invalid in (True, 0, 4, 1.5, '2'):
                with self.subTest(invalid=invalid):
                    config['agents']['claude']['slots'] = invalid
                    with self.assertRaisesRegex(ValueError, 'claude slots must be an integer from 1 through 3'):
                        installer.service_plan(
                            config, state / 'config.json', pathlib.Path(__file__).parent, 'lanes'
                        )

    def test_example_config_uses_runner_controlled_fanout_only(self):
        example = json.loads((pathlib.Path(__file__).parent / 'config.example.json').read_text())
        self.assertEqual(
            {agent: value['slots'] for agent, value in example['agents'].items()},
            {'codex-a': 2, 'codex-b': 1, 'claude': 2},
        )
        for agent in ('codex-a', 'codex-b'):
            for command_name in ('command', 'fallback_command'):
                command = example['agents'][agent][command_name]
                index = command.index('--disable')
                self.assertEqual(command[index + 1], 'multi_agent')
        for command_name in ('command', 'fallback_command'):
            command = example['agents']['claude'][command_name]
            tools = command[command.index('--tools') + 1].split(',')
            self.assertNotIn('Agent', tools)

    def test_lane_plan_rejects_commands_that_allow_hidden_native_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            root = pathlib.Path(__file__).parent
            for agent, field, unsafe in (
                ('codex-a', 'command', ['codex', 'exec', '-']),
                ('codex-b', 'fallback_command', ['codex', 'exec', '-']),
                ('codex-a', 'command', ['codex', 'exec', '--disable', 'multi_agent',
                                        '--enable', 'multi_agent', '-']),
                ('claude', 'command', ['claude', '-p']),
                ('claude', 'fallback_command', ['claude', '-p', '--tools', 'Read,Agent']),
                ('claude', 'command', ['claude', '-p', '--tools', 'Read,Edit',
                                       '--tools=Read,Agent']),
            ):
                with self.subTest(agent=agent, field=field):
                    config = self.config(state)
                    config['agents'][agent][field] = unsafe
                    with self.assertRaisesRegex(ValueError, 'multi_agent|allowlist without Agent'):
                        installer.service_plan(config, state / 'config.json', root, 'lanes')

    def test_serial_plan_also_rejects_hidden_native_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            config = self.config(state)
            config['agents']['codex-a']['command'] = ['codex', 'exec', '-']
            with self.assertRaisesRegex(ValueError, 'multi_agent'):
                installer.service_plan(
                    config, state / 'config.json', pathlib.Path(__file__).parent, 'serial'
                )

    def test_private_storage_hardens_managed_paths_without_truncating_or_changing_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = pathlib.Path(directory) / 'factory'
            factory.mkdir(mode=0o755)
            state = factory / 'state'
            state.mkdir(mode=0o755)
            existing = state / 'queue.json'
            existing.write_text('preserved')
            existing.chmod(0o644)
            config_path = factory / 'config.json'
            config_path.write_text('{}')
            config_path.chmod(0o644)
            config = self.config(state)
            config['worktrees'] = str(factory / 'worktrees')
            plan = installer.service_plan(config, config_path, pathlib.Path(__file__).parent, 'lanes')
            owners = {path: path.stat().st_uid for path in (factory, state, existing, config_path)}

            installer.prepare_private_storage(config_path, config, plan)

            for path in (factory, state, factory / 'worktrees'):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertEqual(existing.read_text(), 'preserved')
            for path in (existing, config_path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            for _, data in plan:
                for field in ('StandardOutPath', 'StandardErrorPath'):
                    log = pathlib.Path(data[field])
                    self.assertTrue(log.exists())
                    self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
            for path, owner in owners.items():
                self.assertEqual(path.stat().st_uid, owner)

    def test_atomic_plist_is_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / 'service.plist'
            installer.atomic_write_plist(destination, {'Label': 'test'})
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_service_environment_uses_current_uid_identity_without_copying_process_user(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'USER': 'untrusted-process-user'}), \
                patch.object(installer.os, 'getuid', return_value=501), \
                patch.object(installer.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='launch-owner')):
            plan = self.plan(pathlib.Path(directory) / 'state', mode='lanes')
            for _, data in plan:
                environment = data['EnvironmentVariables']
                self.assertEqual(environment, {
                    'PATH': '/usr/bin:/bin',
                    'HOME': str(pathlib.Path.home()),
                    'USER': 'launch-owner',
                })
                self.assertNotIn('untrusted-process-user', plistlib.dumps(data).decode())

    def test_live_removes_dry_run_only_from_runners(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(pathlib.Path(directory) / 'state', mode='lanes', live=True)
            self.assertTrue(all('--dry-run' not in data['ProgramArguments'] for _, data in plan[:3]))
            self.assertNotIn('--dry-run', plan[-1][1]['ProgramArguments'])

    def test_invalid_lane_config_and_port_fail_before_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / 'state'
            config = self.config(state)
            del config['agents']['claude']
            with self.assertRaisesRegex(ValueError, 'claude'):
                installer.service_plan(config, state / 'config.json', pathlib.Path(__file__).parent, 'lanes')
            with self.assertRaisesRegex(ValueError, 'port'):
                self.plan(state, mode='lanes', port=80)

    def test_existing_target_and_mode_change_are_preserved_without_explicit_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            plan = self.plan(state)
            target = installer.label_path(installer.SERIAL_LABEL, home)
            target.parent.mkdir(parents=True)
            target.write_text('existing')
            with self.assertRaisesRegex(ValueError, 'existing service preserved'):
                installer.install(plan, mode='serial', replace_mode=False, state=state, home=home, run=self.absent_run([]), uid=1)
            target.unlink()
            old = installer.label_path('life.threadline.runner.codex-a', home)
            old.write_text('old lane')
            with self.assertRaisesRegex(ValueError, 'replace-mode'):
                installer.install(plan, mode='serial', replace_mode=False, state=state, home=home, run=self.absent_run([]), uid=1)

    def test_same_mode_target_is_preserved_without_replace_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            plan = self.plan(state, mode='lanes', live=True)
            target = installer.label_path('life.threadline.runner.codex-a', home)
            target.parent.mkdir(parents=True)
            target.write_text('dry-run lane')
            with self.assertRaisesRegex(ValueError, 'existing service preserved'):
                installer.install(plan, mode='lanes', replace_mode=False, state=state, home=home, run=self.absent_run([]), uid=1)
            self.assertEqual(target.read_text(), 'dry-run lane')

    def test_replace_current_promotes_dry_run_lanes_and_boots_out_only_loaded_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            dry_plan = self.plan(state, mode='lanes')
            for label, data in dry_plan:
                destination = installer.label_path(label, home)
                installer.atomic_write_plist(destination, data)
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                loaded = args[1] == 'print' and args[-1].endswith('.codex-a')
                return subprocess.CompletedProcess(args, 0 if loaded or args[1] != 'print' else 1)
            live_plan = self.plan(state, mode='lanes', live=True)
            installer.install(live_plan, mode='lanes', replace_mode=False, replace_current=True, state=state, home=home, run=run, uid=1)
            self.assertEqual([call[-1] for call in calls if call[1] == 'bootout'], ['gui/1/life.threadline.runner.codex-a'])
            for label, _ in live_plan[:3]:
                data = plistlib.loads(installer.label_path(label, home).read_bytes())
                self.assertNotIn('--dry-run', data['ProgramArguments'])

    def test_replace_current_removes_obsolete_child_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            old_config = self.config(state)
            old_config['agents']['codex-a']['slots'] = 2
            old_plan = installer.service_plan(
                old_config, state / 'config.json', pathlib.Path(__file__).parent, 'lanes'
            )
            for label, data in old_plan:
                installer.atomic_write_plist(installer.label_path(label, home), data)
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                if args[1] == 'print':
                    label = args[-1].rsplit('/', 1)[-1]
                    loaded = installer.label_path(label, home).exists()
                    return subprocess.CompletedProcess(args, 0 if loaded else 1)
                return subprocess.CompletedProcess(args, 0)

            new_plan = self.plan(state, mode='lanes', live=True)
            installer.install(
                new_plan, mode='lanes', replace_mode=False, replace_current=True,
                state=state, home=home, run=run, uid=1,
            )

            stale_label = 'life.threadline.runner.codex-a-2'
            self.assertFalse(installer.label_path(stale_label, home).exists())
            self.assertIn(['launchctl', 'bootout', f'gui/1/{stale_label}'], calls)

    def test_slot_shrink_failure_restores_obsolete_child_slot_and_load_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            old_config = self.config(state)
            old_config['agents']['codex-a']['slots'] = 2
            old_plan = installer.service_plan(
                old_config, state / 'config.json', pathlib.Path(__file__).parent, 'lanes'
            )
            originals = {}
            for label, data in old_plan:
                destination = installer.label_path(label, home)
                installer.atomic_write_plist(destination, data)
                originals[label] = destination.read_bytes()
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                if args[1] == 'print':
                    label = args[-1].rsplit('/', 1)[-1]
                    loaded = installer.label_path(label, home).exists()
                    return subprocess.CompletedProcess(args, 0 if loaded else 1)
                if args[1] == 'bootstrap' and args[-1].endswith('runner.codex-b.plist'):
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0)

            with self.assertRaisesRegex(RuntimeError, 'installation failed'):
                installer.install(
                    self.plan(state, mode='lanes', live=True), mode='lanes',
                    replace_mode=False, replace_current=True, state=state,
                    home=home, run=run, uid=1,
                )

            stale_label = 'life.threadline.runner.codex-a-2'
            self.assertEqual(installer.label_path(stale_label, home).read_bytes(),
                             originals[stale_label])
            restored = [call[-1] for call in calls if call[1] == 'bootstrap']
            self.assertGreaterEqual(sum(path.endswith(f'{stale_label}.plist') for path in restored), 1)

    def test_replace_current_refuses_loaded_target_without_plist_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            def loaded_run(args, **kwargs):
                loaded = args[1] == 'print' and args[-1].endswith('.codex-a')
                return subprocess.CompletedProcess(args, 0 if loaded else 1)
            with self.assertRaisesRegex(ValueError, 'without plist backups'):
                installer.install(self.plan(state, mode='lanes', live=True), mode='lanes', replace_mode=False,
                                  replace_current=True, state=state, home=home, run=loaded_run, uid=1)

    def test_replace_current_bootstrap_failure_restores_current_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            dry_plan = self.plan(state, mode='lanes')
            originals = {}
            for label, data in dry_plan:
                destination = installer.label_path(label, home)
                installer.atomic_write_plist(destination, data)
                originals[label] = destination.read_bytes()
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                if args[1] == 'print':
                    loaded = args[-1].endswith('.codex-a')
                    return subprocess.CompletedProcess(args, 0 if loaded else 1)
                if args[1] == 'bootstrap' and 'runner.codex-b' in args[-1]:
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0)
            with self.assertRaisesRegex(RuntimeError, 'installation failed'):
                installer.install(self.plan(state, mode='lanes', live=True), mode='lanes', replace_mode=False,
                                  replace_current=True, state=state, home=home, run=run, uid=1)
            for label, original in originals.items():
                self.assertEqual(installer.label_path(label, home).read_bytes(), original)
            restored_bootstraps = [call[-1] for call in calls if call[1] == 'bootstrap']
            self.assertEqual(sum(path.endswith('.codex-a.plist') for path in restored_bootstraps), 2)
            self.assertFalse(any(path.endswith('.claude.plist') for path in restored_bootstraps))

    def test_replace_flags_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with self.assertRaisesRegex(ValueError, 'cannot be combined'):
                installer.install(self.plan(root / 'state'), mode='serial', replace_mode=True, replace_current=True,
                                  state=root / 'state', home=root / 'home', run=self.absent_run([]), uid=1)

    def test_pause_to_dry_run_is_kill_first_and_keeps_reversible_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            live_plan = self.plan(state, mode='serial', live=True)
            dry_plan = self.plan(state, mode='serial', live=False)
            destination = installer.label_path(installer.SERIAL_LABEL, home)
            installer.atomic_write_plist(destination, live_plan[0][1])
            events = []

            class Control:
                def engage_stop(self, reason):
                    events.append('registry:stop')
                def finalize_paused(self, *, reason):
                    events.append('registry:paused')

            def run(args, **kwargs):
                operation = args[1]
                if operation == 'print':
                    return subprocess.CompletedProcess(args, 0)
                if operation == 'bootout':
                    events.append('launchctl:bootout')
                    current = plistlib.loads(destination.read_bytes())
                    self.assertNotIn('--dry-run', current['ProgramArguments'])
                    return subprocess.CompletedProcess(args, 0)
                if operation == 'bootstrap':
                    events.append('launchctl:bootstrap')
                    return subprocess.CompletedProcess(args, 0)
                raise AssertionError(args)

            result = installer.pause_to_dry_run(
                dry_plan, mode='serial', registry_control=Control(), state=state,
                home=home, run=run, uid=1,
            )

            self.assertLess(events.index('registry:stop'), events.index('launchctl:bootout'))
            self.assertLess(events.index('launchctl:bootout'), events.index('registry:paused'))
            self.assertLess(events.index('registry:paused'), events.index('launchctl:bootstrap'))
            paused = plistlib.loads(destination.read_bytes())
            self.assertIn('--dry-run', paused['ProgramArguments'])
            backup = result['backup_dir'] / destination.name
            self.assertNotIn('--dry-run', plistlib.loads(backup.read_bytes())['ProgramArguments'])

    def test_pause_refuses_loaded_service_without_reversible_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            control = Mock()
            calls = []

            def run(args, **kwargs):
                calls.append(args)
                loaded = args[1] == 'print' and args[-1].endswith(
                    installer.SERIAL_LABEL
                )
                return subprocess.CompletedProcess(args, 0 if loaded else 1)

            with self.assertRaisesRegex(ValueError, 'without plist backups'):
                installer.pause_to_dry_run(
                    self.plan(state), mode='serial', registry_control=control,
                    state=state, home=home, run=run, uid=1,
                )
            control.engage_stop.assert_called_once()
            control.finalize_paused.assert_not_called()
            self.assertFalse(any(call[1] in ('bootout', 'bootstrap') for call in calls))
            self.assertFalse((state / 'launchd-backups').exists())

    def test_pause_stop_failure_never_bootstraps_or_restores_live_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            live_plan = self.plan(state, mode='serial', live=True)
            destination = installer.label_path(installer.SERIAL_LABEL, home)
            installer.atomic_write_plist(destination, live_plan[0][1])
            control = Mock()
            calls = []

            def run(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0 if args[1] == 'print' else 1)

            with self.assertRaisesRegex(RuntimeError, 'could not stop live services'):
                installer.pause_to_dry_run(
                    self.plan(state), mode='serial', registry_control=control,
                    state=state, home=home, run=run, uid=1,
                )
            control.engage_stop.assert_called_once()
            control.finalize_paused.assert_not_called()
            self.assertFalse(any(call[1] == 'bootstrap' for call in calls))
            self.assertNotIn(
                '--dry-run', plistlib.loads(destination.read_bytes())['ProgramArguments']
            )

    def test_pause_bootstrap_failure_retains_paused_dry_run_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            destination = installer.label_path(installer.SERIAL_LABEL, home)
            installer.atomic_write_plist(
                destination, self.plan(state, mode='serial', live=True)[0][1]
            )
            control = Mock()

            def run(args, **kwargs):
                if args[1] == 'print':
                    return subprocess.CompletedProcess(args, 0)
                if args[1] == 'bootstrap':
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0)

            with self.assertRaisesRegex(RuntimeError, 'dry-run bootstrap failed'):
                installer.pause_to_dry_run(
                    self.plan(state), mode='serial', registry_control=control,
                    state=state, home=home, run=run, uid=1,
                )
            control.finalize_paused.assert_called_once()
            self.assertIn(
                '--dry-run', plistlib.loads(destination.read_bytes())['ProgramArguments']
            )

    def test_migration_refuses_loaded_service_without_a_recoverable_plist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            def loaded_run(args, **kwargs):
                return subprocess.CompletedProcess(args, 0 if args[1] == 'print' and args[-1].endswith('.codex-a') else 1)
            with self.assertRaisesRegex(ValueError, 'without plist backups'):
                installer.install(self.plan(state), mode='serial', replace_mode=True, state=state, home=home, run=loaded_run, uid=1)

    def test_bootstrap_failure_removes_only_new_files_and_restores_opposite_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state, home = root / 'state', root / 'home'
            old = installer.label_path(installer.SERIAL_LABEL, home)
            old.parent.mkdir(parents=True)
            old.write_text('serial backup')
            calls = []

            def run(args, **kwargs):
                calls.append(args)
                if args[1] == 'print':
                    loaded = args[-1].endswith('life.threadline.runner')
                    return subprocess.CompletedProcess(args, 0 if loaded else 1)
                if args[1] == 'bootstrap' and 'runner.codex-b' in args[-1]:
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0)

            with self.assertRaisesRegex(RuntimeError, 'installation failed'):
                installer.install(self.plan(state, mode='lanes'), mode='lanes', replace_mode=True, state=state, home=home, run=run, uid=1)
            self.assertEqual(old.read_text(), 'serial backup')
            self.assertFalse(installer.label_path('life.threadline.runner.codex-a', home).exists())
            self.assertTrue(any(call[1] == 'bootout' for call in calls))
            self.assertTrue(any(call[1] == 'bootstrap' and call[-1] == str(old) for call in calls))


if __name__ == '__main__':
    unittest.main()
