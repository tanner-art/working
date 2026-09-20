# Threadline Product Development Brief

Threadline is one connected personal thinking system. Capture, Review, Organize, Calendar and
Canvas are interfaces over shared information rather than isolated stores. A capture may become
a revised thought, canvas node, commitment, document or development task while retaining its
source and history.

## Product loop

**Capture → Understand → Organize → Act → Reflect**

- **Capture:** fast text and, later, preserved voice input.
- **Review:** inspect, revise, correct and accept proposed meaning.
- **Organize:** folders, capture history, documents and universal search.
- **Calendar:** practical daily and weekly planning over shared commitments and events.
- **Canvas:** persistent visual spaces that can reference and create captures.

The same stable identities, provenance links and user ownership rules must survive movement
between these interfaces. Derived content never deletes or replaces its source.

## Immediate product outcomes

1. Thoughts in Review can be edited without erasing their original capture. “Revise” creates a
   new version; “Correct original” records a source correction with an audit trail.
2. Canvas opens to a bank of persistent canvases. An editor restores title, content, geometry
   and viewport, autosaves meaningful changes, and returns to the bank on exit.
3. Mobile canvas interaction uses an explicit gesture state machine for selection, long-press
   editing, hold-and-drag movement, pinch zoom and two-finger pan. The viewport is effectively
   unbounded and offers Fit to Content and Reset View.
4. Calendar provides mobile day and week views with direct creation, editing, rescheduling and
   completion through the shared commitment/event model. The day timeline remains distinct
   from Morning Digest.

## Connected-information outcomes

- Documents provide a persistent title/body destination for connected captures. Documents link
  to every source capture, support editing without rewriting those sources, and can be opened
  directly from Review, Organize and search.
- Capture, interpretation, revision, semantic object, calendar item, canvas node and document
  references use stable identities and explicit provenance.
- Organize retains a chronological capture log after review and searches original/revised text,
  canvas content, dates, commitments, documents and topics.
- AI may propose related-capture groups or document merges using semantic similarity, time
  proximity and authorized context. The user confirms; sources remain independently accessible.
- Bulk Review operations support assignment, archive/delete with recovery, merge, canvas copy or
  move, and mark-reviewed behavior with confirmation for destructive actions.
- A canvas block can become a capture without changing the block. The capture records the source
  canvas and node identities so users can return to the visual context.

## Later outcomes

- Preserved voice audio, transcripts, extracted ideas and commitments with shared source links.
- Organic canvas branches, freehand strokes and reversible shape recognition.
- Connection anchors and curve geometry independent of node geometry.
- Canvas presentation frames with fixed and follow-content modes.
- Dismissible morning orientation, evening Review and weekly reflection rituals.
- Private personal statistics based only on real user data. Cross-user comparisons require
  explicit privacy design and meaningful anonymized populations.

## Delivery phases

1. **Repair existing experience:** Review revisions/corrections, canvas persistence, navigation,
   zoom, gestures and toolbar space.
2. **Calendar and Canvas Bank:** day/week calendar, direct commitment editing, persistent Canvas
   Bank and focused editor.
3. **Connected information:** shared identifiers, provenance, revisions, capture history and
   universal search.
4. **AI organization:** related-capture suggestions, documents, contextual classification and
   later voice analysis.
5. **Advanced visual thinking:** organic branches, pen recognition, advanced connections, lasso
   and presentation frames.
6. **Personal intelligence:** rituals, statistics and optional user-selected external sources.

Each phase must ship through focused modules with narrow typed contracts. Data, domain rules,
provider calls and presentation remain separate where the boundary is meaningful. Work should
extend an existing owner module before creating another source of truth.
