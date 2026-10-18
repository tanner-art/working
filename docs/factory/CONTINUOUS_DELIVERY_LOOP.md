# Continuous delivery loop

Owner assignment, 2026-10-16: accept a feature and the experience the owner wants,
then prepare, implement, independently review, repair, and integrate modular
code without requiring the owner to operate the queue between stages.

The intended owner interaction is: **“Here is the feature, and here is what the
user should experience.”** Queue registration, contracts, worker selection,
review publication and dependency unlocking are Factory responsibilities.
This change implements that delivery loop; it is not yet proof that a live
overnight run or production deployment succeeds.

## Acceptance

One coordinator uses the existing Registry, scheduler, workers and review
protocol. Owner requests and planning generations are preserved. Every
unfinished feature has a durable next action or an explicit reason for waiting.
The coordinator may prepare only owner-authorized features and bounded repairs
of those features. It cannot invent new product scope.

Preparation reconciles existing code, preserves the requested user experience,
defines one observable end-to-end behavior, and records module boundaries,
public interfaces, persistence ownership, exact paths, tests and dependencies.
Only dependencies with validated integration receipts unlock successors.
Planning is read-only coordinator activity; implementation retains worker leases.

A rejected review schedules a bounded correction and another independent review
with fresh identities. Prior contracts, commits, attempts and verdicts remain
unchanged. Approval alone is not delivery. A delivery receipt binds the approved
commit and PR to one validated integration commit on the configured branch.

The run authorization pins feature identities, request hashes, dependency graph,
integration target, generation budget, parent limit and deadline. Newly prepared
pairs may join only that authorized feature scope through an atomic Registry
operation. Existing canary runs do not gain this capability. Stop, lease,
capacity reserve, independent review and path ownership checks still apply.

External effects have stable operation identities and durable intent. After a
lost response the coordinator reconciles the prior effect before attempting
another. Uncertain actions block their feature with a visible reason. Empty or
dependency-waiting queues remain observable waiting states.

## Evidence and remaining proof

Automated tests use real SQLite Registry transactions and disposable Git
repositories/remotes. Planner/reviewer responses and GitHub observations are
simulated at external boundaries. Coverage includes:

- Intake → planning → exact issue contracts → registration; approved
  implementation → validated branch integration → successor preparation.
- Rejection → preserved rejected patch and findings → fresh correction/review
  identities; approval never substitutes for an integration receipt.
- Replay after publication, concurrent coordinator exclusion, account-pool and
  heartbeat rejection, moved bases, deadline/kill gates, and immutable history.
- Mixed-front restart, non-READY claim refusal, per-package reviewer separation,
  malformed CI observations, and sanitized revision-consistent dashboard reads.

Local verification on 2026-10-16: the full Registry suite passed 512 tests,
the runner suite passed 358, and `pnpm check` passed 773 app tests plus production
build and API typecheck. The subsequently added full-cycle regression passed
separately: it carries one rejected feature through correction and integration,
then its dependent successor through integration, and drains to PAUSED. These
are test-fixture results, not an installed/live run. No lint script is configured.

Not yet proved by this change: a real-provider unattended canary, live Claude
review of newly generated product work, installed-service operation over an
overnight period, hosted dashboard verification, or production/main delivery.
Passing unit/integration fixtures must not be reported as those outcomes.

Before an unattended release, run a bounded canary on an isolated integration
branch with at most two implementation fronts, paired independent reviews,
real capacity refresh, primary stopper and watchdog, and the operational
dashboard. Exercise a review rejection/correction, successor unlocking and
automatic stopping; reconcile back to PAUSED with no dangling ownership.
Report exact commits/PRs, verdicts, receipts, stop events and measured
parent/child runtime separately from waiting time. Do not infer agent hours
from package estimates.

### Current limits

Verification update, 2026-10-18: canary `delivery-canary-20261018-02`
produced PR #462 at `9fa39ba40bca32f9d7584785ef6bcb805f79a288` and
independent Claude approval. Implementation and review attempt runtimes were
73.60224 and 67.327402 seconds respectively; waiting is not agent execution.
Repeated dashboard revision drift triggered a safety stop during integration.
At Registry revision 26594 the Factory is PAUSED, kill-engaged and drained;
integration remains UNCERTAIN without a published receipt, and the successor
has not started. This does not prove the full live cycle.

