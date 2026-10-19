# SYNC-01 verification

## Implementation checks

- Full suite: 794 tests / 72 files passing before final review.
- App TypeScript/build and API TypeScript pass; no lint script configured.
- Build retains the existing large-bundle warning; no bundling refactor included.
- Unit fixtures: initial 98-capture upload; automatic laptop open/reload with exact
  capture equality; subsequent remote save/refresh; no refresh echo write; owner
  changes/sign-out; queued saves; stale read after save; draft guards; missing row;
  read failure; device-only capture detection. Existing merge/conflict tests pass.

## Browser → API → data → UI

Isolated Vite app on 127.0.0.1:4196, synthetic Supabase-compatible service on
127.0.0.1:54328. No production keys, account credentials or user content used.

1. Email-code sign-in opened 98 thoughts immediately, without Settings activation.
2. Second browser tab (separate app instance, same browser auth storage) opened
   the same 98. Reloading both retained account mode and 98.
3. First instance saved synthetic thought 99. Second instance showed 99 and its
   exact text on Today without explicit account load. API logged the guarded
   write and reads; no UI console errors/warnings.
4. Second instance retained an unsent draft while first saved thought 100. Its
   view deliberately stayed at 99; switching views did not erase the draft.
5. Clearing that synthetic draft and returning to Today refreshed to 100,
   including both new thoughts. No Settings load was required.

These are two app instances, NOT two physical devices or separate browser
profiles. This proves UI wiring against a test service, not production auth/RLS.

## Read-only production findings

Existing Threadline Supabase project reports one account workspace, 99 immutable
capture records and 94 current semantic objects. RLS is enabled; SELECT/INSERT/
UPDATE policies use auth.uid() ownership (UPDATE includes WITH CHECK).
No private capture text was retrieved and no production row was changed.

The owner's reported 98 phone captures are not yet reconciled to those counts.
Phone origin, signed-in identity and local-vs-account workspace remain to be
confirmed. Do not delete/reinstall/clear phone storage. Automatic cloud load
does not silently import a different local copy; it exposes preserved device-only
captures and retains the explicit preview/confirm merge path.

## Delivery boundary

Independent exact-commit review and remote CI follow the implementation commit.
No main merge, production deployment or actual-phone sync certification is
claimed by this document. No Factory state or safety controls changed.
