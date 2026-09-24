# Factory Control Center projection boundary

## Purpose

`/dashboard` is the authenticated, read-only human view of Factory state. The Registry remains authoritative for features, packages, workers, leases, attempts, evidence, capacity, failures, and events. The browser and Vercel endpoint do not store or mutate Factory state.

The Control Center provides seven views: Overview, Queue, Workers, Reviews, Capacity, History / provenance, and Failures / attention. Queue is organized by Feature and expands into Work Packages. History provides an expandable Registry-backed path from Feature to package, attempt, branch, commit, pull request, and evidence. The UI renders `VERIFY_REVIEW` as **VERIFY / REVIEW**.

## Request path

1. The browser restores the existing Threadline Supabase session.
2. `GET /api/factory-control` verifies the bearer token against the existing Supabase Auth user endpoint.
3. The endpoint requires the verified Supabase user ID to appear in a server-only owner allowlist.
4. The endpoint fetches one current snapshot from the configured HTTPS Registry projection transport using a server-only bearer token.
5. The transport signs the exact UTF-8 response body with HMAC-SHA-256. The endpoint verifies the detached signature before parsing JSON.
6. The runtime contract reconstructs only supported fields. Unknown fields are dropped and missing, malformed, or unsupported values fail closed.
7. The endpoint adds verification metadata and returns the sanitized snapshot with private, no-store caching headers.

There is no dashboard database, browser fallback, GitHub-label fallback, or write endpoint.

## Hosted projection transport limitation

Vercel cannot read the Mac-hosted SQLite Registry or its local files. A separately operated, read-only HTTPS projection transport must call the backend-neutral Registry read contract and serialize schema version `2`. This package deliberately does not expose SQLite, copy its database into Vercel, or introduce a second state store.

Until the owner allowlist is configured, authenticated requests return `503 authorization_unconfigured`. Until the projection transport is running and its server variables are configured, they return `503 projection_unconfigured`. These are the expected safe states.

Required server-only Vercel variables:

- `FACTORY_CONTROL_ALLOWED_USER_IDS`: comma-separated Supabase Auth user IDs authorized to read Factory operations. Empty or missing fails closed.
- `FACTORY_CONTROL_PROJECTION_URL`: absolute HTTPS URL for the read-only snapshot. Credentials in the URL and URL fragments are rejected.
- `FACTORY_CONTROL_PROJECTION_TOKEN`: bearer token sent only from the Vercel function to the projection transport.
- `FACTORY_CONTROL_PROJECTION_SIGNING_SECRET`: shared HMAC secret of at least 32 characters. Rotate it with the transport token and never use a `VITE_` prefix.

The existing `SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY` server variables, or their existing Vite-compatible fallbacks, remain required for session verification. The browser still needs the existing `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` values to restore its account session.

## Transport response contract

The projection transport responds to authenticated `GET` with:

- `Content-Type: application/json`;
- `X-Threadline-Factory-Signature: sha256=<64 lowercase hexadecimal characters>`;
- no more than 1 MiB of UTF-8 JSON; and
- a schema-version-2 Registry projection matching `src/factoryControl.ts`.

The signature is the lowercase hexadecimal HMAC-SHA-256 of the exact response-body bytes using `FACTORY_CONTROL_PROJECTION_SIGNING_SECRET`. Whitespace changes after signing invalidate the response.

The projection must be generated through Registry methods or a Registry API service. It includes one Registry revision so features, packages, workers, leases, attempts, evidence, usage, failures, and events describe one coherent read. Provider/model values are diagnostic. Capacity values declare whether they are provider reported, Factory measured, inferred, or unknown.

The read-only presentation reconciles sparse structured rows against package state from that same revision. Every `VERIFY_REVIEW` package remains visible in Reviews even when the projection has no corresponding structured review row. A missing review outcome is displayed as neutral **Outcome unrecorded**, never as waiting, approved, or rejected. A package-level failure code or `changes_requested` review remains visible in Failures / attention when the structured failure list omits it. When a `VERIFY_REVIEW` package has typed `review` evidence but no structured review outcome or failure anywhere in that revision, Failures / attention shows `REVIEW_STATE_UNRECORDED` as a data-quality remediation item. It does not inspect the human evidence label or infer whether the review approved or rejected the package. These fallback cards are labeled as derived from package state and show unavailable reviewer, timing, or failure fields as not recorded; they do not synthesize Registry facts.