The proposed shared-capacity publication and query-only dashboard snapshot
repairs pass 533 Registry tests, 361 runner tests, and 773 app tests plus build
and API typecheck. Their regressions exercise the real Registry/runner usage
gate and concurrent SQLite commits, with only provider responses simulated.
These repairs are not yet installed or certified by a new live canary.

The subsequent stopped-integration continuation repair passes 541 Registry
tests and the same 361 runner / 773 app checks. Eight new real-Git/Registry
regressions cover reuse, publication replay, stale-action rejection, invalid
candidates, crash-left RUNNING candidates, target/approval mismatch and target
movement. A query-only check also validates the real canary candidate's binding;
it does not authorize, activate or mutate the live Registry.

- Governing repository instructions prohibit agents from merging into `main`.
  The installed delivery loader therefore rejects `main` and `master` with
  `MAIN_INTEGRATION_NOT_AUTHORIZED`. Use an explicitly approved non-main
  integration branch. This is a policy blocker to production continuous
  delivery, not a configuration flag to bypass; changing it requires separate
  policy authorization and review.
- An intermittent run can adopt an unfinished READY pair or resume its review
  while the VERIFY_REVIEW parent remains context. Old provenance is not
  rewritten. Corrections after CHANGES_REQUESTED are planned by the LIVE loop
  or explicitly prepared under a fresh bounded PAUSED authorization.
- Approved but unintegrated work can resume under a fresh authorization with
  `package_ids: []` only when the Registry certifies exact native approvals,
  completed independent attempts, readable review packets, unchanged owner
  contracts, and no unresolved ownership. Unresolved planning or provider work
  still blocks authorization. One unfinished integration action per feature
  may instead be adopted from a stopped run: the Registry certifies its exact
  native approval, persisted validated candidate, unchanged request and target,
  and coordinator identity. It records a new immutable continuation binding;
  the original action, candidate and review are not rewritten during adoption.
  Activation rejects an action changed since authorization. This scope denies every
  worker claim. The operator also verifies the configured coordinator account,
  heartbeat and shared capacity reserve. Integration remains forbidden while
  PAUSED; LIVE records an immutable continuation certificate. The guards accept
  subsequent scope growth only through Registry-certified successor pairs.
  Empty legacy/uncertified runs fail closed. Already-published effects may
  still be reconciled without another push. The installed service remains inert
  while PAUSED: continuation requires a new authorization and reviewed LIVE
  transition. Recovery first checks the remote for the exact candidate. If
  present it records ALREADY_PUBLISHED; otherwise the existing pre-publication
  scope/deadline/CI checks and exact remote CAS apply. A moved target requires
  revalidation and preserves the prior candidate in the action history. No
  implementation or review attempt is repeated merely to recover integration.
  Resumed completion records total elapsed time separately and leaves execution
  runtime unavailable rather than counting the paused interval as agent work.
- Failed/uncertain provider execution is not automatically an approval or
  permission for unlimited retries. It remains an explicit reconciliation
  blocker; other authorized independent features may continue.
- Explicit PAUSED preparation admits planning (including bounded correction
  planning), issue-contract projection, and recovery of those two action kinds
  only. It cannot dispatch workers, review, or publish an integration.
  Its coordinator heartbeat uses a separate atomic preparation operation bound
  to the fresh active authorization, coordinator identity and deadline. It
  requires PAUSED, kill-engaged, idle Orchestra and no active ownership; stopped
  or superseded authorizations cannot use it. Ordinary worker heartbeats remain
  LIVE-only. The installed-loader regression exercises real Registry telemetry
  and heartbeat persistence before invoking the simulated read-only planner.

## Operator setup and usage

This section is the secondary operational interface, not extra work the owner
should perform for each feature. Use the reviewed immutable release and the
existing [operator procedure](OPERATOR_CLI.md). Do not invoke these examples
against the live Registry merely to test installation.

### 1. Verify the existing installation and account bindings

Keep Factory PAUSED with the kill switch engaged and ownership drained. Verify
the release manifest includes the delivery runtime, the private configuration
is owner-controlled/non-symlink/0600, and the Registry, repository, GitHub wrapper
and worker configuration pass existing operator checks.

