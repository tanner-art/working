# Threadline QA Checklist

Use this before calling a product slice complete.

## North Star Fit

- Raw capture remains fast and does not require the user to pick a type first.
- Original thought content is preserved when classification, review, or linking changes.
- Canvas structure is not destroyed when canvas content becomes semantic structure.
- Commitments stay separate from flexible execution recommendations.
- Priority remains made of independent dimensions, not one hidden priority field.

## Product Behavior

- A newly captured thought appears somewhere reachable.
- Low-confidence captures go to Review.
- Review lets the user correct the proposed type.
- Every active object can be opened from at least one workbench surface.
- Archive hides the object without deleting the underlying data.
- Canvas nodes can be added, selected, moved, edited, connected, deleted, undone, and redone.

## Data Safety

- `pnpm check` passes.
- Local state validation rejects unknown kinds, statuses, malformed metadata, and broken canvas arrows.
- New semantic behavior has at least one focused unit test.
- Browser smoke tests avoid leaving temporary user-visible objects behind.

## Git Policy

- During the overnight run, do not commit or push until the user explicitly says to.
- Keep progress notes in `docs/OVERNIGHT_LOG.md`.
