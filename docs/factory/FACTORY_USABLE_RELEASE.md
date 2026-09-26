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

## Focused bounded-pilot repair (owner authorized; still uninstalled)

The repaired path registers one or two independent implementation/review pairs
in the Registry, then activates an explicit run envelope atomically with LIVE:
`run_id`, exact package allowlist, UTC deadline, configured integration base,
and a parent limit of at most two (while retaining the global cap). The operator
uses `register-bounded-pilot --spec pilot.json` followed by `enable-live
--canary-feature <historical-feature-id> --bounded-run run.json`; the latter is
only an operator command, not activation authority for this task. `main()`
uses the Registry scheduler proposal in this mode. The source GitHub issue and
allowed author prove provenance, and its normalized body must hash to the
registered immutable contract; GitHub readiness/agent/dependency labels are
best-effort projections and never choose or veto the Registry assignment.

Review waits for the immutable `ReviewInput`, an exact PR head match, and the
repository's `Validate app` workflow `verify` check passing (branch protection
does not currently supply a required-check list). A `CHANGES_REQUESTED` outcome leaves the target
out of `DONE`, so a successor dependency remains blocked. Claims and renewals
enforce allowlist and deadline. A scheduled stop carrying an old `run_id` is a
no-op after a successor becomes current; the unconditional owner/emergency stop
continues to engage the kill switch.

`codex_capacity_cli.py` performs read-only provider observations for Codex
`account/rateLimits/read`; it sends no model prompt. It accepts only configured
absolute executable/CODEX_HOME inputs and stores short-window/weekly measurements
with a response-collection timestamp only after a fresh provider request. Its narrow Registry write appends capacity
observations while LIVE without changing worker identity, capabilities,
availability, leases, or ownership. Missing timestamped data fails closed; it
does not relabel cached usage as fresh. The configured model remains the
currently supported model: the attempted Agent A GPT-6 Sol selection was
rejected and no fallback is inferred without a capability probe.

The local dashboard now displays authoritative control mode/kill switch,
Registry revision, bounded run ID/deadline, ownership, verdict, blocker and PR.
Refresh is read-only, automatic and manually available; a failed refresh leaves
the previously rendered snapshot visible and marks the failure. Runtime elapsed
time remains occupancy only, never token or cost data.

Implemented acceptance is limited to the supervised one/two-parent pilot path,
exact-contract review gating, scoped stop/renewal, narrow capacity observation,
and Registry-backed dashboard truth. Remaining/uninstalled work includes the
owner-reviewed activation itself, a real configured GitHub/operator exercise,
exact-commit independent review, hosted dashboard smoke, and unattended
eight-hour readiness. Extra parents/fleet dispatch remain deferred until the
two-builder proof; no automatic main merge is added.

Historical first-phase worker validation: `PYTHONPATH=scripts/runner python3
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
identity/allowlist/run generation and dashboard recovery were then addressed in
the integration phase below. Activation, deployment and independent review were
not part of that worker checkpoint. This is not a broad Factory
readiness claim.

Coordinator validation of this checkpoint outside the worker's socket sandbox:
217 Registry tests and 277 runner tests passed; `git diff --check` passed.
The recovered dashboard-only changes passed their 102-test suite. Threadline's
725 product tests, build and API typecheck passed with no product source changes.
These checks do not substitute for final exact-commit independent review.

### Integration proof and installation boundary

The coordinator exercised the real `enable_live` path using disposable Registry
and fake service operations: two independent implementation/review pairs can be
activated while an unrelated higher-priority READY item stays unchanged and is
excluded from scheduler proposals. The live Registry was not activated.

The provider collector was exercised against the actual Agent A account without
writing Registry: identity was present and both configured capacity scopes were
returned. Partial stdout and buffered notifications have bounded-read tests.
Usage publication round-trips through the real usage validator and preserves
other accounts. Optional `capacity_collectors` entries require `executable` and
`codex_home` for each configured worker, plus optional `timeout_seconds` (maximum
30). The runner polls them at entry and at most once per minute during an active
attempt, without a model prompt. Installation must configure these entries and
verify the worker/account mapping; adding code alone does not activate a feed.
Claude's provider-signal evidence remains separate and must be genuinely fresh;
this collector never fabricates Claude health or capacity.

A separate read-only dashboard preview was browser-tested against revision 1927:
Refresh showed STOPPING, engaged kill switch and zero ownership without changing
the revision. Feature groups and nested attempt history rendered. Stopping only
the preview and pressing Refresh produced an explicit STALE SNAPSHOT banner.
The installed `:8787` dashboard was not replaced. Historical retry features are
not automatically merged by guessing names; their registered identities remain.

No old worktrees or branches were deleted. No main merge, deployment, live
Registry mutation, or product dispatch is included in this candidate. Same-task
claim races have bounded retries; package remediation/requeue still uses the
explicit operator rather than silently rewriting immutable contracts. This is
a supervised pilot repair, not certification for an unattended eight-hour run.

Final coordinator validation before independent review: 225 Registry tests,
283 runner tests, 725 Threadline product tests, production build, API typecheck,
and `git diff --check` passed. The existing large-bundle build warning remains;
no product code was changed. Independent review evidence is intentionally kept
outside its own reviewed commit to avoid a self-referential SHA assertion.
