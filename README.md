# Threadline

Start with [docs/NORTH_STAR.md](docs/NORTH_STAR.md). It is the product compass for this repo: preserve raw thought, build semantic structure around it, and avoid collapsing the system into a generic notes/tasks/calendar app. See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for what is currently implemented, known architecture mismatches, and tracked follow-up work, and [docs/QA_CHECKLIST.md](docs/QA_CHECKLIST.md) before calling a product slice complete.

An AI-native personal thought-to-execution MVP. The product deliberately preserves raw capture and makes every later interpretation editable and reversible.

## Stack

- React + TypeScript + Vite
- Browser localStorage for the initial persisted repository
- No separate stores per screen and no UI state framework

## Architecture

The intended architecture is defined in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): immutable CaptureRecords preserve user expression, reversible interpretations build the semantic graph, and views and Adaptive Plans project current meaning. Actions require user confirmation; reminders are attached notification instructions; Commitments and CalendarEvents are distinct.

The current MVP implements these core boundaries: CaptureRecords preserve original expression, Interpretations retain confidence and rationale, semantic objects are persisted separately, and commitments remain distinct from CalendarEvents. Consequential action and scheduling transitions require explicit confirmation and preserve reversible evidence. The current interpreter remains deterministic behind a replaceable service interface.

## Run

```bash
npm install
npm run dev
```

Before each push, run `pnpm check`. GitHub Actions runs the same gate on every push and pull request.

## First vertical slice

Implemented: text capture, interpretation/confidence/review, explicit confirmation, a reusable object workbench, local persistent semantic objects, Today and Morning Digest, separate commitments and Calendar views, installable PWA support, and a pan/zoom canvas with text blocks, group containers, arrows, drag, resizing, shape conversion, deletion, persistence, and session undo/redo.

Current pipeline: richer connection styling/routing and sticky group membership. Native voice capture is removed from the active pipeline because users can use device dictation. External calendar sync, collaborative/remote persistence, autonomous scheduling, and ROI optimization remain deferred.
