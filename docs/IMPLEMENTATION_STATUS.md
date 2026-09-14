# Threadline Implementation Status

Canonical living status, reconciled with `main` at `39c8c45` on 2026-09-14. For the original salvage analysis and its historical KEEP/MODIFY/DROP findings, see [ARCHIVE_SALVAGE_AUDIT.md](ARCHIVE_SALVAGE_AUDIT.md). Current lifecycle and priority live only in [TASKS.md](../TASKS.md).

## Current stack and delivery

- React, TypeScript, and Vite.
- A single local-first repository persisted in browser `localStorage`, with schema migration, visible load/save failures, retry, and backup export.
- `pnpm check` runs the unit suite, TypeScript check, and production build; GitHub Actions uses the same gate.
- Threadline is installable as a PWA. The current production alias is `https://working-ten-rust.vercel.app`.
- The claimed `temporary-zippy-agate-50psn81` Vercel project is connected to `tanner-art/working` and awaits the next push for its first current automatic deployment.

## Implemented on `main`

- Text capture with preserved CaptureRecord evidence, distinct Interpretation records, and separately persisted semantic objects.
- Deterministic interpretation behind a replaceable service interface, with confidence, rationale, review, supersession, and explicit confirmation/reversal controls.
- Separate commitments and CalendarEvents, including dedicated temporal confirmation evidence for fixed deadlines and scheduling.
- Today and Morning Digest surfaces with fixed-today, upcoming, recommended, needs-review, and project-signal sections.
- A responsive full month Calendar with navigation, selected-day details, scheduled events, visibly unconfirmed proposed dates, and unscheduled commitments.
- A reusable Objects workbench, explicit action eligibility, and cycle-safe dependency graph.
- A pan/zoom Canvas with text blocks, group containers, arrows, drag, deletion, persistence, session undo/redo, pointer and keyboard resizing, and text/group shape conversion.
- Mobile installation metadata, icons, and service-worker app-shell caching.

The merged baseline passes 176 tests, TypeScript, and the production build.

## Active and next work

- TASK-022 adds richer connection presentation and manipulation: line weight, dotted styling, and curved/arc routing.
- TASK-023 adds explicit sticky group membership so moving a group can move its contained blocks while preserving undo/redo and persistence.
- TASK-006 remains blocked on OD-007, the single-parent versus multi-membership containment decision. TASK-008 follows it with the complete project/object workbench experience.
- Provider-backed interpretation, closed-app Web Push delivery, and durable canvas revision persistence remain backlog items. See `TASKS.md` for their current scope.

## Current product decision on voice

Native voice capture and speech recognition are removed from the active pipeline by the user's 2026-09-14 decision. Users can use device or operating-system dictation in the text capture field. The existing voice affordance should not be treated as a promised feature; removing or relabeling that placeholder in the UI can be folded into the next appropriate product-polish task. Preserved-audio provenance rules remain relevant only if native audio capture is revived.

## Remaining architecture and product gaps

| Gap | Next decision or task |
| --- | --- |
| Project/objective containment cardinality and UI | OD-007, then TASK-006 |
| Complete search/filter/history/project workbench | TASK-008 |
| Curved and styled connection arrows | TASK-022 |
| Sticky group membership and group movement | TASK-023 |
| Provider-backed interpretation | Unscoped backlog using TASK-004 interface |
| Closed-app notifications | Unscoped backend/product decision and Web Push task |
| Durable canvas revisions across reloads | Follow-up to D-010 |
| External calendar sync and collaborative persistence | Deferred |
| Adaptive Plan, ROI optimization, autonomous scheduling | Deferred |

## Documentation boundary

`TASKS.md` is the only task lifecycle board. This file records shipped capability and material gaps; it does not maintain a second backlog. Delivery-specific limitations remain in the relevant task documents, including `docs/TASK-007_DELIVERY.md`, `docs/TASK-019_DELIVERY.md`, and `docs/MIGRATION.md`.
