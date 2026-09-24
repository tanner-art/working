# Factory Control Center projection boundary

## Purpose

`/dashboard` is the authenticated, read-only human view of Factory state. The Registry remains authoritative for features, packages, workers, leases, attempts, evidence, capacity, failures, and events. The browser and Vercel endpoint do not store or mutate Factory state.

The Control Center provides seven views: Overview, Queue, Workers, Reviews, Capacity, History / provenance, and Failures / attention. Queue is organized by Feature and expands into Work Packages. The UI renders `VERIFY_REVIEW` as **VERIFY / REVIEW**.

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

Vercel cannot read the Mac-hosted SQLite Registry or its local files. A separately operated, read-only HTTPS projection transport must call the backend-neutral Registry read contract and serialize schema version `1`. This package deliberately does not expose SQLite, copy its database into Vercel, or introduce a second state store.

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
- a schema-version-1 Registry projection matching `src/factoryControl.ts`.

The signature is the lowercase hexadecimal HMAC-SHA-256 of the exact response-body bytes using `FACTORY_CONTROL_PROJECTION_SIGNING_SECRET`. Whitespace changes after signing invalidate the response.

The projection must be generated through Registry methods or a Registry API service. It includes one Registry revision so features, packages, workers, leases, attempts, evidence, usage, failures, and events describe one coherent read. Provider/model values are diagnostic. Capacity values declare whether they are provider reported, Factory measured, inferred, or unknown.

Claude consumption is represented as Factory-measured scopes when no provider percentage exists. A missing percentage remains `null`; the UI never converts measured consumption or an inferred ceiling into provider-reported usage.

## Failure behavior

The API returns no snapshot when authentication, owner authorization, transport configuration, transport availability, content type, size, HMAC verification, JSON parsing, or runtime contract validation fails. The UI shows an unavailable state with a retry action and retains no independent copy as operational truth.

Same-origin browser `GET` requests may omit the `Origin` header. The API accepts that browser shape only when `Sec-Fetch-Site: same-origin` is present. Requests with a foreign Origin, cross-site fetch metadata, or neither signal remain rejected. Evidence and pull-request URLs become links only when runtime validation identifies an absolute HTTP or HTTPS URL without embedded credentials; invalid values remain plain text.

Local component checks establish that the seven read-only views render, expose labeled controls, keep Features expandable, and turn unsafe evidence or pull-request URLs into plain text. A development-server route smoke verifies that `/dashboard` serves the application shell. Browser automation was unavailable in the implementation environment because no browser provider was connected and macOS Computer Use permission was not granted, so this package does not claim a completed interactive browser smoke or screenshot.

These local checks do not prove the hosted Registry projection path. A hosted test with a real allowed Supabase account, configured signed projection transport, and live Registry revision is still required before this dashboard satisfies the restart gate. That test must confirm all seven views against one current Registry revision and capture browser evidence after authentication.

This delivery does not create the Registry projection service, configure hosted secrets, deploy the dashboard, or grant Factory write authority. Those are separate reviewed operations.
