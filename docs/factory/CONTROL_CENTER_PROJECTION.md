# Factory Control Center Registry projection

## Boundary

The Control Center projection is a read-only view of the authoritative Factory Registry. `Registry.control_center_snapshot()` is the backend-neutral API: any future Postgres or Supabase adapter can implement the same single-read contract. The SQLite adapter gathers the complete read under one query-only transaction and records the Registry revision read in that transaction.

The projector translates that immutable read into Control Center schema version 2. It has no database path, SQL, or storage dependency. It does not write a snapshot to another database, expire leases, update heartbeats, calculate eligibility, or become scheduling authority.

The read includes:

- Features, packages, dependencies, leases, attempts, evidence, structured review outcomes, workers, failures, and events.
- Capacity observations and, when the telemetry migration is present, the append-only invocation ledger and its source history.
- Preservation imports and artifacts used for reconciliation counts.
- READY and ACTIVE packages of Registry kind `REVIEW`, projected as waiting or assigned from their dependency, attempt, lease, capability, and lane records.
- Final `APPROVED` and `CHANGES_REQUESTED` review outcomes from the append-only Registry outcome record. The Registry derives the implementer from the latest successful target attempt, rejects a reviewer with any target implementation attempt, and requires a successful reviewer-owned review-package attempt. Approval requires typed `review` evidence on that review package whose attempt reference names the reviewer-owned attempt. Findings, changes requested, approval, and approval evidence are never inferred from package status, evidence labels, or prose.

All records in one response come from one read transaction and one Registry revision. Unknown event types are omitted instead of being assigned a misleading timeline kind. Pending reviews are emitted only when a READY or ACTIVE Registry review package has enough dependency and attempt history to identify its implementer and request time. Final reviews remain visible after the review package is DONE because the outcome is independent Registry state. Missing service, authentication, usage, token, duration, or reconciliation values remain `unknown` or `null` where the dashboard contract permits it. Required numeric aggregates are sums of recorded rows; zero means no matching recorded rows in that Registry read. Every package carries its Registry kind so both projection validators recompute `activeParentCount` from ACTIVE `PARENT` packages. Projection validation rejects mismatched counts, duplicate identities, unknown dependencies, forged review provenance, and packages that cannot be placed in their Registry Feature queue.

Schema version 2 has no `unknown` Factory health value. A Registry read with no Orchestra worker is therefore projected as `constrained`, as are preservation mismatches, stale active leases, critical failures, and a non-healthy Orchestra. The projector never upgrades missing Factory health evidence to `healthy`.

Provider and account identity remain diagnostic. Raw telemetry `account_id`, source identity, raw limit errors, and source/calibration metadata are excluded. The response uses a non-identifying account label. Evidence and pull request links are limited to absolute HTTP or HTTPS URLs without embedded credentials.

Capacity states use the Control Center schema vocabulary exactly: `normal`, `caution`, `checkpoint`, `hard_stop`, `limited`, or `unknown`. Legacy `FINISH_ONLY` observations normalize to `checkpoint`; actual limit/exhaustion signals remain `limited`. Evidence kinds normalize to `commit`, `check`, `test`, `review`, `artifact`, or `screenshot`; runner logs and otherwise unsupported kinds remain visible as generic `artifact` evidence.

## Local transport

The included server is intentionally local. It binds to `127.0.0.1` by default and rejects non-loopback hosts. It exposes only:

`GET /v1/factory-control`

The request must include `Authorization: Bearer <token>`. A successful response includes:

- `Content-Type: application/json`
- `Cache-Control: private, no-store, max-age=0`
- `X-Threadline-Factory-Signature: sha256=<hex digest>`

The signature is HMAC-SHA-256 over the exact response bytes. The shared signing secret must contain at least 32 characters. Missing or incorrect credentials fail with `401`; projection/read/validation failures return a generic `503` without Registry detail. POST, PUT, DELETE, and HEAD are rejected.

Set secrets in the process environment rather than command arguments:

```sh
export FACTORY_CONTROL_PROJECTION_TOKEN='replace-with-a-random-read-token'
export FACTORY_CONTROL_PROJECTION_SIGNING_SECRET='replace-with-at-least-32-random-characters'
python3 -m scripts.factory_registry.control_center_server \
  --database /absolute/path/to/factory-registry.sqlite3
```

The Vercel Control Center requires an HTTPS projection URL. This loopback service is therefore not directly reachable from Vercel and is not a hosted relay. Selecting, provisioning, securing, and operating a relay or hosting location remains an owner decision. No relay, tunnel, cloud storage, deployment, or production secret is created by this package.

## Verification

Run:

```sh
python3 -m unittest scripts.factory_registry.test_control_center_projection -v
python3 -m unittest discover -s scripts/factory_registry -v
pnpm check
```

The focused tests validate schema-v2 shape, deterministic serialization, cross-source usage history, attempt ownership, secret-field exclusion, exact-body HMAC signing, bearer rejection, write-method rejection, loopback binding, backend-neutral use, and before/after logical Registry equality.