Add this exact optional object to the reviewed runner configuration; identifiers
must match the actual installed Registry, not assumed account labels:

```json
"delivery": {
  "run_id": "delivery-canary-01",
  "planner_agent": "codex-b",
  "coordinator_worker_id": "orchestra",
  "validation_commands": [["pnpm", "check"]]
}
```

`validation_commands` are trusted operator argv, never model-supplied shell.
The chosen OpenAI planner lane and its capacity collector must use the same
executable, account home and complete authentication environment. The collector
must explicitly include the Orchestra identity as a shared-account alias;
worker and fresh usage records must agree on the same capacity-pool fingerprint.
Orchestra remains a coordinator, not an implementation lease holder. Stale
heartbeat, unknown account mapping or a breached 20% reserve blocks planning.
Independent review continues through the configured separate reviewer lane.

### 2. Record and authorize owner requests

Run commands from the reviewed release root. Replace the example absolute
paths, feature/run identifiers, revision and future deadline with verified
values. Read `status` before each new mutation; reuse a previous command only
for its exact idempotent replay.

```sh
python3 -m scripts.factory_registry.delivery_cli status \
  --database /absolute/private/registry.sqlite3

python3 -m scripts.factory_registry.delivery_cli submit \
  --database /absolute/private/registry.sqlite3 --expected-revision 123 \
  --id FEATURE-EXAMPLE --title "Example feature" \
  --experience "Describe the action and the result the user should see." \
  --acceptance "The result is observable and survives the required workflow."
```

Optional repeated flags are `--constraint`, `--acceptance` and `--depends-on`.
Requests are immutable; a changed request is not silently written over its
original identity. Authorize only the reviewed feature set while PAUSED:

```sh
python3 -m scripts.factory_registry.delivery_cli authorize \
  --database /absolute/private/registry.sqlite3 --expected-revision 124 \
  --run-id delivery-canary-01 --feature-id FEATURE-EXAMPLE \
  --deadline '<future ISO-8601 deadline with timezone>' \
  --base-ref codex/delivery-canary --parent-limit 2 --max-generations 3 \
  --coordinator-worker-id orchestra
```

Dependencies must belong to this authorization or already have an integration
receipt. A new feature added later does not gain permission to execute in the
current run merely because it exists in the queue.

### 3. Bootstrap contracts, then activate through the operator

The explicit `prepare` command prepares authorized work during a fresh PAUSED
bootstrap. It can invoke the read-only planner or publish issue contracts; it
is **not** a dry-run command. Each pass advances each feature by one available
action, so planning and registration normally require separate passes:

```sh
python3 -m scripts.factory_registry.delivery_cli prepare \
  --database /absolute/private/registry.sqlite3 --expected-revision 125 \
  --config /absolute/private/runner-config.json
```

The coordinator allocates/reconciles marked GitHub issues, verifies their exact
contract bodies and atomically registers the implementation/review pair. Do not
also manually register duplicate product packages. Inspect status and readiness
evidence before activation.

Supervised `tick` requires LIVE and cannot bootstrap work while PAUSED. This
separation prevents a service's RunAtLoad event from starting a paid planner
before the activation transaction succeeds.

Use `operator_cli prepare-dry-run --mode lanes` with the normal release,
preservation, migration and expected-revision arguments. Its optional delivery
LaunchAgent is `life.threadline.factory.delivery`: dry mode runs only
`delivery_cli status`; LIVE mode schedules `delivery_cli tick` every 60 seconds from
the immutable release. The interpreter, module, arguments, config/database and
working directory are checked exactly. Loading dry services does not dispatch.

Construct the reviewed `--bounded-run` JSON from the authorized envelope and
the actual registered package IDs: `run_id`, `package_ids`, `deadline`,
`base_ref`, `parent_limit`. Initially include READY implementations and their
certified ON_DECK reviews; on review-only resume include the review, not its
completed implementation. Install/verify both existing bounded-run guard roles
against that same scope. Then use `operator_cli enable-live --mode lanes
--bounded-run …` with the normal release/preservation/config arguments,
`--expect-revision` and required `--canary-feature`. Only that reviewed operation
transitions PAUSED to LIVE. `submit`, `authorize`, `prepare`, `status` and `tick`
do not.

