# Threadline implementation status

Reference: [North star](NORTH_STAR.md). Updated 2026-09-13 during the local-only overnight run.

## Verified baseline

- The latest `pnpm check` passed 37 tests and the production build. `git diff --check` passed.
- Text capture, Review, Objects, Today, Commitments, and Canvas share one persisted semantic state.
- Browser checks covered archive restoration, displaying history, adding/unlinking a dependency in a draft, and canvas text undo/redo.
- Tests cover interpretation routing, stored-data validation and failure results, parent-cycle exclusion, dependency blocking, original interpretation preservation, canvas history, and digest date selection.

Passing these checks does not prove the full north star is implemented.

## Core gaps and next work

| Area | Current evidence | Remaining behavior |
| --- | --- | --- |
| Capture | Text capture and deterministic proposal rules | Voice is a placeholder; no speech recognition or provider-backed interpretation. |
| Review | Type, status, context, deadline, parent and dependency editing | No conversational correction; dates are not resolved from natural language. |
| Project formulation | Parent links, direct child list and parent/child navigation in the editor | Browser navigation verification pending; no editable desired outcome separate from original capture. |
| Execution | Independent metadata and dependency-aware ranking | No user time/attention budget, duration model, or flexible time allocation. |
| Commitments | Separate confirmed commitment/reminder list; Today date filtering | No timed events, duration, recurrence, or distinct overdue/undated sections. Reminders and hard commitments still share this view. |
| Morning digest | Tested buckets and summary counts | Upcoming, decision, and project signals need actionable detail; no 7 AM delivery. |
| Canvas | Text, rectangular containers, arrows, pan/zoom, drag, session undo/redo | Containers do not own children. Freehand, general shapes, resize, multi-select, true nested grouping, and spatial semantic links are missing. |
| Persistence | Local browser storage, load protection and save-failure feedback | Failure screens and backup download need isolated browser testing. No backup import, cross-tab conflict handling, remote storage, or migration strategy. |
| Accessibility | Labeled filters and native controls | Drawer focus trapping/return and keyboard-only traversal need work. |

Next implementation priority: verify project navigation, then expose actionable digest sections. Preserve raw capture and recorded interpretation while adding structure.

## Verification still pending

- Save failure, retry and backup download in isolated browser storage.
- Zoom-and-pan node placement in the rendered canvas.
- Dependency save/reload and prerequisite completion end to end (current browser check was an unsaved draft; unit tests cover eligibility).
- Regression pass across the accumulated local changes, including narrow-screen layout.

## Working constraints

- Keep all work local. Do not stage, commit, or push until the user explicitly authorizes that again.
- Do not deploy, change credentials, or delete files without asking.
- Do not represent the current deterministic interpreter or canvas containers as features they do not yet implement.
