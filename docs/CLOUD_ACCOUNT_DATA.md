# Cloud-first account data foundation

Status: implementation foundation only. This module is not wired into `App.tsx` yet.

`src/cloudAccountData.ts` coordinates the existing Supabase account adapter without changing
the local workspace schema or local-storage keys. Its purpose is to let the application make
account data the default after authentication while keeping local captures recoverable.

## Source selection

| Situation | Selected source | Write behavior |
| --- | --- | --- |
| Signed out | Existing local workspace | Existing local persistence remains in charge |
| Signed in, cloud row exists | Cloud account row | Revision-guarded cloud writes |
| Signed in, cloud row is empty | Existing local workspace | Cloud creation requires explicit `importLocal()` |
| Cloud unavailable, valid account cache exists | User-scoped recovery cache | Edits stay in recovery until explicit retry |
| Cloud unavailable, no account cache exists | Existing local workspace | Account writes remain disabled; the UI must label this local/offline |
| Preserved write exists and cloud revision is unchanged | User-scoped recovery copy | Explicit retry can safely resume the guarded write |
| Cloud revision changed elsewhere | User-scoped recovery copy | Export or explicit discard/reload; never overwrite the cloud row |
| Owner cannot be verified | Local or recovery copy | Cloud access is blocked |

Cloud data therefore becomes the normal source for a signed-in account that already has data.
Signing in does not copy local data into a new account, overwrite a nonempty account, or delete
the local workspace. These boundaries preserve the explicit-import rule in D-011 and
`AUTH_DATA_PLAN.md`.

Create-only import conflicts are reported separately from network/storage failures: the user
is told that the account already contains cloud data and to load that copy for review. The
adapter never retries that import as an update, and the device’s local data remains untouched.

## Recovery and conflicts

The recovery cache has its own owner-scoped key prefix,
`threadline-account-recovery-v1:`, and never writes the existing Threadline local workspace
keys. A successful cloud read/write records a clean last-known account snapshot. A failed
cloud write records a dirty snapshot with the expected remote revision.

If the connection returns and that revision is still current, `retry()` can safely save the
dirty snapshot. If another device has advanced the revision, the coordinator enters
`conflict`; `retry()` is refused. The caller can offer `exportRecovery()` and then call
`reloadCloud(true)` only after the user explicitly chooses to discard the preserved local
recovery copy. `reloadCloud()` without that explicit flag refuses to proceed.

Imports, saves, and retries share one operation queue so two writes cannot race the same
expected revision. Calling `open()` starts a new generation, including when reopening the
same owner; in-flight results and queued writes from the older generation are rejected rather
than being allowed to replace the newly opened view.

The cache is an availability and recovery mechanism, not a second source of truth. Supabase
remains authoritative in signed-in cloud mode. It is also an application boundary rather than
a security boundary: the database table still requires owner-only RLS.

## Ownership boundary

Every read and write is scoped to the authenticated user ID. The coordinator checks the
current authenticated owner before and after asynchronous operations, rejects stale results
after account changes, refuses adapter rows belonging to another owner, and keeps recovery
records under that owner only. The existing adapter also validates returned `user_id` values.

The database contract remains the generic table and RLS policy documented in
`AUTH_DATA_PLAN.md`. Current Supabase guidance also requires explicit Data API grants for new
tables because tables may no longer be exposed automatically. Grant only `select`, `insert`,
and `update` to `authenticated`, revoke `anon`, enable RLS, and keep separate owner policies
using `(select auth.uid()) = user_id`; update requires both `USING` and `WITH CHECK`.

## Integration steps

1. Construct the existing `AccountAdapter` from the shared Supabase client and the validated
   `VITE_SUPABASE_DATA_TABLE` value.
2. Construct a `LocalAccountSource` that reads the current local `AppState`, settings, and
   digest preference into `AccountData`. Reading must not mutate or clear those stores.
3. Construct `createAccountRecoveryCache()` with browser `localStorage` and then create one
   `createCloudAccountData()` instance with the adapter, local source, cache, and a
   `currentUser` callback backed by the auth state.
4. On confirmed auth state, call `open(session)`. Use the returned `data` as the workspace
   only when the state identifies its source. Keep the phase visible in Settings: local,
   cloud-empty, cloud, offline, recovery, conflict, or blocked.
5. Route workspace saves to `save()` only in active cloud/recovery modes. Existing local-only
   saves remain unchanged when the source is local.
6. For `cloud-empty`, expose a discrete import action that calls `importLocal()`. Do not call
   it automatically on sign-in.
7. For dirty offline recovery, offer export and retry. For conflicts, require export/review
   before the explicit `reloadCloud(true)` action.
8. When auth changes, discard the in-memory view and call `open()` with the new session (or
   `null`). In-flight results for the old owner will be rejected.

Before shipping the wiring, run the existing two-account/two-device hosted checklist in
`AUTH_DATA_PLAN.md`, including denied cross-owner reads and writes, offline saves, stale
revision conflicts, explicit import, sign-out, and local-capture preservation. No production
Supabase project, credentials, or table was touched by this implementation.

## Current limits

- The coordinator stores whole-account snapshots; it does not merge field-level changes.
- Recovery is device-local until a guarded retry succeeds. Users must export conflicting
  changes before choosing the cloud copy.
- Account data at rest in the browser cache is protected by the browser profile, not by
  application-level encryption.
- Realtime subscriptions, collaboration, account deletion, and guided merge are separate
  work.
