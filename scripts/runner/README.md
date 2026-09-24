# Threadline local runner (TASK-015)

A single Mac polls authorized GitHub issues every minute through launchd. It runs one task at a time, starts each attempt from fetched origin/main in a new worktree, invokes its assigned CLI, validates with pnpm check, commits, pushes a new branch, and opens a draft PR. It never merges. Old worktrees and failed attempts are retained.

## Queue contract

Create an issue authored by an allowed account with labels `runner:ready` and exactly one of `agent:codex-a`, `agent:codex-b`, `agent:claude`. Its entire body is JSON:

```json
{"task":"TASK-016","paths":["docs/RUNNER_SMOKE.md"],"instructions":"Create a short note explaining that PRs require human review.","depends_on":[]}
```

Paths are exact files, not directories or globs. Dependencies are issue numbers which must be closed. Only explicitly approved tasks belong in this queue. The runner does not infer readiness from TASKS.md or dispatch product backlog automatically.

## Setup and operation

Copy and edit `config.example.json` for the host. Every path, repository owner, account name, executable, and model name in that file is a placeholder; replace it before use. Keep credentials in the installed CLI’s authenticated profile or host keychain, never in this JSON file. `github.py` uses the existing Git credential for GitHub only, with no token file or logging. Headless Codex follows its workspace sandbox; Claude has only file tools and the runner performs validation. Agent CLI auth must already exist.

Each agent needs `provider`, `account`, `model`, `command`, `fallback_model`, and `fallback_command`. It may also set `slots` from 1 through 3; omission preserves the original single lane. The example uses two Codex A slots, one Codex B slot, and two Claude slots. Slot one preserves the existing service label, arguments, and log names. Additional services use labels such as `life.threadline.runner.codex-a-2`, pass `--slot 2`, and write logs such as `launchd-codex-a-2.log`.

Slots are external, runner-controlled provider child lanes and are the only production fan-out mechanism initially. Every slot launches a foreground CLI process in the runner-created task worktree, so scope locks, process-group termination, validation serialization, and preserved failures remain visible to the factory. Runner installation rejects primary or fallback Codex commands that do not explicitly disable `multi_agent`, and rejects Claude commands without an explicit tool allowlist or with `Agent` in that allowlist. Do not start detached provider jobs such as `claude --background` from a lane: detached work can escape task ownership, timeout handling, and dashboard accounting. Native provider subagents are a later option and should initially be limited to read-only review; writing remains owned by the runner lane.

All slots for an agent use the same configured `account` and therefore share that account's credentials, quota, and single usage record. Extra lanes do not create extra provider capacity. Configure more than one slot only when that exact worker/account has a fresh green usage observation below 70%; slow, stopped, missing, and stale usage do not authorize fan-out. The 70% slowdown and 80% stop thresholds apply to the shared account across its slots. The installer does not read provider credentials or perform authentication probes. Before installing extra Claude slots, the operator must run a successful non-interactive authentication check in the same `HOME` and keychain context that launchd will use. Never copy credentials into this file or weaken TLS.

The example uses Terra as the primary Codex tier with Luna as its lower-cost fallback, and Sonnet with Haiku for Claude. These are replaceable, model-agnostic examples: choose model names and command flags supported by the installed CLI on the host. Use distinct account names and authentication homes only when workers truly have separate provider budgets.

Usage gating reads `usage.json` from the configured state directory unless `usage_file` sets another local path. It is keyed by worker, then account, so one worker can track separate account budgets:

```json
{
  "codex-a": {
    "openai-account-a": {
      "provider": "openai",
      "model": "gpt-5.6-terra",
      "used_percent": 42.5,
      "observed_at": "2026-09-22T10:00:00Z",
      "reset_at": "2026-09-22T15:00:00Z"
    }
  }
}
```

The example policy slows a worker at 70% usage and stops it at 80%. A usage record older than `stale_after_seconds`, missing for its worker/account, or dated in the future is unknown. With `unknown_behavior: "slow"`, unknown and 70–79.99% usage use the configured low-cost fallback command; 80% or more stops dispatch. If the usage file itself is unavailable or malformed, the runner defers work rather than claiming it. A missing fallback command also defers safely.

