# Threadline local runner (TASK-015)

A single Mac polls authorized GitHub issues every minute through launchd. It runs one task at a time, starts each attempt from fetched origin/main in a new worktree, invokes its assigned CLI, validates with pnpm check, commits, pushes a new branch, and opens a draft PR. It never merges. Old worktrees and failed attempts are retained.

## Queue contract

Create an issue authored by an allowed account with labels `runner:ready` and exactly one of `agent:codex-a`, `agent:codex-b`, `agent:claude`. Its entire body is JSON:

```json
{"task":"TASK-016","paths":["docs/RUNNER_SMOKE.md"],"instructions":"Create a short note explaining that PRs require human review.","depends_on":[],"lane":"ASSURANCE","kind":"REVIEW","capacity_size":"VERY_SMALL","capacity_risk":"BOUNDED"}
```

Paths are exact files, not directories or globs. Dependencies are issue numbers which must be closed. `lane` is `FEATURE`, `PLATFORM`, or `ASSURANCE`; `kind` is `PARENT`, `TEST`, `REVIEW`, or `EVALUATION`. Capacity size is `VERY_SMALL`, `SMALL`, or `SUBSTANTIAL`, and risk is `BOUNDED`, `UNCERTAIN`, or `EMERGENCY_RECOVERY`. Missing classification defaults conservatively to a substantial, uncertain FEATURE parent. Only explicitly approved tasks belong in this queue. The runner does not infer readiness from TASKS.md or dispatch product backlog automatically.

## Setup and operation

Copy and edit `config.example.json` for the host. Every path, repository owner, account name, executable, and model name in that file is a placeholder; replace it before use. `registry_database` enables the authoritative Registry path; live runners then require an eligible Registry package/worker pair and a LIVE revision before claiming, acquire a revision-pinned lease, and reserve the attempt. `registry_renew_interval_seconds` must be shorter than `registry_lease_seconds`; the main runner thread renews ownership during setup, provider work, validation, push, and PR creation. Provider code waits behind an exec gate until its PID/PGID is durably bound. Keep credentials in the installed CLI’s authenticated profile or host keychain, never in this JSON file. `github.py` uses the existing Git credential for GitHub only, with no token file or logging. Headless Codex follows its workspace sandbox; Claude has only file tools and the runner performs validation. Agent CLI auth must already exist.

On macOS, the example Claude command uses `claude_keychain.py exec` because some Claude Code releases can report a successful subscription login without persisting it. Create a long-lived token yourself with `claude setup-token`, then store it without echoing it or putting it in shell history:

```sh
/absolute/path/to/python3 /absolute/path/to/threadline-repository/scripts/runner/claude_keychain.py store
```

The masked prompt writes to the fixed `life.threadline.factory.claude-setup-token` service in the effective user’s explicit `~/Library/Keychains/login.keychain-db`. The wrapper resolves both the account and home from that user’s system account record, reads that exact keychain at launch, exports `CLAUDE_CODE_OAUTH_TOKEN` only in the Claude process environment, and replaces itself with the configured absolute Claude executable. The token is never placed in the runner JSON, launchd plist, command arguments, repository, or logs. Run the store command as the same macOS user that owns the LaunchAgent. Installer and runtime validation reject `CLAUDE_CODE_OAUTH_TOKEN` and raw Claude setup-token values in every configured agent `env` object. The full setup and exact-environment verification runbook is in [Claude runner authentication](../../docs/factory/CLAUDE_AUTH.md).

Each agent needs `provider`, `account`, `model`, and `command`. Legacy
`fallback_model` and `fallback_command` values may remain configured, but the
staged capacity policy does not select them. An agent may also set `slots` from
1 through 3; omission preserves the original single lane. The example uses two
Codex A slots, one Codex B slot, and two Claude slots. Slot one preserves the
existing service label, arguments, and log names. Additional services use
labels such as `life.threadline.runner.codex-a-2`, pass `--slot 2`, and write
logs such as `launchd-codex-a-2.log`.

Slots are external, runner-controlled provider child lanes and are the only production fan-out mechanism initially. Every slot launches a foreground CLI process in the runner-created task worktree, so scope locks, process-group termination, validation serialization, and preserved failures remain visible to the factory. Runner installation rejects primary or fallback Codex commands that do not explicitly disable `multi_agent`, and rejects Claude commands without an explicit tool allowlist or with `Agent` in that allowlist. Do not start detached provider jobs such as `claude --background` from a lane: detached work can escape task ownership, timeout handling, and dashboard accounting. Native provider subagents are a later option and should initially be limited to read-only review; writing remains owned by the runner lane.

All slots for an agent use the same configured `account` and therefore share that account's credentials and capacity observations. Extra lanes do not create extra provider capacity. Extra lanes require fresh eligible capacity, and every candidate still passes its package size/risk gate. Missing and stale telemetry do not authorize fan-out. The installer does not read provider credentials or perform authentication probes. Before installing extra Claude slots, the operator must run the configured wrapper with `auth status` and a minimal non-interactive invocation in the same `HOME`, `USER`, `TMPDIR`, `PATH`, and keychain context that launchd will use. Never copy credentials into this file or weaken TLS.

