# Threadline Task Board

## Task Lifecycle

BACKLOG -> READY -> IN_PROGRESS -> REVIEW -> MERGE_READY -> DONE

A task may move from REVIEW to CHANGES_REQUESTED and then back to IN_PROGRESS.

Only READY tasks may be newly assigned.

## Rules

- One implementation owner per task.
- One task has explicit scope.
- Agents cannot expand their own scope.
- Newly discovered work becomes a proposed new task.
- Dependencies must be satisfied before READY.
- Product decisions are recorded in docs/DECISIONS.md.
- Architecture changes require explicit assignment.
- Completion requires a commit SHA.
- Author and reviewer should normally be different agents.

---

## READY

### TASK-001 - Audit Current Implementation Against Architecture

Status: READY
Owner: Unassigned
Reviewer: Unassigned
Priority: P0
Milestone: M0

Depends On:
- None

Goal:
Determine what currently exists in the application and how it maps to the new North Star and architecture.

Scope:
- inspect existing repository
- inspect preserved pre-orchestration branch where useful
- identify implemented features
- identify architectural mismatches
- identify reusable work
- identify abandoned or experimental work

Do Not:
- modify application code
- refactor
- implement missing functionality

Deliverable:
Create or update docs/IMPLEMENTATION_STATUS.md with:
- current stack
- implemented features
- incomplete features
- architecture mismatches
- reusable components
- technical debt
- proposed follow-up tasks

Acceptance Criteria:
- no application code changed
- every major existing subsystem is accounted for
- proposed work is separated from observed current state
- newly proposed tasks include dependencies

Result:
Commit: pending
Review: pending

---

## BACKLOG

Tasks generated from TASK-001 will be added here and promoted to READY only when dependencies and scope are clear.

---

## IN_PROGRESS

None.

## REVIEW

None.

## CHANGES_REQUESTED

None.

## MERGE_READY

None.

## DONE

None.
