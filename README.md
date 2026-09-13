# Threadline

Start with [docs/NORTH_STAR.md](docs/NORTH_STAR.md). It is the product compass for this repo: preserve raw thought, build semantic structure around it, and avoid collapsing the system into a generic notes/tasks/calendar app. See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for what is currently implemented, known architecture mismatches, and tracked follow-up work, and [docs/QA_CHECKLIST.md](docs/QA_CHECKLIST.md) before calling a product slice complete.

An AI-native personal thought-to-execution MVP. The product deliberately preserves raw capture and makes every later interpretation editable and reversible.

## Stack

- React + TypeScript + Vite
- Browser localStorage for the initial persisted repository
- No separate stores per screen and no UI state framework

## Architecture

The intended architecture is defined in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): immutable CaptureRecords preserve user expression, reversible interpretations build the semantic graph, and views and Adaptive Plans project current meaning. Actions require user confirmation; reminders are attached notification instructions; Commitments and CalendarEvents are distinct.

The current MVP predates these boundaries. Its `ThoughtObject` combines original content, source, creation time, contextual metadata, AI interpretation, confidence, relationships, history, and lifecycle status. Screens use the same persisted state:

- Capture stores original content and an interpretation together in a `ThoughtObject`; separate immutable CaptureRecords are not yet implemented.
- Review exposes uncertain interpretations for an explicit confirmation.
- Today displays confirmed actions separately from fixed commitments.
- Commitments displays time-bound reminders and commitments without mixing in flexible execution work.
- Canvas persists text nodes, groups, and directed arrows independently from semantic interpretations, so a later AI pass can infer from spatial relationships without overwriting the canvas.

The current interpreter is deterministic and isolated in `src/interpreter.ts`. Implementing the intended architecture will require changes to the domain model and acceptance flow, including replacing confidence-based Action confirmation with explicit user confirmation. No application changes or data migrations are included in this documentation update.

## Run

```bash
npm install
npm run dev
```

Before each push, run `pnpm check`. GitHub Actions runs the same gate on every push and pull request.

## First vertical slice

Implemented: text capture, voice-capture affordance, interpretation/confidence/review, a reusable object workbench for changing type/status/context/effort/deadline, local persistent semantic objects, Today, a separate commitments view, and an infinite-feeling pan/zoom canvas with text, groups, arrows, drag, deletion, and persistence.

Intentionally deferred: real speech recognition, external calendar sync, collaborative/remote persistence, freehand paths and resize handles, autonomous scheduling, and ROI optimization.
