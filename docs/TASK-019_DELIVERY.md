# TASK-019 delivery and independent review

Status: REVIEW; uncommitted at the user's request. Independent orchestration review and browser validation remain pending.

## Implemented contract

D-005 and D-009 remain separate gates: confirming meaning does not confirm timing; confirming timing does not create an Action or establish an obligation. Reversing an obligation excludes its deadline from the digest's confirmed-object bucket, but preserves separately confirmed events and their evidence. Reversing event scheduling does not reverse an obligation or its deadline. No delivery backend, recurrence, autonomous scheduling, all-day semantics, duration or overlap semantics were added.

The schema-v2 model has an optional `temporalHistory` journal. Absence means no temporal confirmation; old schema-v2 data remains readable without synthesizing evidence. Existing legacy migration remains conservative. Older application versions reject the new field rather than silently dropping its history. The journal does not promote `metadata.deadline` into canonical authority: confirmed deadlines are derived from validated journal evidence when constructing the digest.

Each decision records a unique identity, offset-bearing timestamp, dedicated Review gesture source, confirmation/reversal transition and exact target snapshot:

- A fixed deadline binds an object identity, interpretation identity and valid calendar date. The date must be that interpretation's recorded deadline proposal (edited metadata takes precedence over the interpreter's suggested date).
- Event scheduling binds the event identity, interpretation identity, explicit start instant, recorded temporal context, title, linked object identities and source captures. Review requires exactly one current supporting interpretation for the event's captures. It never infers an event from a deadline or assumes an event's scheduled status is user confirmation.
- A reversal names and repeats the precise active confirmation it withdraws. Duplicate identities/active confirmations, invalid timestamps, unknown sources/transitions, mismatched targets and orphan/retargeted reversals fail validation.

The compatibility state carries pending journal additions separately, allowing immediate live digest updates and retry after a failed save. Reconciliation enforces the saved journal prefix; existing store session baselines protect saved history and reject stale concurrent saves. Captures and interpretation versions remain unchanged by temporal gestures. A date edit invalidates prior deadline eligibility even if that old date is later restored; Review offers reversal of the earlier evidence before a new confirmation. Unrelated edits preserve timing. Historical facts remain inspectable in the persisted journal.

This is validated, auditable local application evidence, consistent with TASK-003's trust boundary. It cannot cryptographically establish that a human clicked a button if someone rewrites an entire internally consistent localStorage document.

## Review and digest

Review has separate item-level Confirm fixed deadline / Reverse fixed deadline and Confirm event scheduling / Reverse event scheduling buttons, with the proposed fact, interpretation, raw capture and confirmation timestamp. Confirmed objects remain accessible in timing Review after leaving interpretation Review. Previously confirmed facts whose proposals are no longer supported can still be reversed.

The Morning Digest enables only fully validated temporal facts:

- Up to three confirmed events on the device-local day, ordered by start instant, with independently confirmed linked obligations.
- Up to three fixed deadlines on currently confirmed objects, earliest date first, including overdue dates. Date-only deadlines stay date-only; there is no invented midnight event or urgency window.
- Obligations without separately verified scheduled events remain in the existing schedule-unverified bucket. Other digest buckets and delivery consent are unchanged.

## Files changed

- `src/domain.ts`, `src/migration.ts`: evidence types, optional persisted journal and append-only reconciliation/validation.
- `src/temporalConfirmation.ts`, `src/temporalConfirmation.test.ts`: proposals, exact-target confirmation/reversal, eligibility and regression coverage.
- `src/TemporalReview.tsx`, `src/App.tsx`: dedicated timing Review controls.
- `src/morningDigest.ts`, `src/DigestPanel.tsx`: validated temporal buckets and honest display labels.
- `TASKS.md`, `docs/TASK-007_DELIVERY.md`, `docs/TASK-019_DELIVERY.md`: lifecycle, baseline cross-reference and delivery/review notes.

## Validation

- `pnpm check`: 148 tests passed; TypeScript and production Vite build passed. No lint script is configured.
- `git diff --check`: passed; tracked diff and new files inspected.
- All 12 temporal tests also passed under `TZ=America/Los_Angeles` and `TZ=Asia/Tokyo`.
- Focused tests cover Action/Commitment isolation, independent scheduling, reversal/reconfirmation, preserved captures/interpretations, edited dates, malformed/forged evidence, exact target/start/context/link mismatches, corrupt storage, protected save history, concurrent saves, quota retry, reload, local-day matching and cancelled events.
- Initial install encountered registry DNS failure. `pnpm install --offline --frozen-lockfile` using the existing `/private/tmp/threadline-task011-pnpm-store` cache succeeded. No package or lockfile change; no other worktree accessed.
- Browser attempt blocked: `pnpm dev --host 127.0.0.1 --port 5179` failed with `listen EPERM`. `agent-browser` was absent from PATH; the existing temporary cached binary was also attempted with a task-specific socket directory, but its daemon exited during startup. No successful browser validation is claimed.

Independent browser checklist (still required):

1. At mobile width, capture a proposed Action/Commitment with a date, confirm its interpretation and verify that no fixed deadline appears in the digest until the separate timing button is pressed.
2. Confirm the deadline, inspect the timestamp, view the digest, reload, reverse it and reload again. Confirm that obligation/Action status and original capture are unchanged by both timing gestures.
3. Edit the proposed deadline through Adjust details; verify the old date loses eligibility, reverse its evidence and explicitly confirm the new date.
4. With a canonical existing CalendarEvent fixture that has an explicit offset-bearing start, nonempty temporal context and supporting capture/interpretation, confirm scheduling and verify the correct local-day digest entry. Reverse it and verify the linked obligation remains confirmed. A standalone event must not create an obligation.
5. Inspect keyboard access, readable timing/source labels, browser errors, save-failure retry and reload behavior. Confirm no notification permission request occurs.

## Limitations and proposed follow-ups

These do not expand the implementation assignment:

- Independent browser validation and orchestration review are outstanding validation gates, not an approval to merge.
- CalendarEvent creation/rescheduling UI remains unavailable. Existing valid events can be confirmed; events with missing/ambiguous source interpretation remain ineligible. A future canonical event authoring task should explicitly record proposed revisions before supporting rescheduling. Current validation rejects changing an event snapshot that already has journal evidence, including reversed history, rather than rewriting that history.
- The current temporal context is recorded text, not a newly defined IANA timezone policy. Event instants match the device-local digest day. Recurrence, all-day events and duration/overlap need separately assigned semantics.
- Full timing-history browsing, unsupported-proposal repair and broader canonical UI reintegration belong in a follow-up/TASK-008. The persisted history is retained now; the minimal Review surface shows active evidence and reversal controls.
- TASK-007's closed-app push/backend decision remains unresolved and is unaffected.

No commit, push, reset, rebase, clean, merge, branch change or other-worktree access was performed.
