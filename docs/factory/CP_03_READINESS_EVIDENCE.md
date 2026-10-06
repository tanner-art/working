# CP-03 readiness implementation evidence (TASK-401)

Base: `9e460a53273e8502f351ec38ad9aaf21984255ab` (merged main after PR #394).
Issue #391 originally named `ed3e2da791a4945d104d055326e54308004b5681`;
the implementation branch uses the later integrated base. This is code preparation
only. CP-02's formal proof and the installed issue-author allowlist still block
Factory dispatch. The worker handoff is separately scoped in issue #398, so
this note does not mark CP-03 complete.

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
- For new version-2 READY registrations, the operator resolves the exact
  `main` target ref to the declared base commit; confirms the queue contract
  and nonempty acceptance criteria; checks each planning path is a readable,
  nonempty regular Git blob; checks existing/new integration and test paths;
  and pins SHA-256 values for the queue contract, acceptance criteria, and
  planning files in a Registry readiness proof. Claim-time readiness checks
  rederive and compare the proof, so moved refs or altered inputs revoke
  eligibility. Sparse legacy contracts keep their existing path.
- READY package registration validates the version-2 proof and atomically
  promotes an ON_DECK feature to READY. Canary and bounded-pilot pair
  registration stores READY features in the same transaction. The scheduler
  and direct Registry claim reject a version-2 READY child if its feature
  is no longer in a runnable state.
- The Control Center projection names missing review packet or feature gates
  in `blockReason`. The installed runner already projects GitHub labels after
  Registry claim; no label authority was added here.

## Verification

- Factory discovery with local loopback enabled: 273 passed.
- Runner discovery with local loopback enabled: 321 passed.
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
- Automatic approval review rejected a proposed claim-time proof check because
  it appeared to apply to legacy packets. The accepted implementation has an
  explicit schema-version-2 condition. Legacy tests remain green.

## Remaining CP-03 work

Issue #398 must include the verified Registry acceptance criteria and planning
hashes in the implementation worker's actual prompt. It requires its own exact
commit and independent review. The current TASK-401/TASK-402 queue contracts
name the older `ed3e2da` base; the new registration validator will reject them
against advanced `main` until the owner refreshes those contracts and their
Registry registration. No live Registry or installed config was changed here.
The registered CP-03 issues remain ineligible while CP-02 proof and the
installed author allowlist are unresolved. Exact-head CI and Claude review
remain pending.
