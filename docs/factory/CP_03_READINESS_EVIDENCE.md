# CP-03 readiness implementation evidence (TASK-404)

Implementation issue: #400. Independent review issue: #401 (TASK-405).
Exact source base: `a227aa9b8f548f3beb40defe1e2110ce1ce6d55d`, after PR #399.
The fresh pair supersedes the stale-base #391/#392 contracts without changing
their Registry history. The earlier prototype commits `650817c` and `d0f3a78`
informed this local implementation; they are not a successful Factory attempt.
This branch is not installed, merged, or dispatched.

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

- The exact issue #400 contract passes `registration_proof` against this local
  Git tree with `main` pinned to `a227aa9`; its queue digest is
  `065122d2ccb407d3dfb1c5172702b98ec1e46d30362f2706aa7e4ca3728d8f56`.
- Factory Registry discovery: 289 tests passed with local loopback enabled.
- Runner discovery: 326 tests passed with local loopback enabled.
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
- Client Vitest: 69 files and 758 tests passed. Client TypeScript, Vite
  production build, and API TypeScript check passed using a private copy of
  complete local dependencies; no dependency or lockfile changed.
- `pnpm check` attempted missing npm downloads and could not resolve the
  registry host. Its three underlying checks passed directly from the local
  dependency tree. No lint script is configured.
- Python compilation with a writable cache prefix and `git diff --check`
  passed. The final diff stays within the issue's declared paths.

## Remaining acceptance dependency

Issue #398 owns actual implementation-child prompt handoff in `runner.py` and
`test_runner.py`. Its separately reviewed change must send the verified
Registry acceptance criteria and planning hashes to the worker before CP-03
can be declared complete. CP-01/CP-02 proof, Registry registration, independent
TASK-405 review, and a guarded Factory run also remain separate operational
gates. The operator currently pins the local `main` ref; issue #398 must verify
the worker checkout of `origin/<base_ref>` matches that exact proof tree. This
local code does not bypass or attest those gates.
