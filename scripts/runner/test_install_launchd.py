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
                    return subprocess.CompletedProcess(args, 1)
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