Worker health is also a conservative display projection over the same revision. A worker is shown healthy only when its recorded health and service are healthy, authentication is valid, and its heartbeat is neither missing, future, nor older than the ratified 180-second freshness window. Unknown, invalid, stale, or conflicting evidence is shown as constrained (or offline when the worker or service reports offline), with the reason visible. The Registry projection applies this same effective-health rule before calculating aggregate Factory health, so stale or unknown Orchestra evidence cannot yield a healthy Factory projection.

Claude consumption is represented as Factory-measured scopes when no provider percentage exists. A missing percentage remains `null`; the UI never converts measured consumption or an inferred ceiling into provider-reported usage. The same coherent projection includes the rolling per-invocation ledger used on Workers and Capacity: sanitized account label, session, task/attempt or explicit diagnostic class, timestamp, model diagnostic, input/output/cache measurements, duration, outcome, actual limit signal, and every observed structured source. Autonomous records must resolve to an attempt owned by the same worker; the parser fails closed on a non-null ownership mismatch. Migrated records whose task provenance cannot be established remain visibly `LEGACY_UNCLASSIFIED`, including any partial package or attempt identifiers, and are never relabeled as autonomous work or diagnostic probes. The dashboard does not ingest transcripts or calculate a second ledger.

Each Work Package carries its Registry attempts and attempt-specific branch, commit, pull request, and evidence projection. The History drill-through uses those fields directly. Event history remains a separate chronological view of Registry transitions; neither surface queries Git or GitHub from the browser.

## Failure behavior

The API returns no snapshot when authentication, owner authorization, transport configuration, transport availability, content type, size, HMAC verification, JSON parsing, or runtime contract validation fails. The UI shows an unavailable state with a retry action and retains no independent copy as operational truth.

Same-origin browser `GET` requests may omit the `Origin` header. The API accepts that browser shape only when `Sec-Fetch-Site: same-origin` is present. Requests with a foreign Origin, cross-site fetch metadata, or neither signal remain rejected. Evidence and pull-request URLs become links only when runtime validation identifies an absolute HTTP or HTTPS URL without embedded credentials; invalid values remain plain text.

Local component checks establish that the seven read-only views render against one preserved-canary projection revision, keep sparse rejected review state visible in Reviews and Failures / attention, constrain incomplete worker evidence, expose labeled controls, keep Features and provenance expandable, expose semantic usage tables, and turn unsafe evidence or pull-request URLs into plain text. A development-server route smoke verifies that `/dashboard` serves the application shell. Browser automation was unavailable in the implementation environment because no browser provider was connected and macOS Computer Use permission was not granted, so this package does not claim a completed interactive browser smoke or screenshot.

The Overview attention count is derived from the exact current set rendered by Failures / attention: structured failures with `requiresHuman: true` plus conservative same-revision reconciliation items such as `REVIEW_STATE_UNRECORDED`. Resolved observations with `requiresHuman: false` remain available under History / provenance, are excluded from both the count and current cards, and do not constrain aggregate Factory health merely because their historical severity was critical.

Schema limitation: schema version 2 does not require a structured review or failure row for every package state, and package rows do not carry review assignment, eligibility, request time, findings, review outcome, or a failure occurrence time. The dashboard therefore cannot recover those facts from a sparse projection. It truthfully marks them as not recorded and uses only package-level state, failure code, block reason, implementer attempt, and typed review evidence for fallback visibility. `REVIEW_STATE_UNRECORDED` means only that review evidence and structured state disagree; it is not an inferred approval or rejection. A future Registry schema revision should make those relationships complete rather than asking the dashboard to infer them.

These local checks do not prove the hosted Registry projection path. A hosted test with a real allowed Supabase account, configured signed schema-version-2 projection transport, and live Registry revision is still required before this dashboard satisfies the restart gate. That test must confirm all seven views, drill-through provenance, and Claude ledger rows against one current Registry revision and capture browser evidence after authentication.

This delivery does not create the Registry projection service, configure hosted secrets, deploy the dashboard, or grant Factory write authority. Those are separate reviewed operations.
