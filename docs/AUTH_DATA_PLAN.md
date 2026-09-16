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

## TASK-029 delivery: Supabase client login wiring

The Settings shell now has a visible Account card and a typed `src/auth.ts` boundary wired to
`@supabase/supabase-js`. Email magic link is the selected login method. When
`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are missing or invalid, the app remains
local-only and honestly shows auth as unconfigured. When those env vars are present, the
client restores sessions, listens for auth state changes, sends email sign-in links, and logs
out through Supabase Auth.

The boundary never reads or writes Threadline application storage. Local-only **data** is shown
independently of account identity. Neither sign-in nor sign-out migrates, clears, or changes
thoughts, canvas, settings, or digest data. Auth tokens are not part of the session projection
or existing exports.

### Remaining hosted setup and validation

1. Choose the Supabase project for Threadline and enable Email magic links.
2. Set Site URL and redirect URLs for the production Vercel URL, preview URLs, and local
   development.
3. Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` to Vercel Production and Preview
   environment variables. Never add a service-role key with a `VITE_` prefix.
4. Independently test link delivery/callback, reload restoration, failed/expired links,
   logout, and network errors on the hosted app; verify local data remains intact through
   account transitions.

Cloud persistence/RLS, explicit import, and account privacy controls remain TASK-034–037.
They were not implemented by TASK-029.

### Exact response to move forward
`Choose the Supabase project for Threadline, set Vercel env vars, then validate hosted email login/logout and local-data preservation.`

## TASK-042 delivery: explicit signed-in account storage (#60)

The client now shares its existing Supabase auth client with an account adapter. A user
must explicitly choose **Copy this device’s local data into my account** or **Load account
data on this device** in Settings → Data. Signing in performs no application-data request.
Import creates an account row only when none exists; it never replaces an existing account.
Load validates the complete account document before opening it in memory. Neither action
writes or deletes the device’s local thoughts, profile or digest preferences.

After activation, thoughts, Review decisions, Bank context folders, canvas, settings and
digest preference save together. The payload preserves the existing schema-v2 model and
its AppState projection, including raw captures and interpretation history. Review and Bank
remain projections of that same model, not separate cloud records. Exports include prior
saved evidence revisions and current edits. Saves are serialized and use revision matching;
a stale device cannot silently replace newer account changes. Errors stop automatic saves
and offer retry/export. Loading again is explicit, with a warning to export unsaved work.
Account changes pause the workspace rather than putting account content into local storage.
Returning to local data or reloading leaves the account copy intact and restores local mode.

### Deployment contract (generic; no project identifiers or credentials)

Use the existing public client configuration, `VITE_SUPABASE_URL` and
`VITE_SUPABASE_ANON_KEY`, plus **`VITE_SUPABASE_DATA_TABLE`**, a non-secret unqualified table
name (lowercase letters, digits and underscores, beginning with a letter). Missing or invalid
configuration disables account data actions. No service-role key or privileged backend is
used or required for this slice. Do not put private project details or keys in source/docs.

Provision the table and RLS separately before hosted validation. The following generic SQL
illustrates the required contract; the table name must match the public configuration.
This task does not execute dashboard changes or SQL against any project.

```sql
create table public.threadline_account_data (
  user_id uuid primary key references auth.users(id) on delete cascade,
  revision uuid not null,
  data jsonb not null check (jsonb_typeof(data) = 'object')
);
alter table public.threadline_account_data enable row level security;
revoke all on public.threadline_account_data from anon;
grant select, insert, update on public.threadline_account_data to authenticated;
create policy "Read own Threadline data" on public.threadline_account_data
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "Insert own Threadline data" on public.threadline_account_data
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Update own Threadline data" on public.threadline_account_data
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
```

The JSON envelope is `{ model, settings, digest }`. `model` retains the current persisted
shape. `revision` is an opaque client-generated UUID replaced on each successful write.
Create-only upsert uses `ON CONFLICT DO NOTHING`; edits filter by both owner and expected
revision and require one returned row. Missing rows, denied access, malformed documents,
network failures and conflicts never fall back to overwriting local data. RLS is essential:
client-side owner filters alone are not a security boundary. Verify with two real accounts
that each cannot select, insert or update the other's row before deployment.

### Validation and limitations

Automated checks cover adapter read/upsert/update filters, create-only import, missing
configuration, denied/offline operations, no implicit migration, unchanged local mode,
serialized saves, revision conflicts, stale account completions, safe retries, preservation
of intermediate evidence, and Review/Bank/settings/digest roundtrip. `pnpm check` includes
unit tests, TypeScript and the production build: all 300 tests across 17 files passed, as
did TypeScript, the production build and `git diff --check`. The existing nonblocking
bundle-size warning remains; there is no configured lint script.
Independent runner review and real desktop/phone, auth and RLS smoke validation remain
required; no live Supabase project was accessed by this task.

This is explicit snapshot storage, not realtime collaboration: load the latest account
version on the other device before editing. Conflicts require exporting unsaved work and
loading again; there is no automatic merge. Import into a nonempty account is refused;
combining multiple existing local datasets remains follow-up work. Failed saves stay in
memory only, with an export path; there is no durable offline account cache. Session undo
history resets on load. Reload starts local mode and requires explicit account activation.
The account digest preference is stored and editable; its digest is available on demand.
Scheduled account notices are not wired in this slice because the existing digest UI writes
directly to device storage, outside the permitted paths. Local-mode digest behavior is
unchanged. Account deletion and remote backup restoration remain TASK-037/follow-up scope.
TASK-034–036 must be reconciled with this delivered slice before further assignment.

Build-in-public note: You can explicitly copy this device’s thoughts into your account and
load them on your phone, including Review, Bank folders and preferences. Local data stays
intact, and competing edits stop with an error instead of silently overwriting work. The
next visible step is hosted two-device validation; realtime merging remains future work.

### Exact response to move forward (TASK-042)
`Run independent review, provision the documented owner-only RLS table and public table-name configuration, then validate explicit import/load, desktop-to-phone Review/Bank edits, conflicts, offline errors, exports and sign-out/local preservation with two test accounts. The runner owns commit and PR delivery.`
