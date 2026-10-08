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

## TASK-413 disposable cross-module canary (blocked 2026-10-08)

This is a validation canary for the installed CP-03 v2 path, not a
reimplementation and not credit for merged PR #407. The earlier #411 attempt
remains historical evidence and is not rewritten by this canary.

The declared Registry proof identity is revision `23307`, exact base
`c43b9ec59b2f2ed88ebfcb002ebc5f7c8f17e79b`, target `main`, and queue-contract
SHA-256 `fad130e9112a5ce49aeefc9c555a2a9263b18ae77772235261bad879c7099472`.
The assigned head is that same base. The disposable test registers a v2 package
against a temporary Git repository and SQLite Registry, preclaims it, and builds
the real implementation-child prompt. Its remaining assertions hold preclaim
before provider launch for a changed planning blob, moved target base, changed
queue contract, and mismatched source issue, while asserting no active lease,
active attempt, or task event is created by any rejection.

Command run:

```
python3 -m unittest scripts.factory_registry.test_cp03_canary_integration -v
```

Result: failed at the required new acceptance-hash assertion, before the
subsequent negative cases could run. The real
`verified_readiness_handoff` prompt contained the Registry revision, exact base,
target ref, queue-contract SHA-256, acceptance-criteria text, and planning
SHA-256, but omitted the registered `acceptance_sha256`. Therefore this canary
cannot truthfully establish the required handoff of all three registered hash
classes. No provider was launched and no live Registry was read or written.

Remaining gate: add the registered acceptance SHA-256 to the runner-owned
implementation-child handoff, then rerun this focused canary along with the
normal Python suite, shared `pnpm check`/build, exact-head CI, and independent
Claude review. That runner change is outside TASK-413's declared editable paths.
