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

### D-011: Initial Auth & Per-User Data Provider — Supabase Auth + Postgres

Ratified 2026-09-15 by TASK-027 (GitHub issue #37), comparing Supabase Auth + Postgres,
Clerk + hosted database, and a minimal custom auth/database path against the app's existing
Vite/Vercel, localStorage-first architecture.

**Decision.** Threadline's first hosted login and per-user data path uses Supabase Auth
(email sign-in to start) plus Supabase Postgres with Row Level Security (RLS) as the per-user
data store. Full comparison, environment variables, and data ownership model:
[AUTH_DATA_PLAN.md](AUTH_DATA_PLAN.md).

**Why.** Supabase is the only compared option giving both authentication and per-user database
isolation from a single vendor and a single set of client-safe environment variables, with row
ownership enforced by RLS at the database layer rather than by application code an agent must
get exactly right. Clerk has stronger prebuilt login UI components but leaves database
selection and per-user isolation entirely custom; a fully custom auth/database path is slowest
and highest-risk for a solo-maintained MVP.

**What this does not do.** This decision does not implement any backend code, does not select
a paid tier, and does not require migrating or deleting existing localStorage data — local-only
usage remains fully supported and is not deprecated (see AUTH_DATA_PLAN.md's data ownership
model).

**Follow-up tasks.** TASK-029 (login UI, existing), TASK-034 (user-scoped storage adapter),
TASK-035 (local-to-account migration/import), TASK-036 (sign-out/offline behavior), TASK-037
(privacy/export/delete settings). TASK-030's original combined scope is superseded by
TASK-034–037; see AUTH_DATA_PLAN.md.

### D-012: Portable Factory Registry and Central Lease Authority

Ratified by the 2026-09-24 Factory migration direction and implemented as a non-live foundation in PR #150.

**Decision.** The Factory registry boundary is backend-neutral. SQLite in WAL mode is the local migration/control-plane adapter, not a permanent architectural dependency. A future Postgres, Supabase, or other adapter must preserve the same contract and pass the same contract tests. After controlled cutover, the registry is the operational source of truth; dashboards and other views are projections and cannot own scheduling state.

Active work is represented by transactional leases. The registry centrally enforces at most one live lease per package, at most one per worker, and no more than three active parent packages globally. `ACTIVE` cannot be established by a direct status write. The feature lifecycle remains `ON DECK → READY → ACTIVE → VERIFY / REVIEW → BLOCKED → DONE`.

**Current authority boundary.** The installed runner remains the live dispatcher until a separately reviewed controlled restart. Merged registry code alone has no authority to claim work, launch processes, mutate the legacy queue, or restart services.

### D-013: Capability-Based, Provider-Neutral Factory Dispatch

Ratified by the 2026-09-24 Factory migration direction and implemented without live authority in PRs #150–152.

**Decision.** Workers are selected by capabilities, approved lanes, availability, capacity, dependencies, package priority, and readiness age (`ready_at`). Agent, provider, and model names are diagnostic metadata and cannot establish permanent roles, eligibility, or ordering. Orchestra coordinates and adjudicates and cannot claim routine implementation work.

Missing, stale, future, invalid, or unknown usage is constrained. Dispatch must preserve at least 20% Orchestra capacity. Exact provider/account-to-capacity-scope mapping and the treatment of any economy/slow class remain open owner decisions; code must not infer them from provider identity.

### D-014: Preservation and Shadow Evidence Precede Factory Cutover

Ratified by the 2026-09-24 Factory migration direction and implemented as preservation, shadow, and observation foundations in PRs #150–152.

**Decision.** Preserved worktrees and branches are evidence. Migration must not delete, reset, rebase, clean, consolidate, rename, or opportunistically refactor them. Shadow dispatch must run against a consistent projection of live state, record the assignment it would make, compare it with observable legacy behavior, and perform no launch or mutation. Unresolved provenance, reconciliation, capacity, or comparison evidence fails the gate.

Passing shadow evidence does not itself grant live authority. Cutover requires the documented acceptance evidence, independent ASSURANCE review, rollback procedure, and a separately reviewed controlled restart. An implementer cannot be the sole reviewer.

### D-015: Bounded Production Risk Precedes Speculative Expansion

Ratified by the 2026-09-24 Factory governance direction and recorded by RISK-003.

**Decision.** A known production-relevant risk with a small, bounded remediation outranks speculative platform expansion.

This ordering rule does not authorize unassigned work, broaden a package, or bypass product-owner decisions. It governs which already-bounded work should be dispatched first.

### D-016: Staged, Provider-Neutral Factory Capacity

Ratified by the product owner on 2026-09-24.

**Decision.** Percentage-observed workers are normal below 90%, caution from
90% to below 95%, checkpoint from 95% to below 98%, and hard stop at 98%.
Caution avoids substantial or uncertain parents. Checkpoint permits healthy
bounded work to reach a clean commit/push boundary and prevents another
substantial or uncertain parent from starting. Crossing 95% alone never
interrupts healthy active work. Hard stop permits only emergency recovery or a
very small bounded ASSURANCE package.

Packages carry provider-neutral size and risk classification. Provider/model
identity never substitutes for that data. Workers without provider percentage
telemetry are eligible from fresh healthy service, authentication, heartbeat,
and successful live-invocation evidence when no actual rate-limit, exhaustion,
throttling, or capacity-launch failure is present. No percentage ceiling is
inferred. Missing or stale percentage scopes remain constrained, and Orchestra
retains at least 20% in every declared percentage scope.

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

### OD-008: Factory Cutover, Archive Visibility, and Retention
When exactly does the registry replace GitHub labels and the local queue as live dispatch truth? Should preserved historical worktrees appear in the default queue or a separate archive? What retention periods apply to task events, attempt logs, failure details, evidence, and usage observations? Until approval, the installed runner remains authoritative, preserved work remains visible to reconciliation, and records are retained.

### OD-009: Factory Dashboard Write Authority
Will one owner or multiple administrators have dashboard write access, and which roles may create, reprioritize, pause, reassign, dependency-lock, or unblock packages? Until approval, dashboards remain read-only projections.

### OD-010: Factory Restart and Merge Controls
Which initial worker capabilities and lane permissions should be configured as data, and may any role besides the owner merge to main? The initial Agent A, Agent B, and Claude mapping is configuration rather than identity semantics. The existing no-agent-main-merge rule remains in force until an explicit decision changes it.

### OD-011: Factory Capacity Source Mapping
Which real provider/account window maps to each declared Orchestra percentage
scope when accounts are shared or changed? Missing, stale, future, malformed,
unknown, or unmapped percentage telemetry remains constrained.
