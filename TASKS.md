# Threadline Task Board

## Task Lifecycle

BACKLOG -> READY -> IN_PROGRESS -> REVIEW -> MERGE_READY -> DONE

Only READY tasks may be newly assigned. Each task has one implementation owner, explicit scope, a commit, and independent review before merge. Product decisions belong in `docs/DECISIONS.md`; architecture changes require explicit assignment.

## IN_PROGRESS

Canvas connection styling and sticky group membership are active as TASK-022 and TASK-023. Their implementation branches own the detailed task entries so parallel work does not create duplicate or conflicting board records.

## READY

None.

## BACKLOG

### TASK-006 - Project and Child-Item Linking

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M2

Depends On: OD-007 (containment cardinality must be ratified)

Goal: Add cycle-safe project/objective containment using the upgraded Relationship model, including parent selection, child lists, and navigation appropriate to OD-007.

Acceptance: relationship provenance is preserved, cycles are rejected, and `pnpm check` passes.

### TASK-008 - Full Objects Workbench

Status: BACKLOG
Owner: Unassigned
Reviewer: Unassigned
Priority: P1
Milestone: M3

Depends On: TASK-006

Goal: Reintegrate search/filter, dependency editing, project organization, history, and clear blocked-versus-ready states onto the current entity model.

Acceptance: every workbench surface is reachable and functional without bypassing explicit confirmation rules, and `pnpm check` passes.

### Unscoped product backlog

- Provider-backed interpretation behind the TASK-004 service interface.
- Closed-app Morning Digest and reminder delivery through Web Push; the required backend, user/device identity, subscription storage, scheduled execution, and sender credentials still need a product and hosting decision.
- Durable canvas revision persistence and retention controls described by D-010.
- External calendar sync, collaborative/remote persistence, Adaptive Plan recalculation, ROI optimization, and autonomous scheduling.
- Voice capture is removed from the active pipeline by the user's 2026-09-14 decision. Device/OS dictation covers the immediate need; native audio capture and transcription may be reconsidered later, but no voice task should be assigned now.

## REVIEW

None.

## MERGE_READY

None.

## DONE

| Task | Delivered result | Evidence |
| --- | --- | --- |
| TASK-001 | Audited the implementation against the architecture and created the salvage plan. | `17f3d29` |
| TASK-002 | Split capture, interpretation, semantic-object, commitment, and CalendarEvent persistence with migration coverage. | PR #9, `677b28f` |
| TASK-003 | Required explicit, traceable confirmation and reversal for consequential action transitions. | PR #13, `b12f677` |
| TASK-004 | Put deterministic interpretation behind a replaceable service interface. | PR #17, `cf4fc32` |
| TASK-005 | Added cycle-safe dependency relationships and dependency-aware action eligibility. | PR #18, `99508a1` |
| TASK-007 | Rebuilt the Morning Digest on the current entities and added in-app delivery behavior. | PR #16, `7002a1d` |
| TASK-009 | Ratified explicit confirmation rules as D-009. | `22580a0` |
| TASK-010 | Added session undo/redo for canvas editing and recorded D-010 revision policy. | PR #8, `6955113` |
| TASK-011 | Made storage failures visible and recoverable instead of silently replacing user data. | `3458372` on `main` |
| TASK-012 | Established `docs/IMPLEMENTATION_STATUS.md` as the canonical implementation-status document. | `e519189` on `main` |
| TASK-013 | Retired the obsolete overnight log. | `a051f8f` on `main` |
| TASK-014 | Added the current QA checklist and aligned its Git policy with `AGENTS.md`. | `e3d8b12` on `main` |
| TASK-015 | Added and hardened the local GitHub queue runner. | `94680e5`, `16c90cf` |
| TASK-016 | Exercised the autonomous queue workflow for issue #1. | `65ce52f` |
| TASK-017 | Exercised and corrected the autonomous queue workflow for issue #4. | `683fc2f` |
| TASK-018 | Made Threadline installable on mobile as a PWA. | PR #12, `8856c3d` |
| TASK-019 | Added separate confirmation provenance for fixed deadlines and scheduled events. | PR #23, `bd76a49` |
| TASK-020 | Added a responsive, navigable full month Calendar view. | PR #24, `d16cb64` |
| TASK-021 | Added bounded pointer/keyboard canvas resizing and text/group shape conversion. | PR #22, `2e4cb4e` |

## Hosting status

- The current production alias is `https://working-ten-rust.vercel.app`.
- The claimed project at `https://temporary-zippy-agate-50psn81.vercel.app` is connected to `tanner-art/working` in GitHub and is awaiting the next push to receive the current build.
- The local `.vercel` directory is intentionally ignored. The pending `.gitignore` change in canonical `main` must be preserved and integrated through review.
