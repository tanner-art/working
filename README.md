# Threadline

Start with [docs/NORTH_STAR.md](docs/NORTH_STAR.md). It is the product compass for this repo: preserve raw thought, build semantic structure around it, and avoid collapsing the system into a generic notes/tasks/calendar app. Use [docs/QA_CHECKLIST.md](docs/QA_CHECKLIST.md) before calling a product slice complete.

An AI-native personal thought-to-execution MVP. The product deliberately preserves raw capture and makes every later interpretation editable and reversible.

## Stack

- React + TypeScript + Vite
- Browser localStorage for the initial persisted repository
- No separate stores per screen and no UI state framework

## Architecture

`ThoughtObject` is the source of truth. It retains original content, source, creation time, contextual metadata, AI interpretation, confidence, relationships, history, and lifecycle status. Screens are projections over the same persisted state:

- Capture preserves raw thought and the recorded interpretation; later user corrections change type/status and add history.
- Review exposes uncertain interpretations for an explicit confirmation.
- Today displays confirmed actions separately from fixed commitments.
- Commitments displays time-bound reminders and commitments without mixing in flexible execution work.
- Canvas persists text nodes, groups, and directed arrows independently from semantic interpretations, so a later AI pass can infer from spatial relationships without overwriting the canvas.

The current interpreter is deterministic and isolated in `src/interpreter.ts`. A provider-backed service still needs asynchronous request handling, errors, and a defined interpretation contract.

See [implementation status](docs/IMPLEMENTATION_STATUS.md) for verified behavior, missing core features, and pending checks.

## Run

```bash
npm install
npm run dev
```

Before each push, run `pnpm check`. GitHub Actions runs the same gate on every push and pull request.

## First vertical slice

Implemented: text capture, voice-capture affordance, interpretation/confidence/review, a reusable object workbench for changing type/status/context/effort/deadline, local persistent semantic objects, Today, a separate commitments view, and an infinite-feeling pan/zoom canvas with text, groups, arrows, drag, deletion, and persistence.

Intentionally deferred: real speech recognition, external calendar sync, collaborative/remote persistence, freehand paths and resize handles, autonomous scheduling, and ROI optimization.
