# TASK-015 verification

## Proven on 2026-09-13

- Main and GitHub main both 88ed680; clean and pnpm check passing (18 tests, TypeScript, build).
- Codex A and B use distinct account IDs and both returned READY headlessly. Claude also returned READY through its print interface.
- Dry-run rejected invalid queues in tests and printed the valid smoke plan without creating state, labels, or worktrees.
- Issue https://github.com/tanner-art/working/issues/1 assigned TASK-016 to Codex B.
- Runner created fresh branch runner/task-016-1-1789352202213804000 from origin/main 88ed680, in an isolated worktree.
- Codex B created only docs/RUNNER_SMOKE.md. Agent and runner validation passed. Commit 65ce52f5e908f10986b448f8b19cad01c178a553 was pushed.
- Runner opened draft PR https://github.com/tanner-art/working/pull/2 and moved the issue to runner:review. Orchestrator inspected the four-line diff with no findings. PR remains unmerged.
- A second poll returned idle without repeating the task. No scaling or concurrent task dispatch was enabled.
- Independent review found shutdown cleanup, post-validation scope, and dependency-waiting defects; fixes and regression checks are included in the follow-up commit.

## Not yet proven: launchd execution

The user LaunchAgent life.threadline.runner was installed with explicit PATH /opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin. launchctl confirmed the service definition and launch. macOS denied its Python executable access to the Documents-hosted runner with `Operation not permitted`. Therefore the successful cycle above was invoked from the authorized Codex session, not from launchd. It required no visible Terminal window, but unattended login/background operation remains blocked pending OS privacy permission.

Executable requiring access: /Library/Developer/CommandLineTools/usr/bin/python3. Do not relocate protected files to evade the permission boundary. After the user grants access, load the preserved plist, verify logs, and perform another controlled task before calling the background service operational.

State/log directory: /Users/domitian/Documents/Codex/threadline-runner-state. Failed and completed worktrees are retained. The service will be unloaded while access is pending to avoid repeated failed launches; its plist remains installed for explicit bootstrap after permission is granted.

No automatic main merge, user mobile approval, or post-merge dispatch was performed. PRs are reviewable from GitHub/mobile. Canonical main remains unchanged and remote-backed.


## Permission retest — 2026-09-13 22:30 local

After the user granted Python access, launchd PID 36000 successfully polled GitHub and wrote an idle heartbeat. On its next scheduled poll, PID 36055 picked up TASK-017 issue #4, created branch runner/task-017-4-1789353049195549000 from 88ed680, and started dependency installation. macOS tccd then requested Documents-folder permission specifically for /opt/homebrew/lib/node_modules/pnpm/pnpm. Thus Python access is resolved, while the end-to-end background test is waiting on this separate permission. No main merge or legacy worktree change occurred.

The attempt reached its 180-second dependency-install timeout while permission remained pending. Issue #4 is runner:failed; its worktree/log remain preserved. The LaunchAgent remains loaded and healthy for queue polling. Retry requires explicit action after the user grants pnpm permission.