For approved-only continuation, use an empty `package_ids` array in that exact
envelope. Do not include old VERIFY_REVIEW/DONE packages or invent READY work to
start the run. The activation transaction repeats the read-only continuation
preflight and persists its exact approval bindings. Guard verification of an
empty scope requires that committed certificate; equality alone is insufficient.
If activation fails, no empty-scope service has permission to run or dispatch.

### 4. Observe, stop and resume

The local dashboard's delivery summary shows feature, next action, blocker,
implementation/review IDs and integration commit. Full CLI `status --run-id …`
also includes private planning/action evidence: keep it in owner-only storage,
not a public dashboard upload. Waiting dependencies or one blocked feature do
not justify pausing unrelated eligible work. LIVE passes continue refreshing
real shared-account telemetry and coordinator liveness even while waiting for
implementation or review.

The coordinator publishes its measured capacity observations through the same
atomic, locked usage-file publisher as worker lanes. Otherwise a fresh Registry
Claude probe can suppress the runner's next probe while its compatibility gate
still sees an old usage file. Publication preserves original timestamps, retains
failed collectors' prior (aging) facts, and cannot replace newer evidence with an
older sample. Registry-only Orchestra aliases stay out of runner account data.

Each local dashboard response reads projection, control, delivery and ownership
from one query-only WAL snapshot. Concurrent telemetry/stop/claim commits do not
invalidate a coherent observation or block writers; the next refresh sees the
new revision. Missing/corrupt sources still produce a sanitized error, never an
empty valid queue. A snapshot is observation only, never dispatch permission.

At owner stop/deadline, use the existing operator `stop`, `reconcile` and
`return-paused` flow; do not erase leases or rewrite SQLite. A stopped run cannot
be restarted under its old authorization. Authorize a new bounded run after
draining and reconciling uncertain actions, subject to the resume limits above.

## Scope and safety boundary

- Only a Registry-validated pair for a hashed, authorized feature may extend
  the package allowlist. Run identity, deadline, target, parent limit and repair
  budget cannot be widened by the planner or coordinator. Legacy bounded runs
  retain their non-extensible scope.
- Review placeholders are not claimable: acquiring any lease still requires
  READY plus all existing worker, capacity, dependency, path and ownership
  checks. Adoption records do not promote historical work.
- Review inputs/verdicts bind the implementation SHA, base, contract, PR,
  attempt and separate reviewer. Unknown/malformed results fail closed.
- The exact approved artifact is validated against the integration target;
  its published receipt, not approval or a DONE label alone, unlocks successors.
- External intent is recorded before execution. A database-keyed coordinator
  lock prevents overlapping ticks; uncertain publication is reconciled before
  replay. Guard scope growth is accepted only when Registry-certified.

## Implementation ownership

### Preserved installed baseline

The original checkpoint incorporated installed Factory release `44da816` through
merge commit `bb2fbf2`; the durable recovery branch restores those file changes
in `3315657` (see `DELIVERY_RECOVERY_2026-10-18.md`). They were absent from the
observed `origin/main` (`b97ec39`). They are not new delivery-loop work. In
particular, that baseline includes the PAUSED-only historical no-commit
classification commands, external-integration review provenance and projection,
review-only follow-up handling, Claude health and bounded-guard repairs. The
historical classification commands can mark their narrowly matched legacy
records DONE/BLOCKED without claiming a successful review; they are not product
implementation or bulk READY promotion. This task has not invoked those
commands or changed any live historical records. Review the entire branch diff
when integrating the preserved baseline, not just the delivery modules below.

### New delivery-loop work

- `delivery_plan.py`: owner brief, planner prompt, modular contract validation.
- `sqlite_delivery.py`: durable delivery records and Registry transactions.
- `delivery_coordinator.py` / `delivery_cli.py`: next actions and operator entry.
- `delivery_integration.py`: exact-commit candidate validation and publication.
- Existing runner/Registry files: narrow compatibility and review-publication
  changes only. Product source is not part of this repair.

Readiness is established by the demonstrated live cycle, not estimated agent
hours or a green fixture suite alone.
