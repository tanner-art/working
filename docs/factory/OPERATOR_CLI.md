# Factory Registry operator CLI

`scripts/factory_registry/operator_cli.py` is the reviewed, fail-closed surface
for a controlled local Factory restart. It operates only on an explicitly
named Registry database. All commands emit one compact JSON evidence record.
Failures emit JSON on stderr and return a non-zero exit status.

The emergency `stop` command is deliberately unconditional. Every other
mutation requires the exact current Registry revision. A stale revision makes
the command fail without applying its requested Registry mutation.

The examples below use placeholders. Resolve them to absolute paths before
running a command:

```sh
PYTHON=/Library/Developer/CommandLineTools/usr/bin/python3
RELEASE="/absolute/path/to/the/reviewed/release"
DATABASE="/absolute/path/to/factory-registry.sqlite3"
CONFIG="/absolute/path/to/config.factory.json"
PRESERVATION="/absolute/path/to/registry/evidence/preservation_snapshot_2026-09-24.json"
COMMIT="the-full-reviewed-release-commit"
```

Run the module from the release root so imports also come from that immutable
release:

```sh
cd "$RELEASE"
```

Do not use an operator script from a source checkout against an installed
Registry. `MANIFEST.sha1` must name `COMMIT` and the exact set of regular files
in the release. Every entry is checked before a controlled mutation; duplicate,
missing, extra, changed, symlink, and special-file payloads are rejected.

## Install preservation evidence and migrate schema v3

The only accepted preservation snapshot has SHA-256
`7d47f980d66bf84676cb6d0c24a7eeab0efe40bbe2451d7b27dfd1d6ed94fce6`.
It records 33 worktrees, 8 dirty worktrees, 7 unmerged branches, no unexplained
records, and no unreleased live leases. Its source must already be owned by the
current user with mode `0600`. Install its exact bytes into the Registry's
owner-only evidence directory before using it operationally:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli install-preservation \
  --database "$DATABASE" \
  --source /absolute/path/to/the/approved-preservation-snapshot.json \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --expect-revision REVISION
```

For a schema-v3 Registry, read `status`, confirm the reported revision, and run
the reviewed migration while it is PAUSED, kill-engaged, and has no lease,
attempt, runtime, orphan, or unbound ownership:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli migrate-registry-v4 \
  --database "$DATABASE" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION
```

The migration creates and verifies a consistent owner-only v3 backup, applies
the v4 review-outcome table and append-only triggers in one immediate
transaction, and checks integrity, foreign keys, unchanged control and
revision, empty review outcomes, and exact preservation afterward. A
transaction failure rolls back. A post-commit verification failure restores
the v3 backup automatically. Before any v4 review outcome is recorded, an
operator can explicitly restore the reported backup:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli restore-registry-v3 \
  --database "$DATABASE" \
  --backup /absolute/path/from-the-migration-evidence.sqlite3 \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION
```

## Evidence-only status and preflight

Status is read-only and does not require a revision:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli status \
  --database "$DATABASE"
```

Preflight verifies SQLite integrity and foreign keys, WAL mode, PAUSED control,
the preservation source hash and the actual imported artifact/package/worker
rows, empty lease/attempt/runtime ownership, the release commit and a complete
manifest covering every release file and runtime dependency, the reviewed
configuration, and private/immutable filesystem modes:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli preflight \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION
```

Add `--require-workers` only after active worker telemetry has been synced. Add
`--canary-feature FEATURE_ID` once the canary is registered. That stronger gate
requires fresh heartbeat and capacity evidence, healthy authentication and
provider diagnostics, at least 20 percent Orchestra reserve, an eligible
implementation worker, an eligible reviewer, and at least one implementer /
reviewer pair with different worker identities.

## Prepare PAUSED dry-run services

The migration file may set only `capacity_mode` and `capacity_scopes` for the
exact `codex-a`, `codex-b`, and `claude` agents. The command fixes each agent at
one slot; supplies the reviewed Registry path, 2,100-second lease, 30-second
renewal, and 90/95/98/defer capacity policy; points `gh` to `github.py` in the
selected immutable release; and wraps Claude with that release's
`claude_keychain.py` using the operator's Python interpreter. Old-release,
source-worktree, temporary, and arbitrary command paths are rejected, as are
secret-shaped fields.

```json
{
  "agents": {
    "codex-a": {
      "capacity_mode": "percentage",
      "capacity_scopes": ["short_window", "weekly_window"]
    },
    "codex-b": {
      "capacity_mode": "percentage",
      "capacity_scopes": ["short_window", "weekly_window"]
    },
    "claude": {
      "capacity_mode": "provider_signal",
      "capacity_scopes": ["provider_signal"]
    }
  }
}
```

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli prepare-dry-run \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION \
  --migration /absolute/path/to/reviewed-config-migration.json \
  --mode lanes \
  --dashboard-port 8787
```

This command calls the controlled `pause_to_dry_run` chain. It engages the
Registry kill switch before stopping a loaded service, backs up installed
definitions, drains Registry ownership, atomically writes and backs up the
configuration, restricts Registry/config storage to the owner, removes write
bits from the release, writes only `--dry-run` worker definitions, returns the
Registry to PAUSED, and then bootstraps the dry-run services. A configuration
failure leaves the Registry STOPPING and the prior definitions unloaded. A
bootstrap failure leaves PAUSED dry-run definitions installed and never
restores a live definition.

