# TASK-059 — Canvas Bank v1

Status: merged into `main` in PR #72 on 2026-09-22. The integration with PR #71 preserved
both Canvas navigation and the Review modal background guard. CI and Vercel checks passed.

## Result

The Canvas navigation item is now **Bank**. It opens a Canvas Bank list instead of immediately
opening the previous drawing. **Think visually** creates a permanent blank canvas, opens it with the
title selected, and saves title, elements, and viewport through the existing local or account
workspace. **Back to Bank** returns to the list; reopening a card restores that document. Title
changes save after a short pause in typing, or immediately on blur/Enter.

The existing Organize subsection formerly called Bank is now **Thought folders**, so the two surfaces
have distinct names.

## Data safety

- Existing single-canvas data projects deterministically to `canvas:legacy` / `My first canvas`.
- Projection and load do not write storage. The Bank is persisted only on a successful save.
- Every legacy element field and the legacy viewport are copied into the migrated document.
- Top-level `canvas` and `canvasViewport` remain an unchanged recovery mirror for one release.
- Repositories address one canvas id and replace only that canvas's current document.
- Existing canvas ids cannot disappear through the compatibility writer.
- Account merge unions disjoint ids, deduplicates identical content, keeps the destination account
  viewport, and stops on same-id title or element conflicts without mutating either source.
- Canvas title validation requires 1–120 trimmed characters; Bank ids and dates are validated.

## Modules

- `canvasBank.ts`: validation, legacy projection, creation, rename, and Bank ordering.
- `canvasBankMerge.ts`: pure conflict-stopping account merge.
- `canvasRepository.ts` / `useCanvasWorkspace.ts`: per-id persistence and per-canvas session undo.
- `CanvasBankView.tsx`: Bank list and creation surface.
- `Canvas.tsx`: title editing and Back to Bank behavior.
- `migration.ts`, `store.ts`, and `accountStorage.ts`: schema compatibility and guarded persistence.

## Validation

- Focused and regression suite: 405 tests across 23 files.
- TypeScript application and API checks: passed.
- Production build and full `pnpm check`: passed.
- Browser smoke: create, focused title, rename, add block, exit, focus return, reopen, and
  recovered legacy card passed at desktop size; the 390 px layout passed with no horizontal overflow.
- `git diff --check`: passed.
- Independent orchestration review checked lossless migration, guarded account merge, per-canvas
  sessions, and save behavior. After the title autosave follow-up, 405 tests, app/API typechecks,
  and the production build passed again.
- The integration check against the combined PR #70–72 code passed 412 tests across 23 files,
  app/API typechecks, and production build. The primary production URL was smoke tested after
  merge for Bank navigation, the migrated canvas card, and Review editing.

## Limitations and follow-up work

This first slice intentionally excludes archive, restore, duplicate, thumbnails, multi-select, hard
delete, storage splitting, and durable canvas revisions. Canvas records still share the existing
single localStorage key and account JSON row, so large multi-canvas workspaces need measured size
limits or storage splitting in a later task. A physical iPhone smoke test remains a release review step.
