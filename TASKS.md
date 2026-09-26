# Threadline Current Task Log

Updated: 2026-09-25 (Europe/Madrid)

This is the active board. The previous board, including historical implementation notes and statuses, is preserved in [the September 22 archive](docs/TASKS_ARCHIVE_2026-09-22.md). Detailed product requirements remain in [Functional Design Priorities](docs/FUNCTIONAL_DESIGN_PRIORITIES.md). A merged PR is marked shipped here even when its real-device release check is still open.

## Shipped on main and certified on the primary URL through PR #72

- PR #68 / TASK-056: durable canvas foundation.
- PR #69 / TASK-046: preserved Review revisions and confirmation invalidation.
- PR #70 / TASK-057: optional email-code sign-in inside an installed app, while retaining the browser link. The existing paid Threadline Supabase email template now contains both options. PR #73 keeps the code field visible after an app restart or a code request in Safari.
- PR #71 / TASK-058: direct thought editing and preserved chronological version history.
- PR #72 / TASK-059: the first Canvas Bank slice: landing page and named, autosaved canvas documents, including lossless first-canvas migration. Duplicate, archive, and restore remain later work.

Primary URL: https://temporary-zippy-agate-50psn81.vercel.app/

The URL responded successfully after PRs #68–72. The Bank landing page and Review editors were inspected on production without altering saved data. No live phone login or cross-account data sync has yet been certified.

## Merged on main after the last primary-URL certification

- PR #75 / TASK-060 shipped Calendar Week and Day views with commitment entry.
- PR #76 shipped the mobile canvas gesture and fit-control slice.
- PRs #77–79 shipped initial organic branch, bulleted-node, and editable connection-handle slices.
- PRs #80–83 shipped the pen, lasso, reversible smoothing, and stroke-shape foundations.
- PR #143 consolidated the beta-readiness foundations, including account data, authenticated interpretation, organization/grouping, calendar connectors, personal statistics, and canvas document work. The open release checks below still govern production certification.
- PR #144 added the installed runner's provider-controlled child review lanes. PR #145 kept the hosted build dashboard projection current.
- PR #150 added the portable Factory registry foundation and preservation import. PR #151 added pure capability dispatch in shadow mode. PR #152 added the read-only live-observation boundary. These merges do not authorize registry cutover or live dispatch.

The September 23 runner-hardening merge series is also present on main. The installed runner remains the live dispatch authority until the separately reviewed controlled restart described in the [Factory architecture](docs/ARCHITECTURE.md#engineering-factory-control-plane).

## Open release checks

1. **P0 — Installed iPhone sign-in.** On the existing primary URL, request one email from the installed app, enter its code there, verify signed-in and sign-out states, and separately verify the same email's browser link. The provider may send 6–10 digits; the Threadline project has sent an eight-digit code. Do not uninstall the existing app, clear browser storage, or share the code. Check that local captures remain available and account data still requires an explicit copy/load action.
2. **P0 — Account isolation and two-device sync.** Verify two distinct accounts and desktop/phone round trips, explicit import/load, owner-only reads and writes, stale-revision behavior, offline errors, and recovery export. Database catalog checks confirmed the owner policies and RLS, but real account tests remain.
3. **P0 — Narrow excess account-table grants.** The signed-in role currently has DELETE, TRUNCATE, REFERENCES, and TRIGGER table grants beyond the intended SELECT/INSERT/UPDATE. No grant was changed: automatic approval review rejected the proposed production revocation because the earlier authorization did not cover that exact permission change. Obtain scoped approval, then remove only the excess grants and verify required operations still work before certifying cross-account safety.
4. **P1 — Physical phone UX smoke.** Open Bank, verify the migrated canvas, create/name/edit/exit/reopen a new canvas, and test Review edit/history and unsaved-draft protection on the phone. Desktop and 390-pixel browser checks already passed. Preserve existing local data.
5. **P1 — Broader email delivery.** Supabase currently uses its built-in email service, which its dashboard warns is rate-limited and unsuitable for a broad production launch. Configure a production email sender before scaling beyond pilot usage.

## September 22 product sequence (historical plan, reconciled September 24)

1. **TASK-060 — Calendar Week and Day views with commitment entry.** Month/Week/Day controls redraw the calendar; Week and Day use a time grid. A commitment can be created from Calendar and shown unscheduled until the user separately chooses a CalendarEvent time. Preserve the distinct obligation and scheduling models. Shipped in PR #75.
2. Mobile canvas zoom, fit controls, usable toolbar space, and tap/hold/drag/resize gestures. The first slice shipped in PR #76.
3. Organic branches, shaped/list child nodes, and editable connection endpoints and curves. Initial slices shipped in PRs #77–79; the epic is not declared complete by those slices alone.
4. Pen, lasso, reversible smoothing, and shape recognition. Foundations shipped in PRs #80–83; later recognition work remains separately scoped.
5. Context-aware capture interpretation and user-confirmed grouping that preserves originals.
6. Chronological Organize log, universal search, date-to-Day navigation, and safe bulk actions.
7. Voice capture and source-linked analysis. Raw audio expires after 14 days by default unless saved or changed in settings; saved audio never auto-expires.
8. Canvas presentation frames with saved coordinates, zoom, order, and edit warnings.
9. Personal statistics. Cross-user rankings require explicit opt-in and privacy safeguards.
10. Optional attributed daily/weekly summaries from user-connected external sources.

Each numbered product area is an epic. The list is retained as the September 22 planning record rather than as current dispatch authority. Deliver one small reviewed PR at a time and retain the confirmation, provenance, and recovery boundaries in the detailed priority document.

## Current dispatch order

- Factory control-plane hardening is now the priority milestone. The
  [September 25 reconciliation](docs/factory/CONTROL_PLANE_HARDENING_RECONCILIATION_2026-09-25.md)
  defines 10 pre-canary repair packages and one post-canary portfolio package.
  Committing that plan does not make any repair or product package runnable.
- Broad product development remains paused until the control-plane repair
  program passes exact-commit independent review and its bounded unattended
  canary.
- Open production release checks and other bounded production-relevant risks take precedence over speculative platform work.
- RISK-003 remains preserved in
  [its reconciliation record](docs/factory/TASK-RISK-GOVERNANCE-RECONCILIATION.md),
  but it is not current dispatch authority for this milestone.

**Dispatch principle:** A known production-relevant risk with a small, bounded remediation outranks speculative platform expansion.

## Separate activation and operations

- The installed runner remains the live dispatcher. The registry, scheduler, and observer merged in PRs #150–152 are migration/control-plane components with no live launch, claim, restart, or cutover authority yet.
- The latest merged live-observation evidence found updating idle parent heartbeats, no READY legacy queue entries, stale Agent A and Agent B usage, and no Claude usage record. All implementation workers were therefore constrained at that observation. This evidence is time-bound and must not be treated as a permanent worker identity or availability rule.
- Repository code now includes the server-side interpretation path and subsequent AI gateway repairs. Main history alone does not certify production activation; Preview evaluation, explicit promotion, and the open release checks still apply.

Historical September 22 operations note, retained for provenance: provider-backed interpretation was described as disabled; the unattended Claude runner had a TLS/credential-environment failure; Agent A was inactive after its work was preserved and released; and the overnight orchestration heartbeat was paused. Current dispatch must use fresh central observations rather than those historical statements.
