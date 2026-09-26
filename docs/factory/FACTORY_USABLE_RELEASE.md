# Factory usable repair evidence

## 2026-09-26 — offline control-plane repair (uninstalled)

This branch preserves CP-02 (`08126fc`) and is not installed, activated,
deployed, or a replacement for the live runner. It adds strict handling for a
successful Claude JSON result envelope before the existing six-field review
verdict checks; review worktrees are checked out at the recorded implementation
SHA and receive a separate read-only prompt and tool allowlist. Provider stderr
is retained as diagnostics but is not machine-parsed as a verdict.

Attempt runtime is now calculated once from normalized recorded start/end wall
timestamps and atomically applied to both `attempts.runtime_seconds` and
`work_packages.runtime_seconds`. Completion replay cannot add time twice;
zero-duration and invalid chronology remain explicit cases. This occupancy
accounting is not model/provider billing.

Package-local Registry conflicts use an explicit deferrable-code set and the
finite poll continues; unknown control/ownership errors fail closed. Decision /
claim revision races are retried only twice before being deferred, and unresolved
post-lease recovery stops further dispatch. Routine staging uses the verified
changed allowlisted paths with `git add -A -- <changed paths>`, so tracked
deletions stage while absent optional allowlist paths do not fail a package.

An implementation now materializes a per-attempt, read-only packet beneath
runner state (never in the tracked checkout): exact binary base-to-implementation
diff, changed-file list, immutable contract, validation evidence, and a hashed
manifest. Packet identity and content hashes are stored in each ReviewInput.
The Claude-specific review adapter preserves its configured wrapper but replaces
provider flags with JSON output, `Read,Glob,Grep`, explicit `dontAsk`, and no
permission prompts. Unsupported providers and equals-form alternate control
flags are rejected. Review parsing accepts only a successful Claude result
envelope and rejects duplicate JSON keys, error subtypes, ambiguous/extra
verdict fields, and target SHA/base/contract mismatch. Stderr is diagnostic only
and never enters the machine verdict parser.

The Registry now has a LIVE-only, monotonic worker-heartbeat observation that
can operate while a worker is BUSY without reconfiguring identity, capability,
availability, capacity, or lease ownership. It writes no usage/provider
measurement and therefore cannot make stale usage appear fresh. Runner refreshes
truthful liveness during polling before dispatch decisions and while a lease is
active; idle peers remain independently refreshable.

Validation run in this isolated workspace: `PYTHONPATH=scripts/runner python3
-m unittest scripts.factory_registry.test_review_integrity
scripts.runner.test_runner scripts.runner.test_registry_control` (69 passed).
This includes real `runner.main` review-loop fakes covering the exact checkout,
read-only Claude command, stdout envelope/stderr separation, and approved,
changes-requested, wrong-SHA, and malformed outcomes. Full Factory-registry
discovery ran 217 tests; 29 Control Center transport tests could not bind
loopback sockets under this sandbox (`PermissionError`), while the remaining
tests passed. Full runner discovery ran 271 tests with one same sandbox
loopback-binding failure in the dashboard HTTP suite. `pnpm check` was not run:
this repair is Python-only and final integration owns it. Registry-owned queue
identity/allowlist/run generation, dashboard recovery, activation, deployment,
and independent review remain next-phase work. This is not a broad Factory
readiness claim.

Coordinator validation of this checkpoint outside the worker's socket sandbox:
217 Registry tests and 277 runner tests passed; `git diff --check` passed.
The recovered dashboard-only changes passed their 102-test suite. Threadline's
725 product tests, build and API typecheck passed with no product source changes.
These checks do not substitute for final exact-commit independent review.
