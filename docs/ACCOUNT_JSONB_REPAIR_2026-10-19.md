# Account-load JSON field-order repair

## Evidence and scope

The recent phone account GET returned HTTP 200; read-only aggregate inspection
found one account workspace with 99 captures and 94 semantic objects. This does
not prove identity/content parity with the phone. No private capture text was
retrieved or changed. A synthetic capture accepted before JSON key reordering
was rejected afterward by `isPersistedState` with `Invalid account data`.

Postgres [documents that jsonb does not preserve object-key order](https://www.postgresql.org/docs/current/datatype-json.html).
Existing mocks returned `structuredClone` and masked this production behavior.
The Supabase skill led to checking the real database round trip, not changing
RLS or replacing user data. The current changelog was checked; the upcoming
November TLS change does not explain a successful October HTTP response.

## Repair

Use one JSON comparator that recursively orders object keys but never arrays.
Keep ordinary JSON optional-field serialization semantics. It supplements,
never replaces, existing schema and provenance validation. Use it for semantic
reconstruction, temporal/grouping provenance, account record/canvas merge,
merge fingerprints and local/account difference detection. No saved records
are rewritten by the comparison.

## Verification

- Before repair: database-style round-trip mocks caused 13 failures across
  account storage and sync tests.
- After repair: 813 tests in 74 files pass, including those same mocks.
- Added negative coverage for changed values/types, added fields, array order
  and multiplicity, altered semantic IDs, reversed interpretation history,
  grouping-signal tampering and changed canvas geometry.
- Follow-up audit reproduced one more failure for a saved recognized Canvas
  shape. Its nested derived-geometry comparisons now use the same comparator;
  reordered shape evidence passes while changed raw geometry is rejected.
- Specific and daily-log Reminders plus scheduled Actions survive reordered
  snapshots with temporal decisions preserved.
- An actual read-only Supabase SQL expression converted a synthetic full account
  payload through jsonb. The repaired app accepted the returned data and merged
  it without adding duplicates. No table insert/update/delete occurred.
- App typecheck/build and API typecheck pass. No lint script is configured.
- Existing large-bundle warning remains, unrelated to this repair.

## Release boundary

This is source/test evidence, not a claim that the phone runs the repair.
PR 468 must receive a fresh exact-commit review and release checks. Main merge
is prohibited by the governing task instructions. Production deployment and
physical-device parity remain unverified; preserve the phone's local copy.