## Usage-feed refresh

Refresh usage immediately before a runner poll with the runner configuration. The feed discovers every configured OpenAI worker's `env.CODEX_HOME`, account, and model, and treats every configured Claude worker as unknown. The home is passed only to the local Codex app-server process; it is not written to the feed or echoed by the command.

```sh
python3 scripts/runner/usage_feed.py --config /absolute/config.json \
  --usage /absolute/state/usage.json
```

For each Codex home, the feed initializes the installed local `codex app-server`, requests `account/rateLimits/read`, and keeps the highest reported `used_percent` window. It atomically replaces the feed using a private, fsynced temporary file, containing only provider, model, used percentage, observation time, and that window's reset time. A failed, logged-out, malformed, or timed-out observation leaves its prior valid record untouched; normal runner stale policy still makes an old record unknown.

There is no documented authenticated Claude percentage source in this slice. A configured Claude worker is explicitly unknown; it never creates or refreshes a green record. For one-off operation without `--config`, list targets with matching `--codex-home WORKER/ACCOUNT=CODEX_HOME` and `--codex-model WORKER/ACCOUNT=MODEL`, and list Claude with `--claude WORKER/ACCOUNT=unavailable`. Do not substitute scraped CLI output, account data, email addresses, tokens, commands, or raw provider responses. The command prints only update and unknown counts. This slice does not install a launchd job; schedule the operator command through the host's existing operational process.

Run `python3 scripts/runner/runner.py --config /absolute/config.json --dry-run` to inspect the queue without mutation. Run without `--dry-run` for one poll. Install with `python3 scripts/runner/install_launchd.py --config /absolute/config.json`; installation defaults to dry-run. `--live` enables execution explicitly. The default `--mode serial` preserves the one-runner setup. `--mode lanes` installs each agent's configured number of external lanes plus a read-only dashboard bound to `127.0.0.1`; use `--replace-mode` only to explicitly migrate between serial and lanes. To promote installed dry-run services to live services in the same mode, or to apply a reviewed slot-count change, use `--live --replace-current`; it backs up the current plists and restores them if bootstrap fails. These replacement flags cannot be combined. launchd uses the configured PATH and runs at login and every 60 seconds; it does not run while the user is logged out or the Mac is asleep.

Status is in the configured state directory: heartbeat.json, issue-N.json, per-attempt logs, launchd logs. GitHub labels transition ready → running → review or failed. No automatic retry: use `--retry N` after inspecting the failure. Retrying creates a new attempt and retains the old one; inspect existing pushed branches/PRs before retrying a publication failure. A crash leaves a durable starting/running record and is not silently redispatched. Reboot recovery requires inspection and explicit retry after labeling the issue runner:failed. Keep one service/config per repository; the lock coordinates processes sharing that state directory.

Stop services with `launchctl bootout gui/$(id -u)/<label>`; serial uses `life.threadline.runner`, while lane mode uses slot-one labels `life.threadline.runner.codex-a`, `.codex-b`, and `.claude`, optional child labels ending in `-2` or `-3`, and `life.threadline.factory-dashboard`. Logs need periodic retention management; task logs may contain source code. Merge and issue closure remain human responsibilities. An independent reviewer must assess code before merge. The daemon does not advance task-board status or assume that a PR is approved.

## Verification

`python3 -m unittest discover -s scripts/runner -v` tests queue rejection rules. `pnpm check` remains the application gate. Installed Codex 0.154.0 uses `codex exec --ignore-user-config -s workspace-write --json -`; see [official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Installed Claude supports `-p --permission-mode acceptEdits --permission-prompts none`.

The scope checks detect unintended agent edits before staging, but are not an OS security boundary. Do not queue untrusted issue text or use this as a multi-tenant execution service. A task that changes its own validation tooling needs especially careful review.
