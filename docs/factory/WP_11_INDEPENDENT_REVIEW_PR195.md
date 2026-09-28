# WP-11 Independent Review — PR #195

- **PR:** tanner-art/working#195 — https://github.com/tanner-art/working/pull/195
- **Implementation commit under review:** `715607b3125c25256aaa5ea09683e69be69c2b09`
- **Base commit:** `942dee8ea90fe41737e6fafcf5ab538253343b27` ("Support evidence-bound canary review retries (#166)")
- **WP-11 planning commit (requirements source):** `02a1496`
- **Implementer:** codex-b
- **Reviewer:** Claude (this document)
- **Reviewer separation:** Claude did not author the WP-11 implementation commit or its planning commit, has no assigned WP-11 implementation task, and edited only this review file in a review-only worktree (task TASK-197 / issue #197, branch `runner/task-197-197-1790356869025632000`). No product, Factory, configuration, credential, hook, or settings file was modified as part of this review.

## Review method and a blocking environment limitation

This review worktree is checked out at base `942dee8`, which predates the WP-11 change: `src/appRoutes.ts` here is still the original 9-line implementation, and `src/App.tsx` still imports `appSurfaceForPath` from `./appRoutes` directly. The implementation commit `715607b3125c25256aaa5ea09683e69be69c2b09` is not present in this worktree's history.

The tools available in this session are limited to file read/write/edit/glob/grep on the local filesystem. There is no shell/git-command tool and no network-fetch tool available, so this review could **not**:

- check out, `git show`, or `git diff` the actual implementation commit,
- fetch the GitHub PR #195 page or its diff,
- independently run the test suite, typecheck, or build against that commit,
- independently confirm the runner's reported 56 test files / 704 tests, build, or API typecheck results.

Everything below the actual-diff content (file contents, exact code, exact test assertions) is therefore assessed **only against the prose diff description supplied in this review's task instructions**, not against the real patch. Re-validating an implementer-supplied description of a diff is not equivalent to inspecting the diff itself, and is called out here as **Finding 1 (Blocking)** rather than silently treated as sufficient.

## Requirements checked (from planning commit 02a1496, as restated in this task's instructions)

1. Preserve navigation, mounting, focus, state, Canvas enter/exit, object open/close, and reload behavior through one declarative composition boundary.
2. Allow later surface modules to be added without editing `App.tsx` or a shared list.
3. WP-11 is the sole `App.tsx` writer.
4. Add `src/appSurfaceRegistry.ts` and a `src/surfaces` discovery contract, with parity tests.
5. Only limited edits to `src/appRoutes.ts`.
6. Duplicate IDs, malformed exports, and unauthorized shell overrides must fail closed.
7. No change to persistence formats or write ordering.

## Findings

### Finding 1 — Blocking: independent review could not inspect the actual commit or PR diff
**Severity:** Blocking
No tool available in this session could retrieve the real content of commit `715607b3125c25256aaa5ea09683e69be69c2b09` or PR #195 (no git-command tool, no network fetch tool, and this worktree's base predates the change). All analysis below rests on a prose description of the diff provided in the task instructions rather than on the diff itself. A description authored as part of the same request asking for approval is not independent evidence of the diff's content, of test coverage, or of the runner's reported pass results. This alone withholds approval regardless of the other findings.

### Finding 2 — Likely Blocking (pending code inspection): fail-closed behavior for duplicate IDs, malformed exports, and unauthorized shell overrides is not evidenced
**Severity:** Blocking (provisional — must be resolved by direct code inspection before merge)
The task's own diff description states the new test file `src/appSurfaceRegistry.test.tsx` "asserts explicit route mappings, safe unknown-path fallback, and no persistence for preview routes." Nothing in the description covers a duplicate-ID case, a malformed-export case, or an unauthorized-shell-override case failing closed, and nothing in the described `appSurfaceRegistry.ts` contents (a `find`-based lookup with a "safe default fallback") describes a check that rejects duplicate `id` values in `appSurfaceRegistry`, validates the shape of an `AppSurfaceDefinition`, or blocks a definition from overriding the app shell without authorization. A `find`-based safe fallback handles "path not found" gracefully, but that is a different guarantee from "malformed/duplicate/unauthorized registration fails closed" — the latter needs an explicit validation or throw path, which is exactly the kind of requirement this task asked to independently confirm. This is a named, specific WP-11 requirement and the described evidence does not show it satisfied.

### Finding 3 — Major (pending code inspection): discovery mechanism's genuine extensibility is unclear
**Severity:** Major
Requirement 2 requires that later surface modules can be added "without App.tsx or shared-list edits." The description states `src/appSurfaceRegistry.ts` declares a single `appSurfaceRegistry` value containing the dashboard/settings/landing-preview/tutorial-preview definitions directly, and `src/surfaces/index.ts` merely "re-exports that contract." A single hardcoded array that a new surface must be added to is itself a shared list; re-exporting it from `src/surfaces/index.ts` does not by itself make it a discovery mechanism (e.g., filesystem/module-based auto-registration) that a later surface module could join without editing that array. Based on the description, this looks more like a relocation of the existing two-branch `if` logic into a typed array literal than genuine discovery. This cannot be confirmed as compliant or non-compliant without reading the actual file.

### Finding 4 — Moderate (pending code inspection): behavioral parity guarantees are asserted, not clearly tested by the new suite
**Severity:** Moderate
Requirement 1 lists navigation, mounting, focus, state, Canvas enter/exit, object open/close, and reload as the guarantees the composition boundary must preserve. The described new test file is a narrow unit test of `appSurfaceDefinitionForPath`/`appSurfaceForPath` string-mapping behavior (explicit routes, unknown-path fallback, no-persistence flag for preview routes). None of the described assertions render `App.tsx`, exercise focus management, Canvas enter/exit, object open/close, or reload. Continuing to pass the pre-existing 704 tests shows no regression in whatever those tests already covered, but it does not itself demonstrate that the new tests add coverage for the specific composition-boundary guarantees WP-11 was chartered to protect at the `App.tsx` level, as opposed to only at the pure-function `appSurfaceRegistry` level.

### Finding 5 — Informational: persistence-format risk appears low from the description alone, but unconfirmed
**Severity:** Informational
The description introduces a `SurfacePersistence` type and a registry field apparently indicating whether a surface persists, tested by "no persistence for preview routes." The described `App.tsx` change only touches the early-return branches that already short-circuit before `ThreadlineApp` (and its `persist`/`saveState` calls) mount for `tutorial-preview`/`landing-preview`/`settings`-adjacent surface checks. On the description alone this looks like typed metadata rather than a rewiring of the actual save/write path, which would be consistent with requirement 7 (no persistence-format or write-ordering change). This is marked informational rather than a finding because it could not be checked against the real file contents.

### Finding 6 — Informational: scope of `src/appRoutes.ts` and `App.tsx` edits appears consistent with "limited edits" and "sole writer," but unverifiable
**Severity:** Informational
Per the description, `src/appRoutes.ts` (originally 9 lines) becomes a compatibility re-export module, and `App.tsx`'s only described change is swapping an import/call site and an `AppSurface`-string comparison for an `id`-based comparison. Total diff size (82 additions / 14 deletions across five files) is consistent with a small, bounded change. Whether WP-11 is in fact the sole writer of `App.tsx` in this PR (versus unrelated changes bundled in) cannot be confirmed without the real diff.

## Verdict

**CHANGES_REQUESTED**

Approval is not possible while Finding 1 stands: this review had no way to independently inspect the actual commit, PR diff, or test/build/typecheck results, so it cannot certify the runner's reported evidence or the substantive code. In addition, based on the diff description available, Finding 2 (fail-closed handling for duplicate IDs, malformed exports, and unauthorized shell overrides) and Finding 3 (genuine discovery-contract extensibility) are specific, named WP-11 requirements that the available description does not show as satisfied. Before this can be re-reviewed for approval, either this review needs direct read access to commit `715607b3125c25256aaa5ea09683e69be69c2b09` (e.g., the commit made available in a worktree/branch this review can read), or a reviewer with that access must confirm Findings 2–4 against the real code and tests.

## Newly discovered work (reported separately, not implemented here)

- Consider adding an explicit fail-closed unit test suite for `appSurfaceRegistry` covering: duplicate `id` values across definitions, a definition missing required fields, and an attempt to register a surface that overrides the app shell without authorization. This is a testing/hardening addition to WP-11's own acceptance criteria, not a new product feature, and does not block reporting it here — implementing it is out of this review's scope.
- If discovery is intended to be genuinely extensible (per requirement 2), consider documenting or implementing an actual registration mechanism (e.g., a `src/surfaces/*` module convention that is enumerated rather than a single hand-maintained array) so a later surface module truly needs no edit to a shared list.

## Files changed by this review

- `docs/factory/WP_11_INDEPENDENT_REVIEW_PR195.md` (new)

No product code, Factory code, configuration, credentials, hooks, or settings were modified. No commit was made; commit and PR creation remain the runner's responsibility.
