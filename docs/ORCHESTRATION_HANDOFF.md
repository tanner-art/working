# Orchestration Handoff

Threadline orchestration may move between Codex A and Codex B when one account is near its usage reserve. The orchestrator role is account-agnostic: either agent can coordinate as long as it preserves the rules below.

In this repo, "Codex A" maps to the runner label `agent:codex-a`, "Codex B" maps to `agent:codex-b`, and Claude maps to `agent:claude`.

## Usage Reserve

- Keep the active orchestrator below 82% usage when possible.
- At or above 82%, stop using that account for implementation. Use it only for brief coordination, blocker triage, and preserving handoff state.
- Push substantial product implementation to Codex A, Codex B, or Claude through assigned tasks and reviewable pull requests.
- Codex A usage telemetry is not exposed by the CLI, so run at most one bounded Codex A task at a time unless a human confirms more capacity.

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

- Keep `main` current before assigning the next implementation task; recently merged app work includes TASK-024 shape palette, TASK-025 iPhone home-screen safe-area controls, TASK-029 Supabase login wiring, and TASK-038 mobile-first capture/organize cleanup.
- Move immediate product usability forward next: user-scoped Supabase storage, hosted login validation, provider-backed AI interpretation, mobile onboarding/home-screen help, Settings as a control center, and Organize folders.
- Continue app-moving product work before deeper engineering-assurance work unless the user redirects.
- For the next 24-hour push, every assigned task should map to one of five outcomes: fast capture, safe user data, confirm/organize meaning, mobile usability, or real AI interpretation. Do not spend agent cycles on process polish unless it directly helps those outcomes ship faster.

## Build In Public Notes

Threadline is being built in public as a visible record of how a nontraditional technical founder builds an AI-native product with agents. Orchestration should preserve that story without slowing the app down.

For each visible product PR, include a short plain-language progress note in the PR or issue that says what changed for users, what remains limited, and what is next. Keep raw provenance and private details out of public artifacts unless the user explicitly approves sharing them. Use `docs/provenance` and `docs/DECISIONS.md` for durable decision history, but keep implementation tasks focused on shipping usable product behavior.
