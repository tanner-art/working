# TASK-337 Action review remediation evidence

This cumulative package reproduces the unmerged TASK-173 Action-staging implementation and repairs the four original TASK-174 findings.

1. Schedule is mounted as an in-app navigation destination and direct workspace surface; completing Review → Action takes the user to Schedule without bypassing the existing save, account, or workspace-exit paths.
2. Schedule has an accessible labelled 1–5 priority selector. Every change appends `actionPriority` evidence, and the derived staged projection is serialized locally and through `accountData`.
3. Staging/scheduling is derived only from valid Action history. Reversal or reclassification cancels the dependent CalendarEvent, removes the actionable staged projection, rejects stale scheduling, and appends a temporal reversal for a previously confirmed Action-derived event. Capture and history are retained.
4. Focused acceptance coverage is in `ActionFlow.test.tsx`, `ScheduleView.test.tsx`, and `actionStaging.test.ts`.

Focused validation run on 2026-09-27:

- `pnpm exec tsc -b --pretty false` — passed.
- `pnpm exec vitest run src/actionStaging.test.ts src/ScheduleView.test.tsx src/ActionFlow.test.tsx src/reviewResolution.test.ts src/migration.test.ts src/store.test.ts src/temporalConfirmation.test.ts --reporter=dot` — passed (7 files, 84 tests).

Limitations: no physical-phone verification was performed. The requested full `pnpm check`, build, and `check:api` are runner-owned shared-lock validation and were not run in this lane. Rollback is reverting this cumulative unmerged change.
