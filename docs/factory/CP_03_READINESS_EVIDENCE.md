# CP-03 readiness implementation evidence (first tranche)

Base: `9e460a53273e8502f351ec38ad9aaf21984255ab` (merged main after PR #394).
Issue #391 originally named `ed3e2da791a4945d104d055326e54308004b5681`;
the implementation branch uses the later integrated base. This is code preparation
only. CP-02's formal proof and the installed issue-author allowlist still block
Factory dispatch. This note does not mark CP-03 complete.

## Implemented

- For version-2 REVIEW packages, the Registry now derives eligibility from
  exactly one target in `VERIFY_REVIEW`, the target's latest successful attempt,
  one immutable review-input evidence row bound to that attempt, and a readable
  review packet whose manifest, files, contract hash, exact commits, and CI
  provenance pass the existing CP-02 validator.
- The read-only dispatch snapshot includes precise missing review prerequisites.
  The scheduler rejects these candidates and shows the reason. A version-2
  review pair also rejects the target's recorded implementer.
- Direct Registry lease acquisition repeats the review prerequisite check in
  its claim transaction. Packet loss or tampering revokes claim eligibility
  without deleting evidence or changing package history.

## Verification

- `python3 -m unittest scripts.factory_registry.test_registry scripts.factory_registry.test_shadow_dispatch -q`: 87 passed.
- Factory discovery: 269 tests ran; 29 localhost-bind errors from sandbox socket
  denial. No other failures reported.
- Runner discovery: 314 tests ran; one localhost-bind error from sandbox socket
  denial. No other failures reported.
- Client Vitest: 69 files, 758 tests passed. Client TypeScript, Vite production
  build, and API TypeScript check passed with a private copy of the complete
  dependency tree already installed in the isolated PR #396 worktree.
- Initial `pnpm check` attempted missing dependency downloads from the older
  local dependency tree, but npm DNS was unavailable. The equivalent test,
  build, and API typecheck commands above then passed from the copied tree.
  No dependency or lockfile changes were made. No lint script is configured.
- Python compilation and `git diff --check` passed.
- An initial test fixture proposal that inserted an attempt directly into
  SQLite was rejected by automatic approval review because the instruction
  prohibited direct SQLite edits. The test was rewritten with public Registry
  lease, attempt-start, and attempt-finish methods and passes. No direct
  database edit was applied by this branch.

## Remaining CP-03 work

Implementation READY still needs registration-time validation of all planning
commits, readable contract and acceptance criteria, required base/target refs,
critical content hashes, and complete worker handoff. Package promotion still
needs atomic Model A feature promotion. GitHub label projection must be pinned
after Registry commit, and the dashboard must display exact contract and gate
rejections. Current R1 version-2 pre-claim checks remain in force. These gaps
block a CP-03 completion claim and require a later exact-commit review of the
full package. The registered CP-03 issues are not dispatch eligible while
CP-02 proof and the installed author allowlist remain unresolved.
