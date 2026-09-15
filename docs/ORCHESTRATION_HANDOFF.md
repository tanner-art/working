# Orchestration Handoff

Threadline orchestration may move between Agent A and Agent B when one account is near its usage reserve. The orchestrator role is account-agnostic: either agent can coordinate as long as it preserves the rules below.

## Usage Reserve

- Keep the active orchestrator below 82% usage when possible.
- At or above 82%, stop using that account for implementation. Use it only for brief coordination, blocker triage, and preserving handoff state.
- Push substantial product implementation to Agent A or Claude through assigned tasks and reviewable pull requests.
- Agent A usage telemetry is not exposed by the CLI, so run at most one bounded Agent A task at a time unless a human confirms more capacity.

## Canonical State To Check First

Before taking over, inspect:

1. `/Users/domitian/Documents/Codex/working`
2. `/Users/domitian/Documents/Codex/threadline-agent-worktrees`
3. `/Users/domitian/Documents/Codex/threadline-runner-state`
4. `TASKS.md`
5. `AGENTS.md`
6. Open GitHub issues and PRs for `tanner-art/working`
7. The heartbeat automation `orchestrate-threadline-app-development`

Do not reset, rebase, clean, delete worktrees, or discard uncommitted changes during takeover.

## Runner Dispatch

The local runner lives at `/Users/domitian/Documents/Codex/working-runner/scripts/runner`.

Queue work by creating a GitHub issue authored by an allowed account with:

- label `runner:ready`
- exactly one agent label: `agent:codex-a`, `agent:codex-b`, or `agent:claude`
- JSON body with `task`, exact `paths`, `instructions`, and `depends_on`

The runner creates an isolated worktree from `origin/main`, runs the assigned agent, validates with `pnpm check` and `git diff --check`, commits, pushes a branch, and opens a draft PR. It never merges.

## Review And Merge

- The implementer must not be the only reviewer.
- Merge only after independent review and validation.
- Keep every GitHub issue and PR updated with an `### Exact response to move forward` section.
- If user action is required, create or update one issue titled `NEEDS USER ACTION:` with the mobile-safe action, consequence, and exact response.

## Current High-Priority Queue

- Integrate approved Agent A `TASK-024` shapes PR after authenticated review/CI path is available.
- Assign `TASK-025` for iPhone home-screen safe-area controls.
- Continue app-moving product work before deeper engineering-assurance work unless the user redirects.
