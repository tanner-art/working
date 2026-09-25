# Live observation and timestamped shadow validation work package

## Lane

PLATFORM: orchestration infrastructure.

## Scope

Add a read-only, backend-neutral adapter from installed runner telemetry to
`DispatchSnapshot`, produce timestamped shadow decisions, compare them with
observable legacy-runner state, and prove no Factory input was mutated.

## Allowed files

- `scripts/factory_registry/**`
- `docs/factory/**`

## Acceptance criteria

- Reads only explicitly supplied runner config, state, preservation, plan, and
  snapshot sources.
- Whitelists configuration fields and never emits commands, environment values,
  credentials, raw provider payloads, or usage-account identifiers; raw config
  and telemetry bytes are not retained after projection.
- Maps runner workers to registry workers explicitly; provider/model identity
  never grants capability, lane, capacity, or ownership.
- Normalizes mapped usage sources to `short_window`, `weekly_window`, or optional
  `billing_budget`; never duplicates or guesses an ambiguous source.
- Missing, stale, future, invalid, or unmapped usage remains constrained.
- Missing, stale, future, invalid, or unknown heartbeats remain constrained.
- Projects onto a copied `DispatchSnapshot` and leaves the input unchanged.
- Records complete worker, package, pair, rejection, and proposal evidence from
  the pure shadow scheduler.
- Treats active heartbeat assignments as observed legacy behavior; unresolved
  ready queue entries or active records without task identity fail comparison.
- Validates preservation counts, imported-package identities, duplicate source
  tasks, source digest, active legacy records, and active leases while ignoring
  native packages created after the preservation import.
- Stable sources remain byte-identical through a sweep. Heartbeat timestamp/PID
  churn is allowed only when worker/task/status semantics remain unchanged.
- Samples the live decision time after source capture so an advancing heartbeat
  cannot appear future merely because capture took time.
- Evidence output is create-only and the callable rejects Factory-controlled or
  preserved destinations.
- Adds no registry writes, leases, worker launches, service control, GitHub
  calls, queue/dashboard mutation, or live-dispatch authority.
- Receives independent ASSURANCE review before merge readiness.

## Superseded policy note

- Capacity scopes: `short_window`, `weekly_window`, optional `billing_budget`,
  or explicit `provider_signal` mode.
- Package capacity uses explicit size and risk fields documented in
  [CAPACITY_POLICY.md](CAPACITY_POLICY.md).
- Freshness/alignment: heartbeat 180 seconds, usage 900 seconds, sweep 900
  seconds ±60, legacy comparison 60 seconds.
- The earlier `GREEN`/`SLOW` 70/80 proposal was superseded by the ratified
  90/95/98 staged policy.

## Exclusions

- Running three scheduled operational sweeps in this code change.
- Simulating completion/failure without a reconciled active assignment.
- Registry cutover or controlled restart.
- Modifying the legacy runner, dashboard, queue, services, provider usage feed,
  or preserved work.
