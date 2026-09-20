# TASK-056 — Existing Canvas Reliability Foundation

Status: REVIEW. Owner: Agent A. Initial independent review requested account text-save batching; focused rereview pending. Do not merge on author validation alone.

## Delivered behavior and boundary

The existing single canvas now saves text as it is typed, preserves completed node moves,
resizes, shape/group/connection edits, and restores pan/zoom after leaving the view or
reloading. Back to Today explicitly exits the canvas without discarding its current state.
The save status identifies device/account storage or directs users to retry/export on failure.
The mobile toolbar scrolls within the screen; the properties row is absent without a selection
and a compact horizontal row with a selection.

`CanvasRepository` exposes only a typed current document read/write contract. Its adapter
patches canvas elements and viewport into the existing aggregate workspace. `canvasSession`
owns grouped text editing and session undo; `useCanvasWorkspace` owns its workspace lifetime
and shortcuts. `Canvas.tsx` renders and forwards editing gestures; `App.tsx` composes the
workspace. The existing local store and account session remain the atomic persistence owners,
including their error reporting, evidence preservation, and concurrency guards. No competing
canvas storage key or database was introduced.

Text changes reach the in-memory workspace immediately. Device saves run on each change; account
text saves coalesce after a short pause and flush on blur, canvas exit, or page hide. One focus/edit
session remains one undo step. Completed pointer gestures commit once; cancelled/incomplete
pointer previews are discarded. Viewport changes do not enter content undo history. Undo/redo
remains session-only under D-010 and survives app-view navigation, not reload.

## Migration and failure contract

- Legacy v1 and existing schema-v2 canvases retain all element IDs, text, geometry, membership,
  shapes, connection styling, and semantic evidence. Missing viewport reads as `(0, 0, 1)`.
- The optional, validated `canvasViewport` lives alongside `canvas` in schema v2 and is emitted
  on a canvas write. Reading old data alone never writes it. Existing strict older clients will
  fail closed on the new field; update/reload those clients before opening the new snapshot.
- Account snapshot/save/reload carries the viewport. Explicit account merges retain the account
  destination viewport, using the device viewport only when the account has none.
- Invalid viewport/document, unreadable saved state, quota errors, and detected concurrent edits
  do not replace the stored snapshot. Failed writes retain the in-memory document for retry/export.
- Visibility/page exit flushes local work. A browser exit warning is requested while a save has
  failed or account saves are pending. Browsers can suppress unload prompts (especially on mobile);
  users must wait for account-save completion before closing. No offline cloud queue was added.
- Browser tabs do not silently merge or refresh each other's snapshots. A stale save fails closed;
  export unsaved work before reloading the current saved version.

## Validation

- `pnpm check`: 381 tests, application TypeScript, production build, API TypeScript.
- `git diff --check`; author diff inspection; React best-practices review.
- No lint script is configured. Existing build warning: bundle exceeds 500 kB.
- Focused tests cover v1/v2 migration, all canvas edit families, non-empty semantic evidence,
  text-before-blur persistence, undo grouping/no-op handling, viewport restoration, corrupt
  viewport, quota/retry/export, stale-tab/external corruption, isolated snapshots, and account
  snapshot/save/reload/merge preservation. Account save tests verify 80 typed characters make one
  update, retain the latest text on reload, and preserve pending text across a failed save.
- Isolated Chromium browser: real keyboard text persisted while textarea remained focused and
  survived reload; pan/zoom restored across Back to Today and reload; no page errors.
- 390×844 viewport: 390-pixel document width, 0-pixel unselected properties row, approximately
  595 pixels of canvas height. Toolbar remained horizontally scrollable within the screen.
- Injected quota failure kept stored bytes unchanged and current text in memory; Retry saving
  cleared the warning and survived reload. Injected corrupt JSON rendered the editing-paused
  recovery screen and retained the corrupt bytes.

Live authenticated cross-device service testing and physical iOS/Safari testing remain for
independent review. Account behavior is covered by the existing adapter/session test harness.

## Files changed

- `src/Canvas.tsx`, `src/App.tsx`, `src/styles.css`: canvas presentation, shell wiring, navigation,
  save status, and compact mobile controls.
- `src/canvasDocument.ts`, `src/canvasRepository.ts`, `src/canvasSession.ts`,
  `src/useCanvasWorkspace.ts`, `src/useWorkspaceExitGuard.ts`, `src/canvasHistory.ts`: document
  validation, repository adapter, editing/session lifetime, shortcuts, exit guard, history notes.
- `src/domain.ts`, `src/migration.ts`, `src/store.ts`, `src/accountStorage.ts`: optional viewport
  persistence and backward-compatible local/account projection/merge.
- `src/canvasRepository.test.ts`, `src/accountStorage.test.ts`,
  `src/canvasTextSaveQueue.test.ts`: focused reliability tests.
- `src/canvasTextSaveQueue.ts`: batches account text writes and retains pending work for retry.
- `TASKS.md`, this delivery note: bounded task record and review handoff.

## Exact review request

Independently review TASK-056 for regressions in the existing single-canvas experience. Verify
repository/host separation; v1/v2 migration and old-client fail-closed behavior; latest text,
position, group, shape and connection preservation; viewport restoration after navigation/reload;
atomic undo for an edit session; quota/corrupt/stale-tab preservation and export/retry; and mobile
toolbar reachability at 390 px. Run `pnpm check` and `git diff --check`. Report APPROVED or
CHANGES_REQUESTED with concrete file/line findings. Do not merge.

## Separate future work (not implemented, not blocking this slice)

Canvas Bank, multiple canvases, durable capture-linked canvas revisions, realtime merging,
offline account queues, and guided backup import remain outside TASK-056. The existing large
bundle warning can be handled by a separately assigned performance task.

Build-in-public note: Your canvas now remembers typed text and where you were looking when you
return. The mobile controls take less space. It is still one canvas; organizing multiple canvases
is a later step.
