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

### D-009: Confirmation Rules for Semantic Objects and Actions

Resolves OD-001. Ratified 2026-09-13 by TASK-009, evaluating (but not adopting wholesale) the archived `wip/pre-orchestration` Review "Confirm interpretation" flow (docs/ARCHIVE_SALVAGE_AUDIT.md item 4) as one candidate.

**General principle.** Automatic acceptance is permitted only for low-consequence, reversible organizational meaning. Any transition that makes an item eligible for execution, scheduling, or notification delivery — a consequential transition — requires exactly one explicit, discrete, user-initiated confirmation interaction targeted at that specific item. Confirmation is never inferred from confidence score, elapsed time, a default value, or a batch/bulk operation that did not specifically target the item.

**Definition: explicit confirmation interaction.** A UI or conversational interaction whose evident, singular purpose is to affirm a specific proposed interpretation or transition — e.g., a dedicated "Confirm" control on a specific interpretation, an affirmative reply ("Yes", "Confirmed", "That's right") in a conversational review turn, or the user directly authoring a field's value themselves (typing or selecting it with intent). A value that was merely pre-filled, defaulted, or left untouched by the user does not count, even if it is technically "present" in a saved record.

**Case-by-case rules:**

1. **Low-consequence interpretations** (e.g., Idea, Reference, informational context/tags with no execution or obligation implied) MAY be organized automatically at any confidence level. This is auto-filing, not "confirmation" in the OD-001 sense — it carries no obligation and remains cheaply reversible.

2. **Uncertain interpretations** (low confidence, or flagged as conditional/ambiguous/a question — per the confidence-capping heuristics already in `src/interpreter.ts`) MUST enter Review and MUST NOT auto-advance out of Review by any means other than an explicit confirmation interaction. No timeout, default, or unrelated edit may move them out of Review.

3. **Consequential state transitions** — specifically: (a) ProposedAction → Action, (b) creation or edit of a Commitment's obligation or of a deadline treated as fixed, (c) any transition that grants Adaptive Plan / execution-queue / notification-delivery eligibility — always require an explicit confirmation interaction, regardless of the interpretation's confidence.

4. **ProposedAction → Action** specifically requires a discrete confirmation interaction distinct from merely selecting "Action" as a type. Choosing a kind is a classification edit, not confirmation. The archived Review "Confirm interpretation" button qualifies as this discrete interaction when it is the dedicated gesture the user pressed — but a general-purpose object editor's Status dropdown, used to flip status to "confirmed" as one field among many during an unrelated edit, does NOT qualify and must not grant Action eligibility on its own. (The archived implementation allowed exactly this second path; it does not satisfy this rule and must not be carried forward as-is.)

5. **Hard Commitments** require their own explicit confirmation for the obligation itself, separate from confirming any date/time as fixed. Confirming that a commitment exists does not by itself fix a deadline or schedule a CalendarEvent; scheduling that event is a separate confirmed action. This mirrors the Commitment/CalendarEvent distinction in D-005.

6. **User corrections and reclassification.** A user directly typing or selecting a field's new value is itself an explicit act and satisfies confirmation for that specific field. It does not, however, retroactively confirm other consequential fields on the same object — e.g., reclassifying an Idea to Action still requires the discrete Action-confirmation interaction from rule 4; touching the record for an unrelated reason grants no free pass.

7. **Explicit confirmation vs. inferred intent.** Every consequential transition must be traceable in the object's history to one specific, timestamped user gesture and the specific transition it authorized (e.g., "Confirmed as Action" is a valid history entry; "status changed" from a generic multi-field save is not sufficient evidence of confirmation for a consequential transition).

**Reversibility.** Confirmation does not lock the object. Reversing a confirmed Action or Commitment back toward ProposedAction/Review must remain possible, must preserve the CaptureRecord and full Interpretation/history (D-001), and must not delete or silently overwrite other confirmed, unrelated meaning. Already-delivered notifications or other external effects of a confirmed Action are not retroactively undone by a later reversal.

**Verdict on the archived candidate.** The archived Review "Confirm interpretation" button is an acceptable instance of the rule-4 confirmation gesture for that entry point, but it is not sufficient as the sole gate: the same archived app also let the generic object-editor Status dropdown set status to "confirmed" outside Review. TASK-003 must ensure only a dedicated confirmation gesture can grant Action/Commitment eligibility from any surface, not only from Review.

