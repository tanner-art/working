#!/usr/bin/env python3
"""Run Claude with a setup token held only in the macOS login keychain."""
import getpass
import os
import pathlib
import pwd
import re
import subprocess
import sys


KEYCHAIN_SERVICE = 'life.threadline.factory.claude-setup-token'
SECURITY = '/usr/bin/security'
EX_CONFIG = 78
MAX_TOKEN_LENGTH = 8192
SAFE_ACCOUNT = re.compile(r'^[A-Za-z0-9._-]+$')


class CredentialUnavailable(RuntimeError):
    """The configured keychain credential cannot be used."""


def account_identity():
    """Resolve the effective user's account and explicit login keychain."""
    record = pwd.getpwuid(os.geteuid())
    account = record.pw_name
    if not SAFE_ACCOUNT.fullmatch(account):
        raise CredentialUnavailable('local account name is not keychain-safe')
    home = pathlib.Path(record.pw_dir)
    if not home.is_absolute():
        raise CredentialUnavailable('local account home is not an absolute path')
    return account, str(home / 'Library' / 'Keychains' / 'login.keychain-db')


def _security_quote(value):
    """Quote trusted local identity paths for security's interactive parser."""
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def validate_token(token):
    """Reject empty, multiline, control-character, or implausibly large values."""
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
        raise CredentialUnavailable('Claude setup token is missing or invalid')
    if any(ord(character) < 33 or ord(character) > 126 for character in token):
        raise CredentialUnavailable('Claude setup token is missing or invalid')
    return token


def load_token(run=subprocess.run):
    """Read the fixed credential without exposing its value in argv or logs."""
    account, keychain = account_identity()
    try:
        result = run(
            [SECURITY, 'find-generic-password', '-a', account,
             '-s', KEYCHAIN_SERVICE, '-w', keychain],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialUnavailable('macOS Keychain lookup failed') from exc
    if result.returncode != 0:
        raise CredentialUnavailable(
            f'no Claude setup token is available for {account} in '
            f'{KEYCHAIN_SERVICE}'
        )
    return validate_token(result.stdout.rstrip('\r\n'))


def store_token(token, run=subprocess.run):
    """Write through security stdin so the token never appears in argv."""
    token = validate_token(token)
    account, keychain = account_identity()
    encoded = token.encode('utf-8').hex()
    command = (
        f'add-generic-password -U -a "{account}" '
        f'-s "{KEYCHAIN_SERVICE}" -X "{encoded}" {_security_quote(keychain)}\n'
    )
    try:
        result = run(
            [SECURITY, '-i'], input=command, capture_output=True,
            text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialUnavailable('macOS Keychain write failed') from exc
    if result.returncode != 0:
        raise CredentialUnavailable('macOS Keychain write failed')
    return account


def exec_claude(command, *, run=subprocess.run, execve=os.execve):
    """Replace this process with Claude after injecting the keychain token."""
    if not command or not os.path.isabs(command[0]):
        raise CredentialUnavailable('Claude command must start with an absolute executable path')
    token = load_token(run)
    environment = os.environ.copy()
    environment['CLAUDE_CODE_OAUTH_TOKEN'] = token
    execve(command[0], command, environment)


def main(argv=None, *, run=subprocess.run, execve=os.execve,
         prompt=getpass.getpass):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ['store'] and len(argv) == 1:
            account = store_token(prompt('Paste Claude setup token: '), run)
            print(f'Stored Claude setup token for {account} in {KEYCHAIN_SERVICE}.')
            return 0
        if argv[:1] == ['exec'] and len(argv) > 1:
            exec_claude(argv[1:], run=run, execve=execve)
            return 0
        print(
            'usage: claude_keychain.py store | exec /absolute/path/to/claude [args...]',
            file=sys.stderr,
        )
        return EX_CONFIG
    except CredentialUnavailable as exc:
        print(f'Claude authentication unavailable: {exc}', file=sys.stderr)
        return EX_CONFIG


if __name__ == '__main__':
    raise SystemExit(main())
