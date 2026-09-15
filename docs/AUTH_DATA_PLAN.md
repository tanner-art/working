# Auth and Per-User Data Plan

Status: Accepted plan (TASK-027, GitHub issue #37). Ratified as D-011 in [DECISIONS.md](DECISIONS.md).

This document defines the concrete login and per-user data path for the hosted Vite/Vercel
app so implementation can start without ambiguity. It does not implement backend code and
does not require destructive migration of existing local data.

## Starting constraints

- The app today is a Vite/React SPA deployed to Vercel with no backend service.
- All state is browser `localStorage`, read/written by `src/store.ts` (`thoughtflow-state-v1`)
  and `src/settings.ts` (`threadline-settings-v1`), plus `src/digestDelivery.ts`'s delivery key.
- Local-only usage must keep working unmodified. Nothing in this plan deprecates it.
- D-001 (preserve original expression) and D-009 (explicit confirmation for consequential
  transitions) apply to any account/migration action a user takes, per the ownership model below.

## Options compared

### A. Supabase Auth + Postgres
- One vendor provides both authentication and the per-user database.
- Row Level Security (RLS) enforces `user_id = auth.uid()` at the database layer, so
  cross-user isolation is structural, not something application code must get right.
- Client-only integration (`@supabase/supabase-js`) fits the existing static Vite/Vercel
  deployment; no new server is required for the MVP slice.
- Two client-safe env vars to start; free tier is sufficient for immediate usability.
- Login UI must be hand-built (Supabase ships an optional but plain `auth-ui-react` package,
  not a polished pre-styled component set).

### B. Clerk + hosted database
- Clerk gives the best out-of-the-box login UI (prebuilt, styled React components,
  session/user management) with very fast setup for auth alone.
- Clerk is auth-only: a separate hosted database (e.g. Neon, PlanetScale, or Supabase used
  as database-only) is still required, and Clerk provides no RLS-equivalent enforcement for
  a database it doesn't own. Per-user isolation must be written and verified by hand in a new
  API layer (Vercel serverless functions verifying a Clerk JWT before every query).
- Two vendor accounts, two sets of environment variables, and materially more custom code
  before "cannot read/write another user's data" is actually true.

### C. Minimal custom auth/database path
- Full control, no third-party auth vendor.
- Requires hand-building password hashing, session/token handling, refresh, CSRF protection,
  and the per-user isolation logic RLS gives for free under option A — the largest security
  surface of the three options for a solo-maintained MVP, and the slowest to "immediate
  usability."
- Not recommended as the default; revisit only if a concrete reason to avoid a third-party
  auth vendor emerges later.

## Recommendation: Supabase Auth + Postgres

Supabase is the default for immediate usability because it is the only option that gives both
authentication and structurally enforced per-user data isolation from a single vendor and a
single client library, without a new backend service. This most directly satisfies TASK-030's
original "prevent cross-user reads/writes by construction" acceptance criterion. The tradeoff
is a plainer default login UI than Clerk's; that cost is small and isolated to TASK-029 (login
UI), and does not affect the data ownership model.

## Required environment variables / account-level setup

One-time, human, account-level steps (not implementable by an agent):
1. Create a Supabase project.
2. Enable the Email auth provider (password or magic link; pick one in TASK-029).
3. In the Supabase dashboard, set Site URL and redirect URLs for the Vercel production
   domain, Vercel preview deployments, and `localhost` dev.
4. Create per-user data tables (schema defined in TASK-034) with a `user_id uuid references
   auth.users` column, enable RLS on every such table, and add a policy restricting
   select/insert/update/delete to rows where `user_id = auth.uid()`.

Environment variables:
- `VITE_SUPABASE_URL` — public, safe in the client bundle (Vite only exposes `VITE_*` vars
  to client code).
- `VITE_SUPABASE_ANON_KEY` — public, safe in the client bundle; RLS is what makes this key
  safe to expose, not its secrecy.
- `SUPABASE_SERVICE_ROLE_KEY` — server-only, needed only if/when a Vercel serverless function
  is added later for privileged operations (e.g. account deletion/export in TASK-037). Must
  never reach the client bundle or `VITE_*` namespace.

Set these in Vercel project settings (Production + Preview) and in a local `.env` (untracked)
for development. No env vars are required for local-only usage; the app continues to run with
none of these set.

## Data ownership model

- Every signed-in user's persisted row carries an explicit `user_id` (Supabase `auth.uid()`).
  RLS denies any query without a matching `user_id` — ownership is enforced at the database
  layer, not only in application code.
- Local-only mode is unchanged and remains the default for anyone who has not signed in:
  `src/store.ts` and `src/settings.ts` keep working exactly as today, untouched by this plan.
- Signed-in mode stores the same persisted-state shape already used locally (today's
  `AppState`/`ThoughtObject` compatibility shape, or its future CaptureRecord/Interpretation/
  Semantic Object split per ARCHITECTURE.md) — this plan is a storage-location decision, not a
  new domain schema.
- No implicit migration. Signing in never deletes or overwrites local data. Copying local data
  into the account requires one explicit, user-initiated action ("Import my local data"),
  matching D-009's confirmation-interaction pattern — not a side effect of login.
- Local and cloud copies may coexist during a transition. Deleting the local copy after a
  successful import is a separate, explicit, later action — never automatic.
- Signing out returns the app to local-only mode and must not delete the local copy.

## Follow-up tasks

Concrete task stubs are recorded in [TASKS.md](../TASKS.md):
- **Login UI** — TASK-029 (already tracked; annotated with this plan's provider/env vars).
- **User-scoped storage adapter** — TASK-034.
- **Migration/import of existing localStorage data into a user account** — TASK-035.
- **Sign-out/offline behavior** — TASK-036.
- **Privacy/delete/export settings** — TASK-037.

TASK-030's original combined scope (schema boundary, sync bridge, cross-user prevention,
settings surfacing, migration/access tests) is superseded by the more granular TASK-034–037
above so the two do not get assigned in an overlapping way. TASK-033 (Settings control center)
remains the umbrella surface these features render into and is unchanged by this plan.

None of TASK-034–037 are promoted to READY here: each depends on TASK-029 (a real signed-in
session must exist before a storage adapter, migration, sign-out, or export/delete flow can be
implemented against it), and TASK-029 itself is not yet DONE. They are recorded as concrete
BACKLOG stubs so assignment can proceed without further scoping once TASK-029 lands.

### Exact response to move forward
Assign TASK-029 login wiring to Agent A once TASK-026's merge status is confirmed:
`Assign TASK-029 login wiring to Agent A.`