The example uses Terra as the primary Codex tier with Luna as its lower-cost fallback, and Sonnet with Haiku for Claude. These are replaceable, model-agnostic examples: choose model names and command flags supported by the installed CLI on the host. Use distinct account names and authentication homes only when workers truly have separate provider budgets.

Usage gating reads `usage.json` from the configured state directory unless `usage_file` sets another local path. It is keyed by worker, then account, so one worker can track separate account budgets:

```json
{
  "codex-a": {
    "openai-account-a": {
      "provider": "openai",
      "model": "gpt-5.6-terra",
      "capacity_mode": "percentage",
      "scopes": {
        "short_window": {
          "used_percent": 0,
          "observed_at": "2026-09-24T19:00:00Z",
          "reset_at": "2026-09-25T00:00:00Z"
        },
        "weekly_window": {
          "used_percent": 73,
          "observed_at": "2026-09-24T19:00:00Z",
          "reset_at": "2026-09-29T00:00:00Z"
        }
      }
    }
  }
}
```

Every configured percentage scope must be present and fresh; the most
restrictive scope controls dispatch. A fresh short window and 73% weekly usage
is therefore normal. Percentage records use the ratified stages: below 90%
normal; 90–95% caution; 95–98% checkpoint; and 98% hard stop. Caution and
checkpoint reject substantial or uncertain parents. Hard stop permits only
emergency recovery or very small bounded ASSURANCE work. Crossing 95% never
terminates a healthy invocation; it reaches a clean checkpoint and prevents
another substantial dispatch. A scope older than `stale_after_seconds`,
missing, or dated in the future constrains the worker and defers work by
default. Capacity stages do not select a fallback model.

Workers without provider percentages use a structured `provider_signal` record:

```json
{
  "claude": {
    "anthropic-account-a": {
      "provider": "anthropic",
      "model": "claude-sonnet",
      "capacity_mode": "provider_signal",
      "service_state": "healthy",
      "authentication_state": "valid",
      "live_invocation_state": "succeeded",
      "limit_signal": "NONE",
      "observed_at": "2026-09-24T19:00:00Z"
    }
  }
}
```

The allowed actual limit signals are `RATE_LIMIT`, `EXHAUSTION`, `THROTTLING`,
and `CAPACITY_LAUNCH_FAILURE`. They constrain the worker and remain available
for calibration. `NONE` with fresh healthy service/auth/live-invocation
evidence keeps the worker normally eligible without inventing a percentage.

Run `python3 scripts/runner/runner.py --config /absolute/config.json --dry-run` to inspect the queue without mutation. Run without `--dry-run` for one poll. Install with `python3 scripts/runner/install_launchd.py --config /absolute/config.json`; installation defaults to dry-run. `--live` enables execution explicitly. The default `--mode serial` preserves the one-runner setup. `--mode lanes` installs each agent's configured number of external lanes plus a read-only dashboard bound to `127.0.0.1`; use `--replace-mode` only to explicitly migrate between serial and lanes. To promote installed dry-run services to live services in the same mode, or to apply a reviewed slot-count change, use `--live --replace-current`; it backs up the current plists and restores them if bootstrap fails. These replacement flags cannot be combined. launchd uses the configured PATH and runs at login and every 60 seconds; it does not run while the user is logged out or the Mac is asleep.

Status is in the configured state directory: heartbeat.json, issue-N.json, per-attempt logs, launchd logs. GitHub labels transition ready → running → review or failed. No automatic retry: use `--retry N` after inspecting the failure. Retrying creates a new attempt and retains the old one; inspect existing pushed branches/PRs before retrying a publication failure. A crash leaves a durable starting/running record and is not silently redispatched. Reboot recovery requires inspection and explicit retry after labeling the issue runner:failed. Keep one service/config per repository; the lock coordinates processes sharing that state directory.

Stop services with `launchctl bootout gui/$(id -u)/<label>`; serial uses `life.threadline.runner`, while lane mode uses slot-one labels `life.threadline.runner.codex-a`, `.codex-b`, and `.claude`, optional child labels ending in `-2` or `-3`, and `life.threadline.factory-dashboard`. Logs need periodic retention management; task logs may contain source code. Merge and issue closure remain human responsibilities. An independent reviewer must assess code before merge. The daemon does not advance task-board status or assume that a PR is approved.

## Verification

`python3 -m unittest discover -s scripts/runner -v` tests queue rejection rules. `pnpm check` remains the application gate. Installed Codex 0.154.0 uses `codex exec --ignore-user-config -s workspace-write --json -`; see [official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Installed Claude supports `-p --permission-mode acceptEdits --permission-prompts none`.

The scope checks detect unintended agent edits before staging, but are not an OS security boundary. Do not queue untrusted issue text or use this as a multi-tenant execution service. A task that changes its own validation tooling needs especially careful review.
