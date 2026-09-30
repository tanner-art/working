# Threadline account-level release checks

Updated: 2026-09-24. The primary app is https://temporary-zippy-agate-50psn81.vercel.app/.

## Installed app sign-in

TASK-057 is merged into main. The existing paid Threadline Supabase project has the primary URL as its Site URL, and its Magic link or OTP email template now includes both the email token and browser confirmation link. The saved template was reloaded and previewed. The stable app responded successfully after deployment.

A real installed-iPhone test remains. Request an email in the home-screen app, enter its code in that app, confirm the session appears there, then sign out. Check the browser link separately. Do not uninstall the current app, clear local storage, or share credentials or codes. The code change did not move or delete local data.

## Account data and isolation

The account-data table has a UUID owner key linked to Auth users, a UUID revision, a JSON-object payload check, enabled RLS, and owner-only INSERT, SELECT, and UPDATE policies. Read-only catalog checks found no anonymous table grants.

Live catalog verification on 2026-09-24 found that this earlier grant warning was stale for `public.threadline_account_data`: the authenticated role already had only SELECT, INSERT, and UPDATE, and anonymous access remained revoked. The four excess signed-in grants existed on the unused legacy `public.threadline_user_state` table instead. With explicit product-owner approval naming that table, DELETE, TRUNCATE, REFERENCES, and TRIGGER were revoked from `authenticated`; SELECT, INSERT, and UPDATE were retained. Post-change catalog evidence confirmed the intended grants, unchanged RLS, and unchanged policies. Anonymous legacy-table grants were outside this approval and remain a separate documented risk. The before/after evidence is recorded in [security/SUPABASE_PRIVILEGE_REVIEW_2026-09-24.md](security/SUPABASE_PRIVILEGE_REVIEW_2026-09-24.md).

After permission cleanup, validate with two real accounts and two devices: explicit local-to-account copy/load, changes in both directions, Account B unable to read or write Account A's row, stale revisions and offline errors leaving source data intact, sign-out returning to preserved local data, and successful recovery export. This cannot be certified from database metadata alone.

## Provider-backed interpretation

The server endpoint and safe client fallback are on main, but provider attempts remain disabled. TASK-031 needs a server-only AI key, direct success and failure checks on /api/interpret, Preview-only evaluation, and explicit Production promotion. No key should appear in browser variables, source code, or this document.

## Pilot versus broader launch

The current Supabase built-in email service is rate-limited and the dashboard warns against broad production use. It is enough to test the sign-in flow; use a production email sender before inviting a larger group.
