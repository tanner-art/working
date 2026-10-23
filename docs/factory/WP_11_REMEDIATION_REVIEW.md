# WP-11 Remediation Review — PR #195

Reviewer: Claude (this session, provider child lane `claude`, slot 1, TASK-199)
Implementer of remediation under review: Orchestra
Original WP-11 implementer: codex-b
Reviewer separation: satisfied in principle — Claude did not author PR #195, TASK-197, or the
original commit `715607b3125c25256aaa5ea09683e69be69c2b09`. No implementation files were
modified by this review.

- PR under review: **#195**
- Remediation commit under review (claimed exact head): **f6a4696133690a68ee9a30883274619cc74fbb1f**
- Original WP-11 implementation commit (codex-b, predates remediation): **715607b3125c25256aaa5ea09683e69be69c2b09**
- Predecessor review whose findings this remediation claims to resolve: TASK-197, Findings 2–4
  (Claude)
- Authoritative requirements source: WP-11 planning commit `02a1496`

## Verdict

**CHANGES_REQUESTED**

Not because a defect was found in the remediated code, but because this review could not
independently verify the remediated code at all. Per the assigned instructions, an APPROVED
verdict is permitted only if no blocking finding remains — "I could not check" is not equivalent
to "no blocking finding remains," so this cannot be recorded as APPROVED.

## Finding 1 — BLOCKING: Required source paths were not readable in this session

**Severity: Blocking**

The assignment specified direct filesystem read access to:

- `/private/tmp/threadline-wp11-remediation/src/appSurfaceRegistry.ts`
- `/private/tmp/threadline-wp11-remediation/src/appRoutes.ts`
- `/private/tmp/threadline-wp11-remediation/src/surfaces/index.ts`
- `/private/tmp/threadline-wp11-remediation/src/surfaces/*.surface.ts` (four modules)
- `/private/tmp/threadline-wp11-remediation/src/appSurfaceRegistry.test.tsx`
- `/private/tmp/threadline-wp11-remediation/src/App.tsx`
- `/Users/domitian/Library/Application Support/ThreadlineFactory/worktrees/codex-b/issue-169-1790353878433880000/*` (original commit `715607b3125c25256aaa5ea09683e69be69c2b09`, same file set, for comparison)

Every attempted `Read` against these paths was auto-denied by the sandbox with the explicit
message that this session "has no approval surface" and that identical requests "will be denied
the same way for the rest of this session." This tool session also has no Bash/git tool, so
`git show <sha>:<path>` from within the current worktree's repository was not available as a
fallback. The current worktree's own `src/` tree does not contain `appSurfaceRegistry.ts` or a
`surfaces/` directory (checked via `Glob`), so there was no local copy to inspect either.

Consequently:

- No line of the actual remediated implementation was read by this reviewer.
- No line of the actual original (codex-b) implementation was read by this reviewer.
- TASK-197 Findings 2–4 could not be independently re-checked against real code.
- The remediation's self-reported results (56 test files / 708 tests, focused 8/8
  route-registry tests, build, API typecheck, git diff check) could not be independently
  reproduced or verified, since this task was also instructed to run only focused checks
  covering its own changes, and there is no code checked out in this worktree to run checks
  against in the first place.
- The instructions explicitly state: "Do not rely on a prose diff summary: use Read/Glob/Grep
  on those exact absolute paths to inspect the real files." No prose-only substitute finding is
  recorded here for that reason — this review makes no claim about the remediation's
  correctness in either direction.

**How to apply:** This finding blocks a substantive verdict on its own; it is not a judgment on
the remediation's quality. Resolving it requires either (a) re-running this review in a session
where the two absolute paths above are inside the allowed working directory / pre-approved for
read access, or (b) providing the remediated and original source as diffable content inside this
review worktree (e.g., a patch file or an already-approved read path) so a future review pass can
inspect the real files as instructed.

## Files actually inspected by this reviewer

- `AGENTS.md` (this worktree)
- `TASKS.md` (this worktree)
- `docs/NORTH_STAR.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/DECISIONS.md`
- `docs/factory/*` directory listing (no `TASK-197`, `TASK-199`, or `WP_11` planning/finding
  documents exist in this repository's `docs/factory/`, so TASK-197's exact Finding 2–4 text was
  not locatable in-repo either — it was only available as the prose summary in the task
  assignment, which this review does not treat as a substitute for reading code)

No files matching the assigned remediation or original-implementation paths were inspected,
because none were accessible.

## Findings 2–4 (TASK-197 carry-forward) — status

**Not independently verified.** This review takes no position on whether Findings 2–4 from
TASK-197 are actually resolved in commit `f6a4696133690a68ee9a30883274619cc74fbb1f`, because the
source files needed to check that were not readable in this session (see Finding 1). Treat prior
TASK-197 status as still open pending a review that can read the real files.

## Known limitations

- No git mutations, commits, pushes, branch changes, or PR actions were performed, per
  instructions.
- No implementation, Factory, configuration, credential, or hook files were modified.
- Only `docs/factory/WP_11_REMEDIATION_REVIEW.md` was created/edited, per the scope lock.
- No `pnpm check` or other broad validation was run; this task was instructed to run only
  focused checks covering its own change, and its only change is this documentation file.
- This review should not be cited as either an approval or a rejection of the remediated code's
  technical content — only as a record that verification could not be performed in this session
  and must be retried with working file access.

## Newly discovered work (reported separately, not implemented here)

1. **Issue:** This session's sandbox has no approval surface, so any task requiring read access
   to paths outside the assigned worktree (as this one did) cannot complete as specified.
   **Proposed task:** Either grant the reviewing session pre-approved read access to the specific
   external paths a review task names, or change the review-task pattern to stage the files to
   inspect inside the reviewer's own worktree (e.g., a read-only bind mount, copy, or patch file)
   before dispatch.
   **Blocking?** Yes, for this specific task's substantive verdict — the review cannot be
   completed as CHANGES_REQUESTED-with-specifics or APPROVED without it. It does not block other,
   differently-scoped tasks.
   **Action taken:** Reported here; not implemented, since resolving it is outside this task's
   assigned scope (`docs/factory/WP_11_REMEDIATION_REVIEW.md` only).
