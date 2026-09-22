import pathlib
import plistlib
import subprocess
import tempfile
import unittest

import install_launchd as installer


class LaunchdInstallerTests(unittest.TestCase):
    def config(self, state):
        return {
            'state': str(state), 'path': '/usr/bin:/bin',
            'agents': {agent: {'command': ['agent', agent], 'env': {'SECRET': 'do-not-copy'}} for agent in installer.LANE_AGENTS},
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
            dashboard = plan[-1][1]
            self.assertEqual(dashboard['ProgramArguments'][-4:], ['--host', '127.0.0.1', '--port', '8787'])
            self.assertNotIn('StartInterval', dashboard)
            dumped = plistlib.dumps(dashboard).decode()
            self.assertNotIn('do-not-copy', dumped)
            self.assertNotIn('agent codex-a', dumped)

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
