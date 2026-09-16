# Threadline account-level blockers

Current state: the repo is clean and recent app work is merged. There are no known open implementation PRs. The remaining blockers are dashboard/account-level validation and secrets, not normal coding.

## 1. Cross-device login and data sync

Already done:

- Supabase has the Threadline account-data table expected by the app.
- Row-level security is enabled and security advisors were clean.
- Vercel has the required public env names for Supabase account storage.
- The hosted app was redeployed and responded successfully.

Still needed:

- Confirm Supabase Auth Site URL and redirect URLs in the Supabase dashboard.
- Run a real email magic-link login test.
- Run a two-account, desktop-to-phone smoke test.

Validation checklist:

- Login returns to the hosted app.
- Settings → Data can copy this device’s local thoughts into an empty signed-in account.
- Phone can load the same account data and show the same Review queue and Bank folders.
- Edits from one device save to account storage and can be explicitly loaded on the other.
- A second account cannot read or update the first account’s row.
- Sign-out/local mode keeps device data intact.
- Stale revision and offline/RLS errors do not overwrite local data.

Exact response to continue:

`Supabase auth redirect URLs are configured for the hosted app and localhost, and I am ready to run two-account desktop-to-phone validation.`

## 2. Real AI interpretation

Already done:

- The provider-backed `/api/interpret` endpoint exists.
- The client fails closed to built-in rules if the provider is missing or broken.
- Settings shows whether Threadline is using built-in rules or provider attempts.
- Tests cover ambiguous, consequential, low-confidence, malformed, and provider-failure cases.
- Provider-backed interpretation is disabled by default.

Still needed:

- Add `AI_INTERPRETATION_API_KEY` only as a server-side Vercel environment variable.
- Deploy.
- Manually validate `/api/interpret` success and failure behavior.
- Only then consider enabling `VITE_AI_INTERPRETATION_PROVIDER=enabled` in Preview first.

Exact response to continue:

`Set AI_INTERPRETATION_API_KEY only as a server-side Vercel env var, deploy, validate /api/interpret success and failure cases manually, then consider enabling VITE_AI_INTERPRETATION_PROVIDER=enabled in Preview only.`
