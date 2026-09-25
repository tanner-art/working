import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

import claude_keychain as keychain


class ClaudeKeychainTests(unittest.TestCase):
    def test_account_identity_uses_effective_uid_and_passwd_home(self):
        account = type('Account', (), {
            'pw_name': 'runner-user', 'pw_dir': '/Users/runner-user',
        })()
        with patch.object(keychain.os, 'geteuid', return_value=501), \
                patch.object(keychain.pwd, 'getpwuid', return_value=account) as lookup:
            self.assertEqual(keychain.account_identity(), (
                'runner-user',
                '/Users/runner-user/Library/Keychains/login.keychain-db',
            ))
        lookup.assert_called_once_with(501)

    def test_load_uses_fixed_service_and_effective_user(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, 'setup-token\n', '')

        with patch.object(keychain, 'account_identity', return_value=(
            'runner-user', '/Users/runner-user/Library/Keychains/login.keychain-db',
        )):
            self.assertEqual(keychain.load_token(run), 'setup-token')

        self.assertEqual(calls[0][0], [
            '/usr/bin/security', 'find-generic-password', '-a', 'runner-user',
            '-s', 'life.threadline.factory.claude-setup-token', '-w',
            '/Users/runner-user/Library/Keychains/login.keychain-db',
        ])
        self.assertTrue(calls[0][1]['capture_output'])

    def test_exec_injects_token_only_into_child_environment(self):
        captured = {}

        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, 'secret-value\n', '')

        def execve(executable, command, environment):
            captured.update(
                executable=executable, command=command, environment=environment,
            )

        with patch.object(keychain, 'account_identity', return_value=(
            'runner-user', '/Users/runner-user/Library/Keychains/login.keychain-db',
        )):
            keychain.exec_claude(
                ['/opt/homebrew/bin/claude', '-p', '--model', 'sonnet'],
                run=run, execve=execve,
            )

        self.assertEqual(captured['executable'], '/opt/homebrew/bin/claude')
        self.assertEqual(captured['command'], [
            '/opt/homebrew/bin/claude', '-p', '--model', 'sonnet',
        ])
        self.assertEqual(captured['environment']['CLAUDE_CODE_OAUTH_TOKEN'],
                         'secret-value')
        self.assertNotIn('secret-value', captured['command'])

    def test_missing_credential_reports_only_non_secret_context(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 44, '', 'sensitive diagnostic')

        stderr = io.StringIO()
        with patch.object(keychain, 'account_identity', return_value=(
                'runner-user', '/Users/runner-user/Library/Keychains/login.keychain-db',
        )), \
                contextlib.redirect_stderr(stderr):
            status = keychain.main(
                ['exec', '/opt/homebrew/bin/claude', '-p'], run=run,
                execve=lambda *_: self.fail('exec must not run'),
            )

        self.assertEqual(status, keychain.EX_CONFIG)
        self.assertIn(keychain.KEYCHAIN_SERVICE, stderr.getvalue())
        self.assertNotIn('sensitive diagnostic', stderr.getvalue())

    def test_store_uses_security_stdin_and_never_token_argv(self):
        captured = {}

        def run(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            return subprocess.CompletedProcess(command, 0, '', '')

        with patch.object(keychain, 'account_identity', return_value=(
            'runner-user', '/Users/runner-user/Library/Keychains/login.keychain-db',
        )):
            account = keychain.store_token('secret-value', run)

        self.assertEqual(account, 'runner-user')
        self.assertEqual(captured['command'], ['/usr/bin/security', '-i'])
        self.assertNotIn('secret-value', captured['command'])
        self.assertNotIn('secret-value', captured['kwargs']['input'])
        self.assertEqual(captured['kwargs']['input'], (
            'add-generic-password -U -a "runner-user" '
            '-s "life.threadline.factory.claude-setup-token" '
            '-X "7365637265742d76616c7565" '
            '"/Users/runner-user/Library/Keychains/login.keychain-db"\n'
        ))

    def test_store_prompt_output_has_no_token(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, '', '')

        stdout = io.StringIO()
        with patch.object(keychain, 'account_identity', return_value=(
                'runner-user', '/Users/runner-user/Library/Keychains/login.keychain-db',
        )), \
                contextlib.redirect_stdout(stdout):
            status = keychain.main(
                ['store'], run=run, prompt=lambda _: 'secret-value',
            )

        self.assertEqual(status, 0)
        self.assertIn(keychain.KEYCHAIN_SERVICE, stdout.getvalue())
        self.assertNotIn('secret-value', stdout.getvalue())

    def test_rejects_relative_executable_and_non_printable_token(self):
        with self.assertRaisesRegex(keychain.CredentialUnavailable, 'absolute'):
            keychain.exec_claude(['claude'], execve=lambda *_: None)
        for token in ('', 'token with spaces', 'token\nsecond', 'x' * 8193):
            with self.subTest(token_length=len(token)):
                with self.assertRaisesRegex(keychain.CredentialUnavailable, 'invalid'):
                    keychain.validate_token(token)


if __name__ == '__main__':
    unittest.main()
