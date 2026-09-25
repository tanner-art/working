# Claude runner authentication on macOS

Claude runner credentials must stay out of repository files, runner JSON,
LaunchAgent plists, command arguments, and logs. The supported Factory path is
a Claude subscription setup token stored in the current macOS user's login
keychain and injected only into the Claude process environment.

## Why the wrapper exists

Some Claude Code releases can complete browser OAuth and print `Login
successful` without creating a durable keychain credential. The observable
failure pattern is:

- `claude auth login --claudeai` exits successfully;
- `~/.claude.json` contains account metadata;
- `claude auth status --json` immediately reports `loggedIn: false`;
- no usable credential exists in Keychain or `~/.claude/.credentials.json`.

Repeating browser login does not repair this persistence failure. The Factory
uses the documented long-lived setup-token path instead.

## One-time owner action

Run these steps as the same macOS user that owns the Factory LaunchAgent:

1. Run `claude setup-token` in a private interactive terminal and complete its
   browser flow.
2. Run the repository helper below. Paste the resulting token only at its
   masked prompt.

```sh
/absolute/path/to/python3 /absolute/path/to/threadline-repository/scripts/runner/claude_keychain.py store
```

The helper writes the token to the fixed
`life.threadline.factory.claude-setup-token` service for the effective local
user. It passes hex-encoded credential data to `/usr/bin/security` over stdin;
the token is not a shell argument or command-history entry.

Do not paste the token into `config.json`, a plist, an environment file, a
repository file, an issue, or a chat.

## Runner configuration

Prefix both Claude commands with the helper and its `exec` operation:

```json
{
  "command": [
    "/absolute/path/to/python3",
    "/absolute/path/to/release/scripts/runner/claude_keychain.py",
    "exec",
    "/absolute/path/to/claude",
    "-p"
  ],
  "env": {}
}
```

Keep the normal Claude model, permission, output, and tool arguments after
`-p`. Do not add `CLAUDE_CODE_OAUTH_TOKEN` to `env`. The wrapper resolves the
account from its effective uid, retrieves the fixed keychain item, sets the
token in a copied process environment, and replaces itself with the absolute
Claude executable. Lookup failures exit with status 78 and a credential-free
message.

## Verification before service load

First confirm that the keychain item exists without reading its value:

```sh
security find-generic-password \
  -a "$(id -un)" \
  -s life.threadline.factory.claude-setup-token >/dev/null
```

Then run the configured wrapper with `claude auth status --json` under the
same minimal identity environment used by launchd. Use the actual paths from
the installed plist and runner config:

```sh
env -i \
  HOME="$HOME" \
  USER="$(id -un)" \
  TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)" \
  PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  /absolute/path/to/python3 \
  /absolute/path/to/release/scripts/runner/claude_keychain.py exec \
  /absolute/path/to/claude auth status --json
```

Require `loggedIn: true`, then make one minimal non-interactive call through
the full configured command. Only after both checks pass should the Claude
LaunchAgent be loaded or reloaded in PAUSED / DRY-RUN mode. Repeat the status
and invocation checks after reload before declaring authentication healthy.
