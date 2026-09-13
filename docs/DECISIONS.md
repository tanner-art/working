# Product and Architecture Decisions

This file records decisions that agents must not silently reinterpret.

## Accepted

### D-001: Preserve Original Expression
Raw CaptureRecords and original canvas expression must remain preserved independently of later AI interpretation.

### D-002: Semantic Flow
Capture -> Interpretation(s) -> Semantic Objects -> Relationships -> Views / Plans.

### D-003: Actions Require Commitment
AI may propose executable work, but ambiguous or unconfirmed work must not silently become an Action.

### D-004: Reminder Is Not a Core Object
A reminder is an instruction attached to another object rather than a fundamental semantic object.

### D-005: Commitments and Calendar Events Are Distinct
Commitment represents an obligation.
CalendarEvent represents something temporally scheduled.

### D-006: Adaptive Plan
The living execution system is called the Adaptive Plan.

### D-007: Canvas Expression Is Preserved
Canvas geometry and visual relationships exist independently of optional semantic interpretations.

### D-008: Scope Cannot Self-Expand
Agents may discover and propose work but may not implement work outside their assigned scope.

## Open Decisions

### OD-001: Confirmation Rules
Exactly when may an AI interpretation become a confirmed semantic object?

### OD-002: Canvas Revision Granularity
How granular should canvas history and retained revisions be?

### OD-003: Interpretation Reversal
What happens when an interpretation is reversed after downstream user edits depend on it?

### OD-004: Reminder Timing Semantics
How should reminders interact with commitments and CalendarEvents?

### OD-005: Adaptive Plan Recalculation
When should the Adaptive Plan automatically recalculate?

### OD-006: Plan Pinning
How may a user pin work so automatic recalculation cannot move it?
