# TASK-058 — Review Thought Editing and Version History

Status: REVIEW. Owner: Codex. Independent review required before merge.

## Goal

Make thought editing obvious from Organize on mobile and desktop while keeping the first
capture immutable and making later text and meaning revisions readable as one progression.

## Scope and acceptance

- Every Review card has a clearly labeled **Edit thought** action and displays its current
  reviewed text.
- The thought panel exposes separate editors for the current thought text and its organized
  meaning. Saving either appends to the existing audited correction/revision chain.
- The original capture remains unchanged and visible in a chronological version history.
- Revising a confirmed Action or Commitment continues to return it to Review under D-009.
- Controls remain usable at a 390-pixel mobile viewport and on desktop.
- Focused tests, full `pnpm check`, and `git diff --check` pass.

## Boundaries

This task reuses the existing persistence and revision model. It does not change authentication,
Canvas, Calendar, semantic architecture, confirmation rules, or merge `main`.

## Independent review request

Verify that Review editing is discoverable and usable on mobile and desktop; the initial capture
cannot be overwritten; text corrections and meaning revisions survive persistence and appear in
chronological order; consequential revisions still require reconfirmation; and unrelated product
surfaces are unchanged. Run focused tests, `pnpm check`, and `git diff --check`. Report APPROVED or
CHANGES_REQUESTED with concrete findings. Do not merge.

## Validation

- `pnpm check`: 407 tests, application TypeScript, production build, and API TypeScript passed.
- `git diff --check` passed; no lint script is configured.
- Local browser inspection showed the two editors and open version history on desktop. At a
  390×844 viewport, the 375-pixel panel stayed within the viewport; both save controls were
  290×44 pixels.
- Existing non-blocking production bundle warning remains (main chunk exceeds 500 kB).
