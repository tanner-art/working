# Threadline takeover inventory — 2026-09-13

Inspected before any cleanup. No reset, rebase, branch deletion, or worktree removal performed.

| Worktree / branch | HEAD | Dirty/staged/untracked | Unique against main | Remote |
|---|---|---|---|---|
| working / main | 88ed680c976a60de3cb810e4a5ff51c57363ac52 | none | canonical | exact match verified by ls-remote |
| working-codex-a / agent/codex-a | 3accbd5336e89763fd19a2e834de42efd5ffab71 | none, including ignored-file check | none | exact match |
| working-codex-b / agent/codex-b | 0257d2ad62887e811358930094750fdeb5b0b662 | none | 111426b, merge 6ccf047, 0795769, 0257d2a | exact match |
| working-claude / agent/claude | 6c4f89041ff44164804b5b514d0ec0110a9be51c | none | six doc commits | exact match |
| wip/pre-orchestration (no checkout) | 7c0ee6b1f6484f6929c8dbcd6f40af59b9953cb4 | n/a | intentionally archived application work | exact match |

Canonical main fetch verified; pnpm check passed 18 tests, TypeScript, production build. No configured lint script. Read AGENTS.md, TASKS.md, NORTH_STAR, ARCHITECTURE, DECISIONS, ROADMAP, ARCHIVE_SALVAGE_AUDIT, IMPLEMENTATION_STATUS, QA_CHECKLIST.

## Processes and recovery

At inventory, Codex B PID 24505 (parent 24504) had cwd working-codex-b; Codex A PID 24600 (parent 24599) had cwd working-codex-a. Claude PID 24788 had cwd working-claude and command `Claude -- version`. Existing desktop Codex and Claude services also ran; Vite PID 12092 served main. None were terminated or redirected. Old sessions must not receive new implementation assignments; fresh isolated worktrees are used by the runner.

Codex A branch reflog contains branch creation at b90cf29 and fast-forward to 3accbd5. Its available home session/history records contain a command request concerning B's merge, ending in usage_limit_exceeded with no agent implementation response. No tracked, staged, untracked, ignored, or patch files were found in its checkout. This does not prove that no older session elsewhere ever contained work.

Git fsck found dropped stash 955974ba8b01f6a1f84bfecfad916fdc680422e8, its index parent 58f3896 and untracked parent 408d840. Preserved and pushed as safety/takeover-dropped-stash-20260913; backup/main-before-task011-cleanup also pushed. The stash contains earlier App/workflow/interpreter/store/styles tests and untracked canvasHistory/dependencies/morningDigest/docs. Tracked application files match the archive; the untracked six files match the archive exactly. README differs by later architecture documentation. The stash is durable via its branch and parents.

Disposition: retain archive and recovered stash, salvage by existing TASK-002–010 dependencies rather than wholesale integration. No separate unfinished entity-split implementation was found. Existing archive implements the old ThoughtObject model, so it cannot substitute for TASK-002. Historical archive validation is recorded in ARCHIVE_SALVAGE_AUDIT; this takeover validated current main, not every archived snapshot.

B's TASK-011 implementation/status are patch-equivalent to main; its obsolete architecture and merge ancestry must not be merged. Claude's doc content matches main; task-board differences are resolved integration edits. All existing branch tips remain remotely preserved. Fresh runner attempts use fetched origin/main rather than rewriting legacy agent branches.

## Tooling

Codex /opt/homebrew/bin/codex 0.154.0: A and B logged in using distinct account IDs in .codex-a and .codex-b. Both passed a read-only headless READY probe. Claude /opt/homebrew/bin/claude is logged in and passed a print-mode READY probe. No auth secrets copied into repository. gh was absent; installed Homebrew gh 2.100.0. Existing Git credential works for repository API; gh login requested unavailable read:org, so github.py obtains the existing credential only for each gh child. No broader authorization requested.

No Threadline LaunchAgent existed at inventory; only Google launch agents were present. Runner installation and smoke results are recorded separately after validation.
