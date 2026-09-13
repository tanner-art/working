# Overnight Progress Log

This file tracks autonomous Threadline progress between Git checkpoints.

## 2026-09-13

- Saved the product north star in `docs/NORTH_STAR.md` and linked it from the README.
- Added a recent-object workbench on Today so captures are not hidden behind the recommended focus card.
- Hardened local state validation for semantic objects and canvas elements.
- Added canvas-to-object capture so visual thinking can enter Review without overwriting the canvas.
- Exposed independent planning dimensions: urgency, effort, attention load, strategic importance, resource cost, and optional ROI.
- Added a unified `pnpm check` command and made CI use it.
- Added direct object-type correction in Review.
- Switched overnight strategy to fewer Git checkpoints to avoid repeated host permission prompts.
- Added a dedicated Objects view with search and type filtering so all active semantic objects are reachable.
- User changed checkpoint strategy: do not commit or push again until explicitly told. Keep overnight work as local file changes and verify with `pnpm check`.
- Added tested canvas history helpers and wired canvas undo/redo into add, connect, delete, and drag operations.
- Added parent project/objective linking from the object drawer using `belongs_to` relationships.
- Added a tested Morning Digest model and a compact Today digest strip that keeps fixed commitments, upcoming items, execution picks, review decisions, and project signals separate.
- Fixed Morning Digest date matching to use the local calendar day instead of UTC.
- Added `docs/QA_CHECKLIST.md` and linked it from the README as a standing bug-prevention checklist.
- Added canvas keyboard shortcuts for undo and redo while avoiding text input fields.
- Made parent project/objective relationships visible in object rows with a tested parent lookup helper.
- Fixed object drawer history handling so archive, complete, and parent-link edits create one clear audit event.
- Improved deterministic interpretation for clustered captures and ambiguous timed conversations, keeping both in Review rather than making hard commitments.
- Added Active / Archived / All filters to Objects so archived thoughts can be found and restored through the status editor. Added accessible labels to search and filters. Existing 26 tests and production build passed.
- Browser verified archive recovery using the existing "Overnight review type smoke test" fixture: found it in Archived, restored it to confirmed, verified it appeared in Active, then returned it to archived. The running tab needed a reload to display the latest changes.
- Parent choices now exclude self, descendants (including paths through archived projects), and existing circular ancestry. Added two regression tests. Existing unavailable parent links remain visible and can be cleared even when no valid parents exist.
- Storage reads now distinguish first use from unreadable saved data. The app pauses editing on failed loads rather than replacing stored thoughts with starter content. Failed saves show retry and JSON backup controls while retaining current work in memory. Added storage failure/retry regression tests; 30 tests and production build pass. Failure UI and backup download still need browser verification with isolated test storage.
- Today now lists only commitments matching today's local date. Edited deadlines take precedence over original suggested dates; upcoming commitments sort by nearest valid date before taking three. Invalid/unresolved dates are excluded from dated digest buckets. Replaced the invented available-hours calculation with the actual confirmed-action count and a clear note that available hours are not configured. Two new regression tests; all 32 tests and production build pass.
- Added an expandable History section to the object editor, showing recorded events newest first with local timestamps. Browser verified an existing canvas thought displayed its capture and confirmation events; closed without editing. All 32 tests and build pass.
- Added dependency editing using existing depends_on relationships. Recommendations exclude actions with unfinished, archived, or missing prerequisites; completion makes them eligible again. Candidate choices prevent self, duplicate, and circular links. Unlinking remains possible for missing targets, and dependency edits appear in history. All 34 tests and build pass; dependency editor browser smoke test remains pending.
- Browser verified adding and unlinking a prerequisite in an unsaved draft, with the waiting message appearing and clearing correctly; closed without saving. Today now distinguishes ready actions from blocked actions, offers a working prerequisite-review button when all actions are blocked, and a working capture button when no action exists. Unspecified effort/attention no longer display invented values. All 34 tests and build pass.
- Canvas text editing now records one undo step when leaving a text field. Browser verified edit, undo, redo, then undo again to restore the original placeholder. Fixed new-node positioning to account for both zoom and pan (visual placement verification pending). All 34 tests and build pass.
- Interpretation now routes tentative, conditional, negative, cancellation, and questioned wording to Review; explicit reminder requests stay reminder proposals pending timing review. Numeric dates no longer look like slash-separated project clusters. Three regression tests added; 37 tests and build pass. This remains a conservative deterministic interpreter, not a connected language model or comprehensive natural-language parser.
- Confirming and reclassifying thoughts now preserve the recorded interpretation and confidence. User decisions change kind/status/history rather than rewriting the original proposal. The editor labels these as recorded values and displays the suggested type. Existing records altered by earlier code cannot have their original confidence reconstructed. Strengthened provenance tests; all 37 tests and build pass.
- Projects and objectives now show direct linked thoughts, their types/statuses and completion counts. Child editors offer navigation back to their active parent. Navigation is disabled while the editor has unsaved changes, so opening a related thought does not silently discard the draft. Direct-child filtering has regression coverage; 38 tests and build pass. Browser navigation verification remains pending.
