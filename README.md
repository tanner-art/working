# Threadline

An AI-native personal thought-to-execution MVP. The product deliberately preserves raw capture and makes every later interpretation editable and reversible.

## Stack

- React + TypeScript + Vite
- Browser localStorage for the initial persisted repository
- No separate stores per screen and no UI state framework

## Architecture

`ThoughtObject` is the source of truth. It retains original content, source, creation time, contextual metadata, AI interpretation, confidence, relationships, history, and lifecycle status. Screens are projections over the same persisted state:

- Capture creates an immutable raw thought plus a replaceable interpretation.
- Review exposes uncertain interpretations for an explicit confirmation.
- Today displays confirmed actions separately from fixed commitments.
- Commitments displays time-bound reminders and commitments without mixing in flexible execution work.
- Canvas persists text nodes, groups, and directed arrows independently from semantic interpretations, so a later AI pass can infer from spatial relationships without overwriting the canvas.

The current interpreter is deterministic and isolated in `src/interpreter.ts`; replacing it with a provider-backed service will not require changing the UI or object model.

## Run

```bash
npm install
npm run dev
```

Before each push, run `pnpm test` and `pnpm run build`. GitHub Actions runs the same checks on every push and pull request.

## First vertical slice

Implemented: text capture, voice-capture affordance, interpretation/confidence/review, a reusable object workbench for changing type/status/context/effort/deadline, local persistent semantic objects, Today, a separate commitments view, and an infinite-feeling pan/zoom canvas with text, groups, arrows, drag, deletion, and persistence.

Intentionally deferred: real speech recognition, external calendar sync, collaborative/remote persistence, freehand paths and resize handles, autonomous scheduling, and ROI optimization.
