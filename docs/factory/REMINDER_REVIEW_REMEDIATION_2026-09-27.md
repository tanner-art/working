# Reminder Review remediation — 2026-09-27

Scope: TASK-343 / issue #301 restores the unmerged TASK-175 reminder implementation on the canonical baseline and repairs the independent Review reachability finding.

- Finding: the original persistence/workflow implementation was not reachable from the mounted Review choice. Repair: `ReviewResolutionControl` consumes the registered Reminder continuation's `needs-input` handoff and mounts `ReminderResolution`; `App.tsx` supplies only bounded state composition.
- Finding: active instructions had no real user-facing projection or delivery limitation. Repair: `ReminderProjections` renders Specific and Daily log projections from persisted state, with in-app-only fallback text and explicit Handled/Dismiss actions.
- Evidence: `ReminderFlow.test.tsx` covers the registered Review handoff and accessible modes; `reminderWorkflow.test.ts` and `reminderProjection.test.ts` cover both modes, reload, due/daily separation, lifecycle retention, and no delivery promise; `migration.test.ts` validates audit reconstruction and rejects forged history. Existing Action and Review tests remain in the focused run.

Residual limitation: browser/system notification delivery is not implemented or claimed; reminders are intentionally visible only in-app. Account persistence uses the same serialized model boundary but no live account service was accessed.

Rollback: revert this bounded TASK-343 change set; it is additive to schema-v2 reconciliation and leaves historical capture/audit evidence untouched.
