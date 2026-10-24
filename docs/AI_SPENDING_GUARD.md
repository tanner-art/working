# Threadline AI spending guard

Scope: the owner-authorized $5/month ceiling for Threadline Chat and capture
interpretation. Brain/search do not call a paid model. This is not a cap on Vercel
hosting, other apps, taxes, or direct use of shared provider credentials.

## Enforcement

- Both server endpoints use one durable ledger, shared across accounts, devices,
  server instances and deployments configured against the same budget database.
- Calendar months use UTC. A database transaction reserves the entire Haiku 4.5
  context ceiling (200,000 tokens), plus the endpoint's maximum output, before
  any paid request. Integer microdollars avoid floating-point accounting.
- A transaction advisory lock serializes reservation and settlement. Duplicated
  reservation IDs cannot authorize another provider call. Settlements are
  idempotent and conflicting second settlements cannot release more money.
- Input/cache tokens are charged conservatively at $3/million and output at
  $10/million, above the verified October 24 public Anthropic endpoint prices
  ($1/$5; cache write $1.25). The public endpoint price/context record is checked
  before **every** request. Unknown prices/dimensions stop execution.
- Successful, structurally valid usage receipts reduce the reservation to this
  conservative charge. Missing usage, crashes, failed provider calls and unknown
  settlements retain the full hold. There is no automatic refund or retry.
- Old unsettled holds also reduce each new month's allowance. A successful reply
  crossing month-end is conservatively charged to both months.
- Only the fixed Haiku model and Anthropic provider are allowed. No paid server
  tools, attachments, reasoning options, fallback models or arbitrary routing.
- Missing credentials, disabled policy, database/catalog outage or malformed
  reservation results stop AI, never capture storage or Brain/search.
- The $5 ceiling is fixed in database constraints; policy can lower it, not raise
  it. Browser roles cannot access the ledger or its functions. Server credentials
  must never use a `VITE_` prefix.

Reservations can temporarily hold roughly $0.61 per in-flight request; validated
replies normally release most of that hold. Conservative charges mean usable
credit can end before the provider dashboard reaches $5. Failed calls may leave
holds requiring an evidence-backed operator reconciliation; never blindly reset.

## Installation / activation gate (NOT yet completed)

1. Run `scripts/ai_spend_guard.sql` once against the intended database, after
   independent review. It is additive, transactional, defaults to disabled, and
   never touches capture/account tables. Preserve its history; do not reinitialize
   counters on deploy. Do not run against an existing installation blindly.
2. Configure server-only `AI_BUDGET_SUPABASE_URL` and
   `AI_BUDGET_SERVICE_ROLE_KEY` for the intended deployment. Restrict the secret
   to Production; preview tests need their own database/credentials. The service
   role is privileged: do not expose it to clients or paste it into chat/logs.
3. Verify actual prior monthly spend and outstanding requests. Seed the current
   month's committed amount conservatively before enabling the database policy.
   Do not assume the new ledger means earlier spend was zero.
4. Inspect actual Gateway routing rules, BYOK and credential scope; ensure no
   dashboard rule overrides the reviewed routing/pricing contract. Confirm the
   owner's $5 budget applies to the actual team/key/OIDC project. Inventory older
   enabled deployments/aliases: they must not provide an unguarded paid path.
5. Verify SQL privileges and true multi-connection contention in isolated staging,
   then one authenticated synthetic end-to-end request, its receipt and Gateway
   cost. Check timeout and exhaustion without sending real captures.
6. Only then enable `AI_INTERPRETATION_PROVIDER=enabled` on the guarded release.
   This switch enables both Chat and interpretation, not just Chat. Record the
   deployed SHA and keep the Gateway monthly budget as defense in depth.

The connector returns 403 for Vercel project environment access; the documented
CLI fallback successfully listed the exact working project's metadata using the
existing local login. Neither budget-specific server variable exists. No
production schema, secret, policy or AI switch has been changed by this repair.
No live inference has been used to validate it yet. The app ledger bounds requests
through this code; provider billing/routing behavior must be verified before
claiming a production hard cap. A provider receipt is trusted billing evidence,
not an independently measured invoice. Provider-internal retries or late charges
must not be represented as covered without verification.

## Local checks

`pnpm check` runs application/API regression tests, builds and typechecks.
`scripts/verify_ai_spend_guard.mjs` runs actual SQL against a disposable PGlite
database, including privileges, cap exhaustion, duplicate operations, invalid
amounts, and cross-month holds. Use `@electric-sql/pglite@0.5.11` installed outside
the repo and set `PGLITE_MODULE` to its `dist/index.js`. This does not change app
dependencies. PGlite queues one connection: it does **not** prove real
multi-connection lock contention; that remains an explicit activation gate.

October 24 verification: all 114 suites / 1,113 tests passed, frontend build and
API typecheck passed, SQL checks passed, independent reviewer approved committing
the disabled implementation with no unresolved code findings. Activation was
explicitly not approved by that review. Existing >500 KB bundle warning remains;
there is no configured lint command. No paid requests or real-data writes ran.

References: Vercel Gateway model/endpoints catalog; Gateway Anthropic Messages
API and Budgets docs; Supabase Database Functions and RLS docs.
