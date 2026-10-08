# CP-03 readiness implementation evidence (TASK-404)

Implementation issue: #400. Independent review issue: #401 (TASK-405).
Original issue base: `a227aa9b8f548f3beb40defe1e2110ce1ce6d55d`, after PR #399.
Current integration base: `e3a51109f4ee7ba15ccae8955b66654e1cc6e40a`.
The fresh pair supersedes the stale-base #391/#392 contracts without changing
their Registry history. The earlier prototype commits `650817c` and `d0f3a78`
informed this local implementation; they are not a successful Factory attempt.
This combined branch is not installed, merged, or dispatched.

## Implemented in TASK-404 scope

- Version-2 READY registration resolves the exact `main` target ref to the
  declared base commit, checks the queue contract and nonempty Registry
  acceptance criteria, verifies readable regular Git blobs for every planning
  path and declared existing path, and pins queue, acceptance, and planning
  SHA-256 values in a Registry proof. The preclaim checker rederives that proof
  and rejects moved refs or changed inputs. Legacy sparse contracts retain
  their existing path.
- READY package registration validates the version-2 proof and atomically
  promotes an ON_DECK feature to READY. Canary and bounded-pilot registration
  store READY features in the same transaction. Direct status transitions,
  failed-package requeue, active-attempt completion, lease release, and the
  CP-02 external integration bridge now repeat that gate before entering
  READY. Legacy packages also receive atomic feature promotion. Scheduler and
  direct claim reject a version-2 READY child whose feature is not runnable.
- Version-2 REVIEW eligibility derives from one VERIFY_REVIEW target, its
  latest successful attempt, one immutable review-input evidence row bound to
  that attempt, and a valid CP-02 review packet with exact commits and CI
  provenance. Snapshot and Control Center projection show missing prerequisites;
  direct lease acquisition repeats the check in its transaction. Packet loss
  or tampering revokes claim eligibility without deleting historical evidence.
  Worker pairing also rejects the recorded implementer.
- The CP-02 external integration path retains its separate, verified lineage:
  a historical failed attempt, an INTEGRATED_ELSEWHERE reconciliation, exact
  PR/CI and packet binding, and an independent reviewer. A version-2 review
  with this lineage can claim; an unproven one cannot enter READY.
- Scheduler and Control Center show missing or malformed stored proof reasons
  without Git access. Preclaim reports a package-local deferrable rejection
  with the exact failed checks and pair details, leaving other queue work able
  to continue. Lease-time feature, review-input and proof losses are converted
  to the same deferrable pair result, so a changed packet after preclaim does
  not make the runner record a failed Registry package or project a failure
  label from an uncommitted state.
- GitHub label writes remain downstream of committed Registry state; this
  branch adds no label authority.

## Current validation

- Issue #400 was validated against its original `a227aa9` base with queue
  digest `065122d2ccb407d3dfb1c5172702b98ec1e46d30362f2706aa7e4ca3728d8f56`.
  Its base and issue/task identities are stale for a new Factory registration;
  a fresh exact-base pair is required after integration.
- On the current integration base, Factory Registry discovery: 298 tests passed
  with local loopback enabled.
- On the current integration base, runner discovery: 329 tests passed with local
  loopback enabled.
- New negatives cover proofless ON_DECK promotion, proofless external bridge,
  moved/tampered inputs, missing proof projection and preclaim, and requeue
  rollback. Two concurrent READY registrations of one ON_DECK feature both
  commit with the feature READY. A valid snapshot followed by packet tampering
  still fails the lease transaction.
- A runner-control race test tampers with the review packet after preclaim and
  confirms claim defers with the precise gate while the Registry package stays
  READY and unleased. Read-only lineage views exercise five rejection cases
  for the external bridge: unexpected successful attempt, wrong integration
  commit, wrong repository head, wrong evidence URL, and wrong implementer.
- `pnpm check` passed: 69 Vitest files and 758 tests, client TypeScript, Vite
  production build, and API TypeScript. Lockfile-pinned dependencies were
  installed from the local package store; no dependency or lockfile changed.
- `git diff --check e3a5110..HEAD` passed. No lint script is configured.
  The combined diff stays within issues #398 and #400's declared paths.

## Remaining acceptance dependency

Issue #398's implementation-child prompt handoff is included on this combined
branch. It supplies the verified Registry acceptance criteria and planning
hashes and rejects drift before provider launch. Its original reviewed patch is
unchanged by the current-main replay. Fresh exact-head independent review,
integrated CI, exact-base Registry issue contracts and a guarded Factory run
remain separate operational gates. This local code does not bypass or attest
those gates.

## TASK-419 CP-03 cross-module canary (issue #419)

This validation canary is pinned to base/head
`d197a35a10041d95a5b8f34ef1eba1fc1de6c758` with target ref `main`, Registry
revision `24040`, queue-contract SHA-256
`282f6e0d03db9ee41d3f74866adb40313fc88072a40a95d93f50b6457ed52ad2`, and
acceptance-criteria SHA-256
`7bce1c9390b56c5a18f6d473a53fa3ed04f6fa51e03353b958abdf25a7ea91cc`.
Its planning-file SHA-256 contract is:

- `AGENTS.md`: `b1de2b77b56b147a701550ed738c1e19203bec39399dbf8f25fd6255c6f387ac`
- `TASKS.md`: `04ab551e9057b445ceb313ce77556d902801bcc7f7cdf704f7e7f3b87c694038`
- `docs/ARCHITECTURE.md`: `d0f9feafa19aa2368348094e01fe52424282db1d1183f453a398e5b4845d24dd`
- `docs/DECISIONS.md`: `cf72aab01fe62d89d43c254d0114c0c6c7b9c1ed4e100352e8b0ee4a2c69252e`
- `docs/NORTH_STAR.md`: `f187c86595999dc5806f422de317094f7c911c3fc2479a5b4acb4b791839a70c`
- `docs/ROADMAP.md`: `e741b94c4a827df12e8a684122c4275dd12535cdbf75856d7301efe5e46a8bb2`
- `docs/factory/CONTROL_PLANE_HARDENING_RECONCILIATION_2026-09-25.md`: `78450414cba865b5a3dbcca6f811a57fbef518fbb29ce1006daf28834cd4cacd`
- `docs/factory/CP_03_READINESS_EVIDENCE.md`: `148a93ee593ec66929b11c6b27073c35ba4a1b00f747c46a46bfc2bc35c9699f`
- `docs/factory/R1_READINESS_SOLO_VALIDATION_2026-09-27.md`: `2844aa34589865d16c1ff2b1d64e4af794d2ddd0b132670cb6a6d795ecc6a305`

- `python3 -m unittest scripts.factory_registry.test_cp03_canary_integration`
  exercises an isolated Git repository and temporary Registry. It proves the
  registered v2 queue, acceptance, planning hashes, exact base, target ref,
  and Registry revision reach the implementation-child prompt after Registry
  preclaim. It also proves a tampered planning digest, a moved `main` base, a
  mismatched source issue, and a changed queue contract fail before simulated
  provider launch with no active lease or attempt ownership.
- Focused normal Python coverage passed: `python3 scripts/runner/test_task_readiness.py`
  ran 9 tests, and `python3 scripts/runner/test_runner.py` ran 58 tests. The
  canary command above ran 1 test; all three commands exited successfully.

The operational gate remaining after local validation is exact-head CI plus
independent Claude review, followed by the separately authorized guarded
Factory run. This canary validates already integrated CP-03 code; it does not
retroactively make merged PR #407 a Factory attempt. Historical #411 and #415
attempts remain historical evidence and are not rewritten by this result.
