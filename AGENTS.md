# Agent Operating Rules

## Authority
Agents execute assigned tasks. They do not redefine product scope, architecture, or priorities.

## Scope Lock
An agent may only modify code necessary to complete its assigned task.

## Modular Changes
New behavior should enter through a small module with one clear responsibility and a narrow
typed interface. Keep data access, domain rules, provider calls, and presentation separate
when the boundary is meaningful. Do not bury feature-specific workflows in `App.tsx`, create
parallel sources of truth, or perform broad refactors to claim modularity. Reuse an existing
boundary when it already owns the behavior; otherwise identify the new module and its contract
in the task. Test the contract and important failure behavior at that boundary.

An agent must NOT:
- expand its own scope
- implement newly discovered features
- refactor unrelated systems
- change product behavior outside acceptance criteria
- alter NORTH_STAR.md or ARCHITECTURE.md unless explicitly assigned
- merge into main

If additional work is discovered:
1. Describe the issue.
2. Propose a new task.
3. Explain whether it blocks the current task.
4. Continue the current task only if safe.
5. Do not implement the new task without assignment.

## Git
- Work only on your assigned branch/worktree.
- Commit completed work.
- Never merge into main.
- Report the commit SHA when finished.

## Before Coding
Read:
1. docs/NORTH_STAR.md
2. docs/ARCHITECTURE.md
3. docs/ROADMAP.md
4. docs/DECISIONS.md
5. TASKS.md
6. The assigned task

Inspect existing code before modifying anything.

## Completion
Before declaring a task complete:
- verify acceptance criteria
- run relevant tests
- run typecheck
- run lint if configured
- run build
- inspect git diff
- confirm new feature logic is placed behind an appropriate module boundary
- report files changed
- report known limitations
- report newly discovered work separately
- commit the task

## Review
The author of a task should not be its sole reviewer.

Reviewers should not rewrite the implementation unless specifically assigned to fix it.
