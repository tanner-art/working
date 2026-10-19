# CROSS-DEVICE-SYNC — same account, same captures

Owner assignment: phone and laptop must show the same saved captures when signed
into the same Threadline account. Preserve the existing phone's 98 captures.

## Execution and boundaries

One implementation parent, `SYNC-01`, and one exact-commit independent Claude
review, `SYNC-01-REVIEW`. Direct execution in the owner's account is authorized;
these are repository work packages, not a claim that Factory registration or
dispatch occurred. No Factory changes or main merge are part of this work.

Baseline: reviewed repair `90e4465b9187615d7ec6d54b8a68227d542b095b`
(PR 467, includes the Commitment repair). One writer owns App.tsx.

## SYNC-01

- Behavior: sign-in/reload opens existing account data automatically. An empty
  account offers a prominent one-time sync action. Local originals remain intact.
  Account updates refresh on focus/periodically when no editor or unsaved work
  can be displaced. Device-only captures remain recoverable and discoverable.
- Persistence owner: existing accountStorage adapter/session, Supabase owner-only
  row and revision compare-and-swap. Device-local storage remains its own backup.
- Owned paths: src/accountStorage.ts, src/accountStorage.test.ts,
  src/accountSync.ts, src/accountSync.test.ts, src/App.tsx, src/auth.ts,
  src/auth.test.ts, docs/AUTH_DATA_PLAN.md, this package and verification evidence.
  Review-discovered required sync boundary: src/useCanvasWorkspace.ts,
  src/canvasSession.ts and src/canvasSessionSync.test.ts must invalidate stale
  editor history when a remote canvas snapshot becomes the new baseline.
- Out of scope: Factory, main merge, realtime collaborative editing, conflict
  guessing, bulk data overwrite, local deletion, new tables, unrelated features.
- Acceptance: a synthetic 98-capture phone workspace reaches the account through
  explicit initial sync; a new laptop session automatically opens all 98 exact
  IDs/content; a subsequent save appears on safe refresh without a Settings load.
  Sign-out/account-switch, failed reads, stale writes, draft/save/read races and
  missing cloud rows must not lose or overwrite either source.
- Tests: session/bootstrap/refresh tests, full product suite, app/API typechecks,
  build, browser flow where available. No configured lint command.
- Observable completion: same-account phone/laptop capture counts and sample
  IDs agree after actual deployment and first-device sync. Synthetic evidence is
  not proof that the owner's physical phone has been migrated.

## SYNC-01-REVIEW

Depends on SYNC-01 commit/PR and validation. Independent Claude must inspect the
exact sources and diff, attempt to defeat ownership, stale-write and draft
preservation, and return structured APPROVED/CHANGES_REQUESTED/BLOCKED evidence
bound to the commit, base, PR and input hash. Deployment verification follows
review; production is not certified by a passing mocked test.

## Runtime accounting

Record measured author execution and independent reviewer runtime separately in
the final evidence. Do not label elapsed wall-clock time as provider execution
time or estimate agent hours from package size.

## Owner-authorized account-load repair (October 19)

The installed phone reported the generic account-load failure after a successful
HTTP read. A synthetic reproduction found the schema-v2 validator compared JSON
object insertion order, which Postgres jsonb does not preserve. The owner
explicitly assigned the repair. This extends SYNC-01 only to key-order-independent
JSON comparisons used by account load/save, merge, local-difference detection,
and their nested semantic, temporal, grouping and canvas validation paths.

Additional owned paths: src/jsonEquality.ts and its tests, src/migration.ts,
src/temporalConfirmation.ts, src/groupingProposal.ts and its tests,
src/canvasBankMerge.ts, src/canvasStrokes.ts (embedded shape validation), and
src/testSupport/jsonbRoundTrip.ts.

Acceptance: database-reordered fields must load/save/merge without losing any
capture; changed values, extra fields, array/audit ordering changes, duplicate
identities and stale writes remain rejected. No production-data mutation,
database migration, permission change, Factory change or main merge is allowed.
Exact-commit independent review is required again for this repair.
