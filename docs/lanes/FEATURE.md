# FEATURE lane

## Lane purpose

Deliver bounded user-facing behavior and presentation while preserving product, data, accessibility, and interaction invariants.

## Approved task categories

- Frontend components and views
- UI and UX behavior
- Canvas interaction
- Responsive and mobile behavior
- User-facing product integration explicitly defined by a work package

## Refuse or escalate

- Unspecified backend or persistence design
- Authentication or authorization policy changes
- Database migrations
- Orchestration infrastructure
- Product-scope expansion or new architecture
- Destructive changes to captures, revisions, or user data

## Required inputs

- Bounded interaction and visual acceptance criteria
- Named routes/components and allowed files
- Data contract or mock boundary
- Mobile/accessibility requirements
- Dependencies and preservation constraints

## Preferred tools and workflows

- Inspect existing component and state patterns first
- Implement the smallest vertical UI slice
- Use deterministic component/unit tests for behavior
- Run browser verification for changed flows
- Verify phone-width layouts for mobile-affecting work

## Canonical files to read

- `AGENTS.md`
- `docs/NORTH_STAR.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- The assigned work package and relevant delivery documents

## Architecture invariants

- Preserve original captures and canvas revisions
- AI proposals do not silently create consequential meaning
- UI views do not become alternate sources of truth
- Account boundaries and local-data preservation remain intact

## Testing requirements

- Targeted behavior tests
- Typecheck and production build
- Full repository check when the package is complete
- Browser smoke test for changed routes
- Physical-device evidence when the acceptance criteria require real gestures

## Completion evidence

- Acceptance-criteria checklist
- Changed files and diff inspection
- Test/build output
- Browser/device observations and limitations
- Commit SHA and PR when authorized

## Common failure modes

- Editing shared application shells concurrently
- Desktop-only interactions presented as mobile-complete
- Visual polish hiding missing persistence
- Gesture conflicts between tap, hold, drag, and pinch

## Escalation conditions

- Data model or API contract is missing
- A required behavior conflicts with architecture invariants
- Real-device verification is required but unavailable
- Work crosses another active package's files

## Review checklist

- Scope and acceptance criteria match
- Accessible controls and readable states
- Mobile behavior is explicit
- Loading, empty, error, and recovery states exist where relevant
- No hidden source-of-truth or destructive behavior was introduced

## Reusable procedures

- Reproduce → isolate component/state boundary → implement → targeted test → browser verify → full check
- Record physical-device work as unverified until observed on the actual device

## Known-good examples

- A narrow page or interaction change with isolated tests and a preview URL

## Anti-patterns

- Opportunistic redesigns
- Giant `App.tsx` integration batches
- Treating screenshots as persistence evidence
- Claiming mobile completion from desktop emulation alone

## Lane-specific metrics

- Acceptance criteria passed
- Regression count
- Browser/device verification coverage
- Accessibility findings
- Review rework rate
