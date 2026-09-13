# Threadline Architecture

This document defines the intended architecture supporting [NORTH_STAR.md](NORTH_STAR.md). It is a design direction, not a claim that the current MVP implements these boundaries. Database technology, physical schemas, and service topology remain undecided.

## Sources of truth

Two complementary records answer different questions:

- Immutable CaptureRecords and preserved canvas revisions establish what the user actually expressed.
- The semantic graph establishes the system's current interpretation: objects, their meaning, and semantic relationships.

Derived summaries and views must not replace source material. Interpretations can be revised, rejected, or superseded while retaining provenance and history. Reversing an interpretation retracts or revises its derived objects and relationships without deleting captures or unrelated user-confirmed meaning. Already delivered notifications or external effects cannot be undone by changing interpretation history.

## Entity boundaries

| Concept | Responsibility |
| --- | --- |
| CaptureRecord | Immutable identity, source modality, capture time, original payload or stable reference to it, and context as captured. Voice, text, and canvas input create or reference these records. |
| Interpretation | A versioned reading of one or more captures, including source references, rationale, confidence, proposed meaning, and review state. Multiple competing or complementary interpretations may coexist. |
| ProposedAction | A proposal for executable work within an interpretation. It is not an executable semantic Action and is ineligible for work scheduling. It need not be a separate persisted entity. |
| Semantic Object | Current meaning and lifecycle state, with references to supporting CaptureRecords and interpretations. Extensible types include Idea, Action, Project, Commitment, Person, Reference, and Objective. Original content is accessed through capture references, not duplicated as an object's authoritative field. |
| Relationship | A typed link with explicit endpoint identities, scope, and provenance. Semantic links describe meaning; canvas links describe visual connections or structure. A drawn arrow does not automatically become a semantic dependency. |
| CalendarEvent | A temporal event with scheduled time and temporal context, optionally linked to a Commitment or other object. It has its own scheduling lifecycle. |
| Reminder instruction | A scheduling/notification instruction attached to a semantic object, with a trigger and delivery state. It does not introduce a Reminder semantic type or change its target's type. |
| Adaptive Plan | A revisable allocation of time and attention to eligible Actions, based on graph constraints, capacity, and prioritization inputs. Its allocations are distinct from fixed CalendarEvents. |

An Action is executable work explicitly created or confirmed by the user. An AI inference remains a ProposedAction until confirmed, regardless of confidence. An explicit create-action interaction can express confirmation; how free-form language qualifies is a product decision. The initial capture/review flow should require confirmation of AI-proposed work.

A Commitment is an obligation or promise, not a reserved time slot. For example, a promise to deliver a draft Friday can have a deadline without a CalendarEvent; a Thursday meeting about that draft is a separate event. Moving the meeting does not silently change the promise or its deadline. An event can exist without a commitment, and a commitment can reference multiple related events when appropriate.

Capture references may identify a text span, audio interval, or canvas revision and element set. One CaptureRecord can yield several interpretations or semantic objects; an object can accumulate evidence from several captures. Semantic descriptions may evolve independently of the original wording.

## Semantic flow and review

Capture → Interpretation(s) → Semantic Objects → Relationships → Views / Plans

1. Preserve the expression as a CaptureRecord before deriving meaning. Reference an existing record when reinterpreting the same expression.
2. Generate interpretations with provenance and confidence. A voice transcript is derived from preserved audio when audio is available; transcription corrections must not overwrite source evidence. If only text is available, record that limitation rather than implying audio was preserved.
3. Review uncertain or consequential meaning. Confirm, edit, reject, or defer proposals. High-confidence non-consequential organization may be automatic; inferred Actions and ambiguous commitments are not silently accepted.
4. Create or update semantic objects from accepted meaning, retaining capture and interpretation references. Acceptance is not one-to-one: one capture may produce an Idea and several separately confirmed Actions.
5. Establish semantic relationships with provenance. Inferred consequential links, such as work dependencies, remain proposals until accepted through review.
6. Project current meaning into views and calculate plans from eligible work. Unresolved proposals appear in Review rather than entering executable work queues.

