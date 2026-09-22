# Threadline Current Task Log

Updated: 2026-09-22 (Europe/Madrid)

This is the active board. The previous board, including historical implementation notes and statuses, is preserved in [the September 22 archive](docs/TASKS_ARCHIVE_2026-09-22.md). Detailed product requirements remain in [Functional Design Priorities](docs/FUNCTIONAL_DESIGN_PRIORITIES.md). A merged PR is marked shipped here even when its real-device release check is still open.

## Shipped on main and the primary URL

- PR #68 / TASK-056: durable canvas foundation.
- PR #69 / TASK-046: preserved Review revisions and confirmation invalidation.
- PR #70 / TASK-057: optional six-digit email-code sign-in inside an installed app, while retaining the browser link. The existing paid Threadline Supabase email template now contains both options.
- PR #71 / TASK-058: direct thought editing and preserved chronological version history.
- PR #72 / TASK-059: the first Canvas Bank slice: landing page and named, autosaved canvas documents, including lossless first-canvas migration. Duplicate, archive, and restore remain later work.

Primary URL: https://temporary-zippy-agate-50psn81.vercel.app/

The URL responded successfully after these merges. The Bank landing page and Review editors were inspected on production without altering saved data. No live phone login or cross-account data sync has yet been certified.

## Open release checks

1. **P0 — Installed iPhone sign-in.** On the existing primary URL, request one email from the installed app, enter its six-digit code there, verify signed-in and sign-out states, and separately verify the same email's browser link. Do not uninstall the existing app, clear browser storage, or share the code. Check that local captures remain available and account data still requires an explicit copy/load action.
2. **P0 — Account isolation and two-device sync.** Verify two distinct accounts and desktop/phone round trips, explicit import/load, owner-only reads and writes, stale-revision behavior, offline errors, and recovery export. Database catalog checks confirmed the owner policies and RLS, but real account tests remain.
3. **P0 — Narrow excess account-table grants.** The signed-in role currently has DELETE, TRUNCATE, REFERENCES, and TRIGGER table grants beyond the intended SELECT/INSERT/UPDATE. No grant was changed: automatic approval review rejected the proposed production revocation because the earlier authorization did not cover that exact permission change. Obtain scoped approval, then remove only the excess grants and verify required operations still work before certifying cross-account safety.
4. **P1 — Physical phone UX smoke.** Open Bank, verify the migrated canvas, create/name/edit/exit/reopen a new canvas, and test Review edit/history and unsaved-draft protection on the phone. Desktop and 390-pixel browser checks already passed. Preserve existing local data.
5. **P1 — Broader email delivery.** Supabase currently uses its built-in email service, which its dashboard warns is rate-limited and unsuitable for a broad production launch. Configure a production email sender before scaling beyond pilot usage.

## Next product implementation, in order

1. **TASK-060 — Calendar Week and Day views with commitment entry.** Month/Week/Day controls redraw the calendar; Week and Day use a time grid. A commitment can be created from Calendar and shown unscheduled until the user separately chooses a CalendarEvent time. Preserve the distinct obligation and scheduling models.
2. Mobile canvas zoom, fit controls, usable toolbar space, and tap/hold/drag/resize gestures.
3. Organic branches, shaped/list child nodes, and editable connection endpoints and curves.
4. Pen, lasso, reversible smoothing, and shape recognition.
5. Context-aware capture interpretation and user-confirmed grouping that preserves originals.
6. Chronological Organize log, universal search, date-to-Day navigation, and safe bulk actions.
7. Voice capture and source-linked analysis. Raw audio expires after 14 days by default unless saved or changed in settings; saved audio never auto-expires.
8. Canvas presentation frames with saved coordinates, zoom, order, and edit warnings.
9. Personal statistics. Cross-user rankings require explicit opt-in and privacy safeguards.
10. Optional attributed daily/weekly summaries from user-connected external sources.

Each numbered product area is an epic. Deliver one small reviewed PR at a time and retain the confirmation, provenance, and recovery boundaries in the detailed priority document.

## Separate activation and operations

- Provider-backed AI interpretation is still disabled. TASK-031 requires a server-only key, endpoint success/failure checks, Preview-only evaluation, and explicit promotion. Built-in rules continue to work.
- Manual Claude review and planning work functions. The unattended Claude launchd runner is not running and last exited with a TLS/credential environment error. Do not weaken certificate verification or reset its state. Runner repair is supporting infrastructure, not the next product feature.
- Agent A is not actively working. Its Canvas foundation and Canvas Bank work were preserved and released; no worktree was discarded.
- The overnight orchestration heartbeat was paused after the September 22 factory handoff.