## Sync active worker telemetry

Imported `legacy-worker:*` rows remain immutable preservation records. Each
active worker uses a separate identity. Sync one worker at a time and fetch the
new revision before the next mutation.

```json
{
  "worker": {
    "id": "codex-a",
    "display_name": "Codex A",
    "role": "WORKER",
    "availability": "IDLE",
    "capabilities": ["documentation"],
    "approved_lanes": ["PLATFORM"],
    "last_heartbeat_at": "fresh UTC timestamp",
    "usage_state": "NORMAL",
    "provider_diagnostics": {
      "provider": "openai",
      "capacity_mode": "percentage",
      "capacity_scopes": ["short_window", "weekly_window"],
      "service_state": "healthy",
      "authentication_state": "valid",
      "live_invocation_state": "succeeded"
    }
  },
  "usage_observations": [
    {
      "id": "unique-observation-id",
      "worker_id": "codex-a",
      "capacity_scope": "short_window",
      "capacity_mode": "percentage",
      "consumed_percent": 10,
      "state": "NORMAL",
      "observed_at": "fresh UTC timestamp"
    },
    {
      "id": "another-unique-observation-id",
      "worker_id": "codex-a",
      "capacity_scope": "weekly_window",
      "capacity_mode": "percentage",
      "consumed_percent": 20,
      "state": "NORMAL",
      "observed_at": "fresh UTC timestamp"
    }
  ]
}
```

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli sync-worker \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION \
  --telemetry /absolute/path/to/sanitized-worker-telemetry.json
```

Heartbeats older than 180 seconds and capacity evidence older than 900 seconds
are rejected. Percentage observations must cover every configured scope and
their state must match the 90/95/98 thresholds. Provider-signal evidence must
record a healthy service, valid authentication, a successful live diagnostic,
and no limit signal. Orchestra must use percentage evidence and retain the
20-percent reserve. Secret-shaped keys are rejected rather than copied.

## Register the A5 canary

The reviewed spec contains exactly one READY `PARENT` implementation package
and one READY `REVIEW` package in the ASSURANCE lane. The review depends on the
implementation and requires `review` or `independent-review`. Both package IDs
must use the runner's `TASK-number` format.

Each package also includes the exact normalized GitHub issue body as
`queue_contract`. The operator stores only its SHA-256. A live runner hashes
the selected issue body and refuses the claim if any instruction, allowed path,
dependency, lane, kind, size, or risk field differs. The review issue's numeric
dependency must be the implementation task number.

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli register-canary \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION \
  --spec /absolute/path/to/reviewed-a5-canary.json
```

Registration is atomic and requires PAUSED, empty ownership, no other READY or
ACTIVE package, healthy worker gates, and a distinct eligible reviewer. A
review dependency becomes eligible when its implementation reaches
VERIFY_REVIEW; normal dependencies still require DONE. Both pre-claim and the
atomic lease acquisition read the successful implementation attempt and reject
that exact worker as the reviewer.

## Enable only the reviewed canary

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli enable-live \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION \
  --canary-feature FEATURE_ID \
  --mode lanes \
  --dashboard-port 8787
```

The command repeats every preflight and worker gate, rejects unrelated READY or
ACTIVE packages, promotes the current reviewed dry-run definitions while the
Registry remains PAUSED, and finally compare-and-swaps that exact revision to
LIVE. If the final compare-and-swap fails, it engages the kill switch and uses
the controlled pause chain to restore dry-run definitions.

The generic `install_launchd.py` command cannot install LIVE definitions or use
`--replace-current`. Those operations require the in-process capability used by
this reviewed operator after its Registry gates pass.

## Stop, reconcile, retry, and return PAUSED

Emergency stop has no revision precondition so a stale operator can always
close dispatch first:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli stop \
  --database "$DATABASE" \
  --reason "bounded A5 canary complete"
```

After reading the new revision with `status`, terminate recorded process groups
and close runtime and lease-only ownership:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli reconcile \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION
```

A failed package can be requeued only while PAUSED, only after a terminal
FAILED or BLOCKED attempt, and only with no active ownership. The old attempt,
lease, events, and evidence remain unchanged:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli requeue-failed \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION \
  --package TASK-NUMBER \
  --reason "reviewed deterministic canary retry"
```

Record the independent reviewer decision only after the reviewer attempt has
finished and the Factory has returned to PAUSED. The spec contains one review
evidence object and one schema-v4 review outcome. The evidence must name the
review package, use kind `review`, and bind `metadata.attempt_id` to the actual
successful reviewer attempt. An approval must name exactly that evidence ID.
The Registry atomically stores and validates both records against the actual
implementation worker, reviewer worker, review interval, dependency, and
attempt provenance:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli record-review-outcome \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION \
  --spec /absolute/path/to/review-outcome.json
```

Return STOPPING or RECOVERY_REQUIRED to PAUSED only after reconciliation and a
fresh revision read:

```sh
"$PYTHON" -m scripts.factory_registry.operator_cli return-paused \
  --database "$DATABASE" \
  --config "$CONFIG" \
  --release "$RELEASE" \
  --release-commit "$COMMIT" \
  --preservation "$PRESERVATION" \
  --expect-revision REVISION \
  --reason "ownership drained and preservation reconciled"
```

Do not edit the Registry with ad-hoc SQL or call internal Python methods from a
shell. Preserve the JSON output from every command with the canary evidence.