These are logical boundaries, not mandatory separate services or separate transactions. Reinterpretation repeats the flow using preserved captures. Changes must identify affected derivations so reversal can withdraw them, preserve independent user edits, and invalidate dependent views or plan allocations. Conflicts with later confirmed edits return to Review rather than being silently overwritten.

## Canvas expression

Canvas is an input surface with its own preserved structure, built from:

- **CanvasElement:** text, shapes, freehand marks, containers, and other visual content with stable identities. An element may optionally reference one or more semantic objects; its visual type does not imply a semantic type.
- **Relationship:** visual connectors, containment, and grouping with explicit canvas endpoints. These remain distinct in scope from semantic graph relationships.
- **Geometry:** position, size, path points, and spatial arrangement associated with elements and connectors.

Canvas edits create new preserved revisions of expression rather than mutating historical evidence. Canvas CaptureRecords reference immutable revisions or snapshots with sufficient element, relationship, and geometry context to reconstruct what was interpreted. Undo/redo changes the active state while retaining the source revision referenced by an interpretation.

AI can use proximity, arrows, labels, containment, text, and drawings to propose meaning. It must not rewrite the source layout, turn every node into a semantic object, or promote visual proximity into a dependency without an accepted interpretation. Semantic edits do not implicitly move or relabel source canvas elements. Deliberate user canvas edits produce new expression and can prompt reinterpretation.

The revision representation and capture granularity are unresolved implementation/product choices; preserving interpretable source structure is the invariant.

## Scheduling and prioritization

First determine eligible and feasible work, then compare and allocate it:

- Action confirmation and lifecycle status determine eligibility.
- Dependencies are graph constraints governing order and readiness. Cycles or unresolved prerequisites should surface for resolution, not be hidden inside a score.
- Deadlines are temporal constraints/inputs. They may contribute to derived urgency alongside remaining effort and context. A plan should expose infeasible deadlines rather than silently relax them.
- Fixed CalendarEvents and available time, attention capacity, money, and people constrain allocation.
- Effort, attention load, strategic importance, resource cost, and optional ROI remain independent estimates. Unknown values remain unknown rather than implying zero cost or importance.
- Urgency is distinct from those estimates; preserve enough explanation to show why a recommendation changed. No single scoring formula is prescribed yet.

The Adaptive Plan recalculates flexible work allocations as these inputs change. It does not reschedule fixed events, alter commitments, or turn proposals into Actions. Reminder instructions control notification timing; they are neither work allocations nor deadline fields. A reminder about an Idea leaves it an Idea.

## Current implementation and future alignment

The current React/TypeScript/Vite MVP stores `ThoughtObject` and canvas state in browser localStorage. `ThoughtObject` combines original content and interpretation, includes `reminder` as a kind, and uses confidence to confirm objects. It does not yet enforce the boundaries above.

Future implementation should separate capture provenance from semantic meaning, add reversible interpretation acceptance, replace reminder objects with attached instructions, distinguish commitments from events, and preserve canvas revisions. Existing reminder data requires interpretation or review before conversion; it must not be blindly retyped as Actions or Commitments. Migration must preserve existing source content and clearly identify any historical evidence that the MVP never recorded.

Persistence must support stable references, preserved source revisions, and consistent updates to accepted meaning and its derivations. These requirements do not select a database, graph database, backend, or framework. This documentation change does not migrate data or modify application behavior.

## Open product decisions

- Which explicit language or interaction counts as confirmation of an Action or Commitment, and which non-consequential interpretations may be accepted automatically?
- What canvas revision granularity balances recoverable expression with capture volume, and what retention/deletion controls should apply to captures, especially voice recordings?
- How should Review present competing interpretations, partial acceptance, and reversal when later user edits depend on earlier meaning?
- What reminder triggers, recurrence, delivery channels, and timezone behavior belong in the first slice? How should a standalone “remind me” request obtain a semantic target without inventing work?
- What calendar semantics are needed for all-day events, recurrence, availability, and externally changed events? Which deadlines are hard constraints versus negotiable targets?
- When should the Adaptive Plan recalculate, which allocations can users pin, and how should infeasible plans and priority tradeoffs be presented? Autonomous scheduling remains outside the initial slice.
