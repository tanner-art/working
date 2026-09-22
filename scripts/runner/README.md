# Threadline local runner (TASK-015)

A single Mac polls authorized GitHub issues every minute through launchd. It runs one task at a time, starts each attempt from fetched origin/main in a new worktree, invokes its assigned CLI, validates with pnpm check, commits, pushes a new branch, and opens a draft PR. It never merges. Old worktrees and failed attempts are retained.

## Queue contract

Create an issue authored by an allowed account with labels `runner:ready` and exactly one of `agent:codex-a`, `agent:codex-b`, `agent:claude`. Its entire body is JSON:

```json
{"task":"TASK-016","paths":["docs/RUNNER_SMOKE.md"],"instructions":"Create a short note explaining that PRs require human review.","depends_on":[]}
```

Paths are exact files, not directories or globs. Dependencies are issue numbers which must be closed. Only explicitly approved tasks belong in this queue. The runner does not infer readiness from TASKS.md or dispatch product backlog automatically.

## Setup and operation

Copy and edit config.example.json for the host; use absolute executable paths and distinct Codex homes. `github.py` uses the existing Git credential for GitHub only, with no token file or logging. It currently targets github.com and the Homebrew gh path. No organization scope is required. Headless Codex follows its workspace sandbox; Claude has only file tools and the runner performs validation. Agent CLI auth must already exist.

Run `python3 scripts/runner/runner.py --config /absolute/config.json --dry-run` to inspect the queue without mutation. Run without `--dry-run` for one poll. Install with `python3 scripts/runner/install_launchd.py --config /absolute/config.json`; installation defaults to dry-run. `--live` enables execution explicitly. The default `--mode serial` preserves the one-runner setup. `--mode lanes` installs the three fixed agent lanes plus a read-only dashboard bound to `127.0.0.1`; use `--replace-mode` only to explicitly migrate between serial and lanes. launchd uses the configured PATH and runs at login and every 60 seconds; it does not run while the user is logged out or the Mac is asleep.

Status is in the configured state directory: heartbeat.json, issue-N.json, per-attempt logs, launchd logs. GitHub labels transition ready → running → review or failed. No automatic retry: use `--retry N` after inspecting the failure. Retrying creates a new attempt and retains the old one; inspect existing pushed branches/PRs before retrying a publication failure. A crash leaves a durable starting/running record and is not silently redispatched. Reboot recovery requires inspection and explicit retry after labeling the issue runner:failed. Keep one service/config per repository; the lock coordinates processes sharing that state directory.

Stop services with `launchctl bootout gui/$(id -u)/<label>`; serial uses `life.threadline.runner`, while lane mode uses `life.threadline.runner.codex-a`, `.codex-b`, `.claude`, and `life.threadline.factory-dashboard`. Logs need periodic retention management; task logs may contain source code. Merge and issue closure remain human responsibilities. An independent reviewer must assess code before merge. The daemon does not advance task-board status or assume that a PR is approved.

## Verification

`python3 -m unittest discover -s scripts/runner -v` tests queue rejection rules. `pnpm check` remains the application gate. Installed Codex 0.154.0 uses `codex exec --ignore-user-config -s workspace-write --json -`; see [official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Installed Claude supports `-p --permission-mode acceptEdits --permission-prompts none`.

The scope checks detect unintended agent edits before staging, but are not an OS security boundary. Do not queue untrusted issue text or use this as a multi-tenant execution service. A task that changes its own validation tooling needs especially careful review.
