# Threadline account-level release checks

Updated: 2026-09-22. The primary app is https://temporary-zippy-agate-50psn81.vercel.app/.

## Installed app sign-in

TASK-057 is merged into main. The existing paid Threadline Supabase project has the primary URL as its Site URL, and its Magic link or OTP email template now includes both the six-digit token and browser confirmation link. The saved template was reloaded and previewed. The stable app responded successfully after deployment.

A real installed-iPhone test remains. Request an email in the home-screen app, enter the six-digit code in that app, confirm the session appears there, then sign out. Check the browser link separately. Do not uninstall the current app, clear local storage, or share credentials or codes. The code change did not move or delete local data.

## Account data and isolation

The account-data table has a UUID owner key linked to Auth users, a UUID revision, a JSON-object payload check, enabled RLS, and owner-only INSERT, SELECT, and UPDATE policies. Read-only catalog checks found no anonymous table grants.

The authenticated role also has DELETE, TRUNCATE, REFERENCES, and TRIGGER table grants that the app does not need. No grant has been changed. Automatic approval review rejected revoking these in production because the existing authorization did not specifically include that permission change. Ask for exact scoped approval before removing only those four grants; retain SELECT, INSERT, and UPDATE.

After permission cleanup, validate with two real accounts and two devices: explicit local-to-account copy/load, changes in both directions, Account B unable to read or write Account A's row, stale revisions and offline errors leaving source data intact, sign-out returning to preserved local data, and successful recovery export. This cannot be certified from database metadata alone.

## Provider-backed interpretation

The server endpoint and safe client fallback are on main, but provider attempts remain disabled. TASK-031 needs a server-only AI key, direct success and failure checks on /api/interpret, Preview-only evaluation, and explicit Production promotion. No key should appear in browser variables, source code, or this document.

## Pilot versus broader launch

The current Supabase built-in email service is rate-limited and the dashboard warns against broad production use. It is enough to test the sign-in flow; use a production email sender before inviting a larger group.