### D-010: Canvas Revision Persistence Policy (Session Undo Now, Durable Revisions Later)

Resolves OD-002. Ratified 2026-09-13 by TASK-010.

**Scope of this decision.** This decision governs only the *editing-history* undo/redo stack wired in TASK-010 (src/canvasHistory.ts). It does not implement, and must not be read as implementing, durable canvas revision storage referenced by CaptureRecords (docs/ARCHITECTURE.md's "Canvas edits create new preserved revisions of expression").

**What ships now.**
- The canvas continues to persist exactly as it does today: `AppState.canvas` (a flat `CanvasElement[]`) is saved via `saveState`/localStorage as the single current canvas state. No new persisted schema is introduced.
- Undo/redo is a bounded, in-memory stack of full `CanvasElement[]` snapshots (`src/canvasHistory.ts`), scoped to one browser session. It is not written to localStorage and does not survive a reload; reloading starts with an empty undo stack against whatever canvas state was last saved.
- Each undo step is one atomic user edit (an add, a connect, a delete, one completed drag, or one committed text edit), not a fine-grained log of every pointer-move or keystroke.

**What this explicitly is not.** This is not the durable, provenance-preserving canvas revision mechanism ARCHITECTURE.md describes for CaptureRecords ("Canvas edits create new preserved revisions of expression rather than mutating historical evidence... Undo/redo changes the active state while retaining the source revision referenced by an interpretation"). Session undo/redo lets a user reverse their own recent in-session edits; it gives no guarantee that a canvas state referenced by an existing capture/interpretation remains reconstructable after reload, after the undo stack is cleared, or after this session ends.

**Durable revision granularity (resolves the OD-002 granularity question).** A durable canvas revision is created when a user explicitly captures canvas content for semantic interpretation (i.e., the existing "Capture node" action, or its future equivalents). A capture references an immutable snapshot of the full canvas plus the set of selected element IDs at that instant — not a single element in isolation, since arrows and spatial layout carry meaning per D-007. Ordinary edits between captures (adds, moves, connects, deletes, text edits) persist only as current canvas state (`AppState.canvas`) and as session undo/redo steps per this decision; they do not themselves create a durable revision. A future explicit manual "snapshot" feature may add further user-triggered revisions; autosaving a revision on every keystroke or pointer move is explicitly not part of this policy — that would defeat the "one atomic user edit per undo step" granularity above and create far more revisions than any interpretation needs to reference.

**Required properties of any future durable-revision implementation, whenever it lands:**
1. Durable canvas revisions must be immutable snapshots, referenced by canvas CaptureRecords/interpretations by stable identity — not the mutable session undo/redo stack this decision describes.
2. Durable revisions must be retained independently of the bounded, session-only undo/redo stack: clearing or exhausting the undo stack (bounded per D-010's implementation) must never delete a revision a capture depends on.
3. Implementing durable revision storage requires TASK-002 (CaptureRecord/Interpretation split) to land first, since canvas CaptureRecords need the entity boundaries TASK-002 introduces to reference revisions correctly (per docs/ARCHITECTURE.md's entity table). Durable implementation remains deferred until TASK-002 is integrated; this decision fixes the granularity above but does not implement it.

**Non-goal for TASK-010.** TASK-010 does not implement durable revision storage, does not add a revision table/schema, and does not claim canvas history survives anything beyond the current browser session.

## Open Decisions

### OD-003: Interpretation Reversal
What happens when an interpretation is reversed after downstream user edits depend on it?

### OD-004: Reminder Timing Semantics
How should reminders interact with commitments and CalendarEvents?

### OD-005: Adaptive Plan Recalculation
When should the Adaptive Plan automatically recalculate?

### OD-006: Plan Pinning
How may a user pin work so automatic recalculation cannot move it?

### OD-007: Semantic Object Membership Cardinality
May a semantic object belong to multiple projects or contexts, or only one parent? Raised by the `wip/pre-orchestration` salvage audit (docs/ARCHIVE_SALVAGE_AUDIT.md), which found a single-parent `belongs_to` relationship modeled without this being a ratified decision. This gates how the Relationship model's project-containment shape is implemented.
