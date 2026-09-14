# TASK-007 delivery and review notes

## Implemented slice

Morning Digest derives from CaptureRecord-backed Interpretations and SemanticObjects, plus separate CalendarEvents. It never changes captures, interpretations, objects, reminders, events or their delivery eligibility. The legacy UI is reconciled through the existing pure adapter so newly confirmed work appears immediately, without waiting for reload.

- Fixed today and confirmed deadlines: **blocked/deferred**. D-009 requires separate timestamped confirmation for scheduling and fixed deadlines. The current schema only records Action/Commitment confirmation; neither CalendarEvent status/timestamps nor date-shaped metadata establishes temporal confirmation. Both buckets remain empty, and the UI explicitly reports them unavailable rather than claiming no events/deadlines exist.
- Unscheduled obligations: up to three explicitly confirmed commitments, displayed as “Confirmed obligations — schedule unverified.” Unverified dates and linked events do not suppress these obligations or establish timing.
- Recommended execution: up to three explicitly confirmed Actions ordered by recorded strategic importance, then identity. Known unfinished or missing dependency targets exclude a recommendation. This is a deterministic selection, not an Adaptive Plan, capacity estimate, or composite priority formula.
- Decisions: up to five current interpretations needing review (including unresolved reminder instructions); superseded versions are excluded.
- Project/objective signals: up to three confirmed objects and their actual status; no invented progress metrics.

The bounded counts follow the archive's attention limits. Original source records and provenance references remain available in the canonical model. Wider workbench/drill-down reintegration remains TASK-008.

## Delivery contract

The dedicated “Enable 7 AM in-app digest” gesture opts into this schedule only. It does not confirm object-level reminder instructions or request OS/browser notification permission. A separate localStorage key, `threadline-morning-digest-v1`, records enabled state, gesture timestamp and last delivered local date. The semantic schema and app-shell service worker are unchanged.

While mounted, the app checks the local clock every 15 seconds and on focus/visibility changes. When visible at or after 7 AM, it displays an accessible in-app notice linking to the live digest. Opening later catches up for that day only. Hidden/suspended/closed applications do not deliver; resuming rechecks the clock. DST uses wall-clock local hours rather than a 24-hour repeating timeout. Travel uses the device's current date/timezone. Manual viewing is always available, including before 7 AM or with delivery disabled.

Delivery settings are persisted before publishing a notice. Read/write failures are surfaced and fail closed for automatic delivery. Disable/re-enable preserves the day's delivery marker. Storage events and a pre-delivery re-read reduce duplicates across tabs; localStorage has no transactional cross-tab claim, so simultaneous visible tabs can still show duplicate in-app notices. This is not an exactly-once guarantee. Clearing browser storage also clears consent/history. The notice is session UI, and the digest is a live projection, not a historical snapshot.

## Exact closed-app mobile delivery blocker / proposed follow-up

Proposed task: **Decide and implement closed-app Morning Digest Web Push** (unassigned; depends on TASK-007 and an explicit backend/product decision).

The current repository has no push subscription endpoint/store, authenticated user/device identity, scheduled server execution, push sender credentials, or server-readable digest data. The worker only caches the app shell; registering it does not schedule background execution. No provider was selected or invented in TASK-007.

Required decision and inputs:

1. Choose/authorize backend hosting and scheduled execution, subscription ownership/authentication, and provision Web Push sender/VAPID credentials with private keys kept server-side.
2. Decide whether the notification is a generic “open your digest” message (which can leave thought data local) or a personalized digest (which requires an approved synchronization/privacy model). The worker cannot read the app's localStorage.
3. Define home/device timezone behavior, travel, missed delivery, multi-device deduplication, unsubscribe and retention policies, and permission/onboarding expectations for supported mobile browsers/installed PWAs.
4. Implement explicit permission/subscription consent, secure subscription storage and revocation, scheduler, push and notification-click handlers, then verify on real installed mobile devices with the app closed.

This blocks true closed-app notifications, not the implemented in-app slice. No background-push capability is claimed in the UI.

## Temporal confirmation prerequisite / proposed follow-up

Proposed task (unassigned, not implemented): **Record and persist dedicated fixed-deadline and CalendarEvent scheduling confirmation provenance** under D-009 and D-005, including explicit authoring, timestamped transition evidence, validation and reversal. This prerequisite blocks TASK-007’s fixed-event and confirmed-deadline buckets, including classification over canonical fixtures. Action or obligation confirmation cannot substitute for it. No schema or product decision is introduced here.

The compatibility adapter also discards unconfirmed legacy deadline metadata, current screens cannot author canonical CalendarEvents, and its validator reconstructs adapter-derived objects. The follow-up must address canonical authoring/persistence before enabling those buckets. Until then, available actions, decisions, obligations and project/objective signals remain useful for in-app delivery. Local-date utilities serve the digest day and delivery schedule (including persisted delivery-day validation); temporal-fact matching is deferred until facts can be validated. Recurrence, all-day events and event duration/overlap remain outside the current CalendarEvent contract.

## Validation and independent review

- `pnpm check`: 64 tests passed; TypeScript and Vite production build passed. No lint script configured.
- Network-restricted environment: initial pnpm auto-install attempts failed DNS. Dependencies were copied into this worktree from the existing TASK-018 dependency directory (read only at source); no package/lockfile changes. A temporary `/tmp/task007-bin/pnpm` wrapper disabled pnpm's automatic dependency reinstallation for the successful check, including nested script invocations.
- Focused tests: all 13 passed separately under `TZ=America/Los_Angeles` and `TZ=Asia/Tokyo`, covering local midnight, DST wall-clock trigger, invalid delivery dates, excluded unconfirmed temporal data, confirmation, classification, current review versions, schedule consent, catch-up, visibility, deduplication, disabled and corrupt settings.
- `git diff --check` passed; changes inspected. No commits, resets, rebases, cleans, merges or writes to other worktrees.
- Browser check attempted but blocked: Vite failed to listen on `127.0.0.1:5177` with sandbox `EPERM`; agent-browser failed to create its socket directory with `Operation not permitted`. No browser verification is claimed.

Independent reviewer should run a focused mobile-width browser check: inspect readable/keyboard-accessible controls; enable at 6:59 and advance to 7:00; verify one notice, navigate from another app view using Read digest, reload and verify no repeat; advance to next day, hide/resume, disable/re-enable; simulate storage failures; confirm a proposed Action and verify the live digest updates. Verify no Notification permission prompt and no closed-app push claim. P1 temporal-confirmation correction is ready for independent rereview; author left all changes uncommitted at the user's request.
