# Phone dashboard snapshot setup

This is a one-row mirror, not a second Factory Registry. The Mac publishes a signed, gzip-compressed, sanitized projection every three hours. Settings → Open agent dashboard opens `/dashboard`; Refresh reloads only the latest published copy. It does not wake or contact the Mac, and the page visibly marks copies older than 3½ hours.

1. Apply `scripts/factory_registry/hosted_snapshot.sql` through the reviewed Supabase migration process. The row accepts at most 1 MiB compressed, represented by at most 1,398,104 base64 bytes; RLS is enabled and browser roles have no grants.
2. Configure server-only `FACTORY_CONTROL_ALLOWED_USER_IDS`, `FACTORY_CONTROL_SUPABASE_SERVICE_ROLE_KEY`, `FACTORY_CONTROL_PUBLISH_TOKEN`, and `FACTORY_CONTROL_PROJECTION_SIGNING_SECRET`. Never expose or log them.
3. Store the publisher token and signing secret in Keychain as `threadline-factory-dashboard-publish-token` and `threadline-factory-dashboard-signing-secret` (or supply protected local-process environment values). Run `python3 -m scripts.factory_registry.publish_control_snapshot --database "$REGISTRY_PATH" --endpoint "https://<Threadline-host>/api/factory-control"` once, without printing the snapshot or credentials.
4. Fill the four non-secret launchd template placeholders and install it as the user's `com.threadline.factory.dashboard-snapshot` LaunchAgent only after first publication succeeds. It runs at login and every 10800 seconds, independently of the Factory runner.

The API deliberately runs on Vercel Node.js, not Edge, because the private Supabase REST read contains the base64-encoded row (up to 1,398,104 bytes). Do not activate this bridge by configuring secrets alone. Merge and deploy reviewed code, apply the table migration, and obtain a fresh independent security review before any production activation. Do not apply the SQL or install the publisher as part of this package.
