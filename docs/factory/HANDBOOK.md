# Threadline Factory  
## A Plain-English Guide to How the System Works

## 1. What the Factory Is

The Threadline Factory is a system for getting software work done through multiple AI workers without requiring a person to manually manage every prompt, branch, terminal window, or review step.

The basic idea is simple:

**You decide what needs to happen.  
The Factory decides how to organize the work, which worker should do it, whether the work is safe to start, how it should be reviewed, and when it is actually finished.**

The Factory is not one AI model.

It is the full system around the models:

- the work backlog
- the scheduler
- the workers
- the branches and worktrees
- the review process
- the evidence
- the dashboard
- the usage/capacity tracking
- the history of what happened

The goal is to turn several AI coding systems into something that behaves more like a coordinated engineering organization.

---

# 2. The Simplest Mental Model

Think of the Factory like a real manufacturing plant.

A normal factory has:

- products that need to be built
- jobs that must be completed
- workers with different skills
- supervisors deciding who does what
- workstations where jobs are performed
- quality inspectors
- records proving what happened
- limits on how much work can happen at once

The Threadline Factory uses the same basic structure.

### In Factory language:

**Feature**  
The thing we ultimately want to build.

**Work Package**  
A specific chunk of work needed to build that feature.

**Worker**  
An AI agent capable of doing the work.

**Orchestra**  
The coordinator that decides what work should happen next.

**Lease**  
A temporary claim saying, “this worker currently owns this task.”

**Lane**  
The type of work being performed.

**Assurance**  
Independent review proving the work is actually good enough.

**Registry**  
The central system that records what work exists, who owns it, what state it is in, and what happened.

---

# 3. The Main Flow

At a high level, work moves through the Factory like this:

**Idea or objective**

→ Feature

→ Work packages

→ Dependencies checked

→ Ready work identified

→ Orchestra selects an eligible worker

→ Worker claims the package

→ Worker implements it

→ Tests and evidence are produced

→ Independent review happens

→ Work is approved or sent back

→ Completed work is merged

→ The next blocked tasks become available

The Factory repeats this process continuously.

---

# 4. Orchestra

## What is Orchestra?

Orchestra is the Factory's coordinator.

It is not supposed to be the worker that writes most of the code.

Its job is to answer questions like:

- What should be worked on next?
- What work is blocked?
- Which worker is capable of doing this?
- Which workers are currently available?
- Are we already doing too much at once?
- Does this task depend on something unfinished?
- Is the worker running low on usage?
- Does this work need independent review?
- Did a previous attempt fail?
- Can another task start now?

A useful analogy is:

**Workers are employees.  
Orchestra is the operations manager.**

Orchestra coordinates, decomposes, adjudicates, and protects system capacity. It is explicitly prevented from claiming normal implementation work itself.

---

# 5. Workers

A worker is an AI system that can perform a task.

Examples currently include Agent A, Agent B, and Claude, but those names are not supposed to become permanent roles in the architecture.

Instead, workers are described by their capabilities.

For example, a worker might be capable of:

- frontend coding
- backend coding
- database work
- testing
- documentation
- architecture review
- adversarial review

The Factory should ask:

**“What capabilities does this task require?”**

not:

**“Which named AI usually does this?”**

This makes the Factory model-agnostic.

A worker can be replaced later without redesigning the Factory.

---

# 6. Capabilities

A capability is a skill that a worker is approved to perform.

Examples:

- React frontend
- Python backend
- database migration
- testing
- code review
- security review
- documentation

Tasks can require one or more capabilities.

Workers can only receive tasks they are qualified to perform.

This helps prevent a worker from being assigned simply because it is idle.

---

# 7. Lanes

Lanes describe the kind of work being done.

The Factory currently defines three main lanes.

## FEATURE

User-facing product work.

Examples:

- building a new screen
- implementing a feature
- improving a workflow
- adding functionality users interact with

## PLATFORM

Infrastructure and internal systems.

Examples:

- database architecture
- task scheduling
- registry systems
- telemetry
- orchestration
- persistence
- deployment infrastructure

## ASSURANCE

Independent verification.

Examples:

- reviewing another worker's code
- regression testing
- adversarial testing
- validating architecture
- checking acceptance criteria

The important idea is:

**Lanes describe the work, not the identity of the worker.**

A worker may be approved for one or several lanes.

---

# 8. Features

A Feature is the human-level thing we care about completing.

For example:

**“Google Calendar integration”**

might be a Feature.

That Feature could contain multiple Work Packages:

- OAuth authentication
- import calendar events
- create calendar events
- synchronization logic
- UI
- tests
- review

The dashboard should show Features first because that is what humans care about.

You should not need to understand every internal task just to know whether the feature is moving.

---

# 9. Work Packages

A Work Package is a bounded piece of work that one worker can own.

A good Work Package answers:

- What is the goal?
- What is in scope?
- What is explicitly out of scope?
- What capabilities are required?
- What dependencies exist?
- What counts as complete?
- What tests are required?
- What evidence should be produced?

The goal is to prevent vague tasks like:

**“Improve the calendar.”**

Instead:

**“Implement read-only Google Calendar event import using the existing integration boundary. Do not implement event creation or synchronization yet.”**

A Work Package should be small enough that one worker can finish it without silently expanding into unrelated work.

---

# 10. Scope

Scope defines what a worker is allowed to change.

One of the most important Factory rules is:

**A worker cannot expand its own scope.**

If a worker discovers another problem, it should report:

- what it found
- whether it blocks the current task
- what new task should probably be created

It should not simply start fixing everything it notices.

This protects the architecture from “while I'm here” changes and uncontrolled rewrites.

---

# 11. Dependencies

A Dependency means one task cannot safely happen until another task is complete.

Example:

**Task B depends on Task A.**

Task B must wait.

The Factory should not assign Task B simply because a worker is free.

Dependencies are one of the first things Orchestra checks before dispatching work.

---

# 12. Priority

Priority describes how important a Work Package is relative to other available work.

Priority alone does not determine what gets assigned.

The Factory also considers:

1. whether dependencies are satisfied
2. whether the worker has the required capabilities
3. worker availability
4. capacity
5. how long the task has been waiting

The planned ordering is:

**Dependencies  
→ Priority  
→ Capability  
→ Oldest ready work**

---

# 13. Ready vs Blocked

## READY

A task has everything required to start.

That means:

- dependencies are satisfied
- required decisions are made
- the task is properly scoped
- an eligible worker exists

## BLOCKED

Something prevents the task from starting.

Examples:

- dependency unfinished
- missing product decision
- authentication problem
- no eligible worker
- capacity unavailable
- previous failure requiring intervention

The Factory should explain **why** something is blocked instead of simply leaving it inactive.

---

# 14. The Feature States

The Factory uses six human-facing states:

## ON DECK

We know we want this, but it is not ready to start.

## READY

It can start whenever an eligible worker and capacity are available.

## ACTIVE

Someone is currently working on it.

## VERIFY / REVIEW

Implementation is complete, but the work still needs validation.

## BLOCKED

Something prevents progress.

## DONE

The required implementation and evidence have passed the completion rules.

These states are intended to make the dashboard understandable without exposing every low-level implementation detail.

---

# 15. The Registry

The Registry is the Factory's central control system.

It records:

- Features
- Work Packages
- Dependencies
- Workers
- Capabilities
- Leases
- Attempts
- Evidence
- Usage observations
- Failures
- Events

The Registry answers:

**“What is actually happening right now?”**

Previously, Factory state was scattered across GitHub issues, queue files, branch state, logs, labels, and worktrees.

The Registry exists to give the Factory one coherent operational picture.

---

# 16. SQLite and the Registry

The first Registry implementation uses SQLite with WAL.

For a nontechnical reader:

**SQLite is basically a small database stored locally on the Mac.**

**WAL** means “Write-Ahead Logging.”

That simply means the database keeps a reliable transaction log that makes concurrent and interrupted operations safer.

The important architectural rule is:

**SQLite is not the Factory.**

The Factory talks to a generic Registry interface.

SQLite is just the first implementation.

Later, the Registry could move to something like Postgres or Supabase without redesigning the scheduler.

---

# 17. Source of Truth

A “source of truth” is the place the system treats as authoritative.

If two systems disagree, the source of truth wins.

During the migration, the goal is for the Registry to become the authoritative source for Factory operations.

GitHub will still matter enormously, but mainly as:

- collaboration surface
- code repository
- PR system
- review evidence
- commit history

The Registry answers operational questions such as:

- who owns this task?
- is it active?
- is it blocked?
- which worker is eligible?
- is there an active lease?

---

# 18. Lease

A Lease is one of the most important concepts in the Factory.

A lease means:

**“This worker owns this task right now.”**

It has:

- a worker
- a task
- a start time
- an expiration time
- a release reason

Why use leases instead of simply saying “assigned to Agent B”?

Because workers can crash.

Sessions can expire.

Machines can restart.

Tasks can get stranded.

If the lease expires, the Factory can safely reason about whether the work needs recovery.

The Registry enforces:

- one active lease per task
- one active lease per worker
- no more than three active parent Work Packages globally

---

# 19. Three-Parent Limit

The Factory intentionally limits itself to three active parent Work Packages at one time.

This is not because only three workers can exist.

It is because unlimited parallelism often produces:

- merge conflicts
- dependency collisions
- review bottlenecks
- duplicated work
- wasted model usage

The Factory is optimizing for:

**useful throughput**

not:

**maximum number of agents running.**

---

# 20. Attempt

An Attempt is one execution of a Work Package.

A task might require more than one attempt.

For example:

**TASK-200**

Attempt 1  
→ Agent crashes

Attempt 2  
→ implementation fails tests

Attempt 3  
→ succeeds

The Factory keeps all three attempts.

It does not overwrite history when something is retried.

This is important for debugging and learning.

---

# 21. Evidence

Evidence proves that work is actually complete.

Evidence may include:

- commit SHA
- test results
- build results
- CI
- review result
- deployment preview
- screenshots
- artifact links

A task should not become DONE just because an AI says:

**“Finished.”**

It becomes DONE because the required evidence exists.

---

# 22. Assurance

ASSURANCE is independent quality control.

The central rule is:

**The implementer should not be the only reviewer of its own work.**

A worker may implement something.

Another worker should independently inspect it.

For higher-risk work, review may include:

- adversarial testing
- failure simulation
- regression checks
- architecture review

The Factory already treats implementer/reviewer separation as a core requirement.

---

# 23. Provenance

Provenance means:

**“Where did this come from, and what happened to it over time?”**

For Factory work, provenance may include:

- original task
- worker assigned
- worktree
- branch
- attempts
- commits
- PR
- reviews
- failures
- retries
- final evidence

This prevents situations where a task record claims work exists somewhere that it actually does not.

The migration discovered a real example of provenance drift: issue #99 pointed at a retry worktree that had never actually been created.

---

# 24. Append-Only Events

The Factory maintains an event history.

Examples:

- TASK_READY
- TASK_CLAIMED
- TASK_STARTED
- TASK_BLOCKED
- TASK_REVIEW_REQUESTED
- TASK_FAILED
- TASK_COMPLETED

“Append-only” means old history cannot simply be rewritten.

New events are added.

This creates an audit trail.

---

# 25. Failure Taxonomy

Instead of every worker writing a random failure message, the Factory uses normalized failure categories.

Examples include:

- HEARTBEAT_MISSED
- RATE_LIMIT
- CONTEXT_EXHAUSTED
- SCOPE_DRIFT
- CI_FAILURE
- REVIEW_FAILURE
- DEPENDENCY_BLOCKED
- MERGE_CONFLICT
- AUTH_FAILURE
- TASK_TOO_LARGE
- ORCHESTRA_CAPACITY_RISK

There can still be a human-readable explanation.

The code gives the Factory a consistent way to recognize patterns.

---

# 26. Heartbeat

A Heartbeat is a periodic signal from a worker or service saying:

**“I am alive, and this is my current state.”**

Machine heartbeats occur roughly every 60 seconds in the current infrastructure.

A missing heartbeat can indicate:

- process failure
- machine issue
- crashed worker
- stale task ownership

---

# 27. Capacity

Capacity means how much usable AI work remains available.

Examples:

- model usage remaining
- rate limits
- account limits
- session availability

The Factory should not assume that an authenticated worker has capacity.

If usage information is stale or unknown, the system treats the worker as constrained instead of inventing availability.

Workers with percentage telemetry use four stages: normal below 90%, caution
from 90% to 95%, checkpoint from 95% to 98%, and hard stop at 98%. Caution and
checkpoint avoid substantial or uncertain parent packages. Healthy active work
may reach a clean checkpoint after crossing 95%; it is not interrupted merely
for crossing that line. Hard stop permits only emergency recovery or very small
bounded assurance work.

Some providers do not expose a live usage percentage. Those workers use fresh
service, authentication, heartbeat, live-invocation, and actual limit signals.
Healthy evidence keeps them normally eligible. The Factory records real rate
limits or exhaustion instead of inventing a percentage ceiling.

---

# 28. Orchestra Reserve

The system reserves part of the coordinator's capacity.

The current rule is:

**Keep at least 20% of Orchestra capacity in reserve.**

Why?

Because the coordinator must still be able to:

- respond to failures
- reprioritize
- adjudicate conflicts
- create new tasks
- review unusual situations
- recover the system

If Orchestra consumes all of its usage doing normal work, the Factory can lose its ability to manage itself.

---

# 29. Shadow Dispatch

Shadow Dispatch is how we test the new scheduler safely.

The scheduler examines real Factory state and decides:

**“If I were allowed to assign work right now, what would I do?”**

But it does not actually launch anything.

It records:

- eligible workers
- rejected workers
- eligible tasks
- rejected tasks
- reasons
- ordering
- proposed assignment

Then those decisions are compared against the existing system.

This lets us prove the scheduler behaves correctly before giving it real authority.

The new scheduler must pass several consecutive sweeps plus completion/failure simulations and independent assurance before live dispatch can be considered.

---

# 30. Live Dispatch

Live Dispatch is when Orchestra is actually allowed to:

- claim tasks
- create leases
- assign workers
- launch execution
- update Factory state

Shadow Dispatch must come first.

Live dispatch requires separate approval.

---

# 31. Cutover

Cutover means:

**“The new system is now the authoritative production system.”**

For example:

Before cutover:

GitHub labels + queue files + local state may still drive execution.

After cutover:

The central Registry becomes the source of truth for dispatch.

Cutover is intentionally a deliberate event.

It should never happen accidentally because a new component exists.

---

# 32. Worktree

A Git Worktree is an isolated working copy of the same repository.

This lets multiple workers modify the codebase simultaneously without editing the same physical files.

Example:

- Agent A → worktree A
- Agent B → worktree B
- Claude → worktree C

Each can work on a different branch.

Worktrees are the worker's physical workspace.

---

# 33. Branch

A Branch is a version line in Git.

Instead of every worker writing directly to `main`, workers write to their own branches.

Example:

`codex/task-123-calendar-import`

The branch holds the worker's commits until review and merge.

---

# 34. Pull Request

A Pull Request, or PR, asks:

**“Should the changes on this branch become part of main?”**

A PR provides:

- diff
- CI
- review discussion
- commit history
- preview deployment
- evidence

The Factory uses PRs as collaboration and assurance surfaces.

---

# 35. Main

`main` is the canonical code branch.

It represents the accepted product state.

Workers should not casually edit `main`.

Work should generally move:

Worker branch

→ Pull Request

→ Review

→ Merge

→ `main`

---

# 36. CI

CI means Continuous Integration.

In simple terms:

**Every proposed code change is automatically tested.**

CI may run:

- unit tests
- type checking
- builds
- linting
- integration tests

Green CI means those automated checks passed.

It does not automatically mean the product decision itself was correct.

That is why independent review still matters.

---

# 37. Reconciliation

Reconciliation means proving that two representations of reality agree.

During the Factory migration, the Registry import was compared with the existing repository state.

The current preservation reconciliation found:

- 33 worktrees
- 8 dirty worktrees
- 7 unmerged branches
- 0 unexplained records
- 0 active leases

Zero unexplained records is especially important.

It means the migration has accounted for the known work instead of silently losing it.

---

# 38. Preservation

Preservation means:

**Do not destroy or “clean up” old work until we understand what it is.**

During migration:

- do not delete worktrees
- do not reset them
- do not rebase them
- do not overwrite dirty files
- do not casually consolidate branches

Every artifact gets classified first.

Preservation exists because unfinished work may still contain valuable implementation or reasoning.

---

# 39. Scheduler

The Scheduler decides which READY task should be assigned next.

Eventually its reasoning looks approximately like:

**Are dependencies satisfied?**

→ How high is the priority?

→ Which workers have the required capabilities?

→ Which of those workers are available?

→ Is sufficient capacity available?

→ Which task has waited longest?

→ Would assigning it violate the three-parent limit?

→ Would it violate Orchestra reserve?

Only then should the Factory assign work.

---

# 40. Dashboard

The Dashboard is the human view of the Factory.

The dashboard is not supposed to become another source of truth.

It reads from the Registry.

Its default level should focus on Features:

- ON DECK
- READY
- ACTIVE
- VERIFY / REVIEW
- BLOCKED
- DONE

A user can expand deeper when needed into:

- Work Packages
- worker assignments
- attempts
- PRs
- tests
- evidence
- failures

The goal is:

**simple at the top, inspectable underneath.**

---

# 41. Why the Factory Exists

Without the Factory, adding more AI agents can actually make development worse.

You get:

- duplicated work
- branches nobody remembers
- unreviewed code
- agents stepping on each other
- unclear ownership
- wasted usage
- forgotten failures
- tasks completed in the wrong order

The Factory exists to make parallel AI work reliable.

The objective is not:

**“Run the most agents possible.”**

The objective is:

**“Turn available AI capacity into the maximum amount of correct, reviewed, useful work without losing control of the system.”**

---

# 42. The Factory in One Diagram

You:

**“Build this.”**

↓

### ORCHESTRA
Breaks the objective into bounded Work Packages.

↓

### REGISTRY
Records tasks, dependencies, workers, capabilities, capacity, and history.

↓

### SCHEDULER
Finds READY work and eligible workers.

↓

### LEASE
Temporarily assigns one worker to one package.

↓

### WORKER
Implements the package in an isolated worktree/branch.

↓

### VALIDATION
Tests, builds, CI, and evidence.

↓

### ASSURANCE
Independent review.

↓

### PR
Reviewed code is proposed for `main`.

↓

### MAIN
Accepted product state.

↓

Registry updates.

Dependencies unlock.

Orchestra dispatches the next work.

↓

**Repeat.**

---

# 43. The Most Important Rules

If you remember only ten things, remember these:

1. **Orchestra coordinates; it should not routinely implement.**
2. **Workers are selected by capability, not brand/model name.**
3. **Tasks cannot silently expand their own scope.**
4. **Dependencies must be respected.**
5. **One worker owns a task at a time through a lease.**
6. **No more than three parent packages should be active simultaneously.**
7. **The implementer should not be the sole reviewer.**
8. **A task is not DONE without evidence.**
9. **Unknown capacity is treated as constrained, not assumed available.**
10. **History and provenance should be preserved rather than overwritten.**

---

# 44. The Factory's Long-Term Goal

The desired experience is eventually:

You tell the system:

**“I want Threadline to import MindNode canvases and organize them into semantic clusters.”**

You should not need to:

- open three Terminal windows
- decide which AI gets which task
- manually create branches
- copy prompts between models
- track usage manually
- remember which task depends on which
- inspect every unfinished branch yourself

Instead:

The Factory should break down the objective, schedule safe parallel work, launch eligible workers, review their output, surface the decisions that genuinely require you, and continuously move the product forward.

Your role becomes increasingly:

**Product owner and decision maker**

rather than:

**human message router between AI agents.**

---

# 45. Glossary

- **Canary** — a small, low-risk real test of a new system before you trust it broadly. Instead of turning the whole Factory on, you send one harmless package through READY → lease → launch → implementation → review → DONE. If that succeeds, you gain evidence the full chain works. Your restart plan explicitly uses this lifecycle as the final proof before broader operation. :chatgpt-content-reference{index="0"} Think: *test one airplane before letting the whole fleet fly.*

- **Soak test** — leave a system running for a longer period to see whether problems appear over time. A canary answers “does it work once?” A soak answers “does it remain healthy for hours?” Your degraded-capacity test was essentially a soak: heartbeats, leases, preservation, failures, and review state were monitored repeatedly over time. :chatgpt-content-reference{index="1"}

- **Shadow mode / shadow dispatch** — the scheduler makes real decisions but is forbidden from acting on them. It might say, “I would assign TASK-27 to Agent B,” while creating no lease and launching nothing. This is how you test decision quality before granting authority.

- **Dry run** — similar to shadow mode, but broader. A process goes through the motions without making the consequential change. “Load workers in PAUSED/DRY-RUN” means prove the services, auth, configuration, and decision logic work before allowing real tasks to launch. Your restart procedure explicitly starts this way. :chatgpt-content-reference{index="2"}

- **Lease** — temporary exclusive ownership of work. “Agent B has the lease on TASK-X” means nobody else should work that package until B finishes, fails, or the lease expires. This prevents duplicate agents from doing the same work. The Factory’s Registry was designed around transactional leases and one active owner. :chatgpt-content-reference{index="3"}

- **Lease expiry** — the lease has a time limit. If an agent dies or disappears, the Factory does not assume it owns the task forever. After expiry and recovery checks, the package can eventually be reassigned.

- **Heartbeat** — a periodic “I’m alive” signal from a worker or service. Your older system emitted them roughly every 60 seconds. :chatgpt-content-reference{index="4"} If a heartbeat gets stale, Orchestra should question whether the worker is actually healthy.

- **Registry** — the Factory’s operational database of reality: tasks, dependencies, workers, leases, attempts, evidence, failures, usage, events. The whole migration was largely about replacing fragmented state with one authoritative Registry. :chatgpt-content-reference{index="5"}

- **Source of truth / authoritative** — the system whose answer wins when two things disagree. If the Dashboard says Agent B is ACTIVE but the Registry says no lease exists, the Dashboard is wrong because the Registry is authoritative.

- **Projection** — a view generated from the source of truth. Your Control Center is supposed to be a projection of Registry state, not another independent store. That is why dashboard discrepancies are treated as bugs.

- **Reconciliation** — compare two representations of reality and prove they match. Example: “Registry says 33 worktrees, preservation snapshot says 33 worktrees.” Zero unexplained records means reconciliation succeeded. :chatgpt-content-reference{index="6"}

- **Preservation** — don’t destroy old or uncertain work while migrating systems. That is why you kept 33 worktrees and the dirty/unmerged branches instead of “cleaning up.” :chatgpt-content-reference{index="7"}

- **Worktree** — an isolated physical checkout of the same Git repository. Agent A and Agent B can edit separate copies of the same repo without overwriting each other.

- **Branch** — a line of Git history. The worktree is the physical workspace; the branch is the version history that workspace is writing to.

- **PR / Pull Request** — a proposal to merge one branch into another, usually `main`. It gives you the diff, CI, review discussion, and evidence surface.

- **`main`** — the accepted/canonical code branch. Think of it as the product’s approved production history, not somebody’s scratch area.

- **CI / Continuous Integration** — automated validation that runs when code changes. Tests, builds, typechecks, etc. Claude correctly identified that Factory Python code originally lacked CI coverage; that was a real risk because local tests alone don’t guarantee every future PR gets tested automatically.

- **Gate** — a condition that must pass before the system proceeds. A1–A5 are restart gates. “CI green” is a merge gate. “Independent reviewer exists” is a live-operation gate.

- **Acceptance criteria** — concrete proof that a task counts as successfully completed. Not “make canvas better,” but “tap selects, drag moves, resize handle works, tests pass.”

- **ASSURANCE** — your independent review lane. Its job is not primary implementation; it challenges implementation, tests assumptions, catches regressions, and validates acceptance criteria. The architecture explicitly requires implementer ≠ sole reviewer. :chatgpt-content-reference{index="8"}

- **Adversarial review** — stronger than normal review. The reviewer actively tries to break the change, find edge cases, violate invariants, or prove assumptions wrong. You use this for higher-risk systems such as lease semantics because bugs there could corrupt ownership and scheduling.

- **Invariant** — a rule that must always remain true. Examples in your Factory: “one active lease per package,” “no more than three parent packages,” “implementer cannot be sole reviewer.” If an invariant breaks, something is fundamentally wrong.

- **Parent package** — one major active unit of work. The global three-parent cap prevents unlimited parallelism. Child tasks may exist under it, but the parent is what counts against concurrency.

- **Dependency** — work that must finish before another package can safely start. Your original Threadline task graph used dependencies heavily; e.g. many tasks were blocked on the entity-model split. :chatgpt-content-reference{index="9"}

- **Blocked** — a package cannot currently proceed because of a known reason: dependency, owner decision, auth, review, capacity, etc. “Blocked” should always answer *why*.

- **Constrained** — a worker exists and may be healthy, but policy says don’t assign it normal work right now. Example: earlier Agent A was healthy but constrained because of the overly conservative weekly-usage rule.

- **Eligible** — allowed to receive a specific package *right now*. Eligibility can depend on capability, lane, authentication, health, capacity, dependencies, and policy.

- **Capability** — what a worker is trusted/able to do: frontend, platform, assurance, database, etc. Your newer architecture deliberately selects workers based on capabilities instead of permanently saying “Claude does X.” :chatgpt-content-reference{index="10"}

- **Lane** — category of work: FEATURE, PLATFORM, ASSURANCE. It describes the job, not the provider/model. :chatgpt-content-reference{index="11"}

- **Attempt** — one execution try for a package. If attempt 1 fails and attempt 2 succeeds, you preserve both histories rather than pretending the failure never happened.

- **Retry** — another attempt after failure. Your unattended rules correctly say retries should be bounded; otherwise the Factory can waste hours hammering one broken problem.

- **Idempotent** — doing the same operation twice has the same effect as doing it once. This is important in automation. For example, “release lease X” should ideally not cause damage if accidentally called twice.

- **Transactional** — multiple database operations either succeed together or fail together. For a lease claim, you want: check package → check cap → create lease → change state → append event as one atomic operation, not half-finished steps. That’s why the Registry design emphasizes transactions. :chatgpt-content-reference{index="12"}

- **Atomic** — indivisible from the system’s perspective. A task claim should be atomic so Agent A and Agent B cannot both see “free” and both claim it simultaneously.

- **Race condition** — two processes act at nearly the same time and produce a bad outcome depending on timing. Duplicate task claims are a classic race condition.

- **Rollback** — return the system to a known safe state after something goes wrong. Your restart controls require returning to PAUSED without losing ownership/provenance. :chatgpt-content-reference{index="13"}

- **Kill switch** — immediate ability to stop new Factory activity. Different from rollback: kill switch stops; rollback restores.

- **Cutover** — the moment a new system becomes the live authoritative one. Example: switching from local SQLite Registry to hosted Postgres. You can build and test the hosted system for weeks without “cutting over.”

- **Migration** — moving from one architecture/data system to another. Cutover is the switch; migration is the whole process getting there.

- **Adapter** — code that makes one backend behave like a common interface. SQLite Registry adapter and future Postgres Registry adapter let the rest of the Factory use the same Registry API without caring which database is underneath.

- **API** — a defined way for software components to talk to each other. Your future Factory API would let Mac workers and the hosted Control Center interact with Registry functionality without directly manipulating the database.

- **Schema** — the structure of stored data: tables, columns, relationships, constraints. “Registry schema” means the shape of Features, Work Packages, Workers, Leases, Attempts, etc.

- **WAL / Write-Ahead Log** — database technique where changes are logged before being finalized. It helps SQLite handle crashes/concurrency more reliably. Your migration specifically chose SQLite with WAL as the initial Registry foundation. :chatgpt-content-reference{index="14"}

- **Telemetry** — measurements about how the system is behaving: heartbeat, runtime, token usage, failures, latency, capacity. It is observation data, not necessarily business/product data.

- **Provenance** — the chain showing where something came from and what happened to it. In the Factory: task → attempt → worker → branch → commit → PR → review → evidence. In Threadline itself, provenance also means preserving the original user thought rather than allowing AI interpretation to overwrite it. The North Star explicitly requires original thought preservation. :chatgpt-content-reference{index="15"}

- **Append-only** — old history isn’t rewritten; new facts/events are added. Useful for provenance because failed attempts don’t disappear.

- **Drift** — two things that are supposed to agree slowly stop agreeing. Example: Dashboard says 3 items in review while Reviews tab shows 0. That’s dashboard/Registry drift.

- **Stale** — information was once valid but is too old to trust now. A usage measurement from hours ago may be stale even though it was correct when recorded.

- **Dry-run vs paused** — `PAUSED` means the worker/system should not dispatch real work. `DRY-RUN` means it may exercise logic without the consequential side effects. Often you use both together during restart.

- **Live authority** — permission for a component to actually affect real state: create leases, launch workers, merge code, mutate queues, etc. Much of your migration has been about gradually increasing authority only after evidence.

- **Feature flag** — a switch in code/config that lets you turn behavior on/off without rewriting it. The migration brief explicitly wanted the new scheduler behind a flag so old and new dispatchers cannot race each other. :chatgpt-content-reference{index="16"}

- **Graceful degradation** — system keeps functioning in a reduced mode instead of failing entirely. Example: only Agent B eligible, so Factory runs one package rather than pretending all three workers are available.

- **Fail-safe / fail closed** — if the system is uncertain, it chooses the safer option. Your early scheduler treated stale capacity as constrained rather than assuming availability. :chatgpt-content-reference{index="17"}

- **False positive / false negative** — useful when thinking about automated gates. False positive: Factory thinks worker is unhealthy when it’s actually fine. False negative: Factory thinks it’s healthy when it’s actually unavailable. Your Claude quota problem was basically creating false positives by equating “no percentage telemetry” with “no capacity.”

- **Throughput** — useful completed work per unit time. Not agents running, not commits, not tokens. Your Factory should optimize reviewed/DONE packages.

- **Latency** — how long one piece of work takes from start to finish. You can have high throughput even if individual package latency is somewhat high if several safe packages run in parallel.

- **Bottleneck** — the stage limiting the whole pipeline. Earlier your bottleneck shifted from implementation capacity to ASSURANCE/review capacity when Agent B finished but nobody was eligible to review it. :chatgpt-content-reference{index="18"}

- **Backpressure** — deliberately slow upstream work when downstream capacity is overloaded. Example: stop launching more implementation when VERIFY/REVIEW is piling up faster than reviewers can clear it.

- **Observability** — ability to understand the system’s internal state from external signals. Logs are part of observability; the Control Center is supposed to make the Factory observable to you.

- **Control plane** — the part that decides and coordinates what happens. Orchestra + Registry + scheduler + policies are the Factory control plane. The agents doing actual coding are the execution/data plane, loosely speaking.

- **Canonical** — the accepted official version. `main` is canonical code; Registry is becoming canonical operational state.

The handful I’d make sure you can explain back without notes are: **canary, soak, shadow mode, dry run, lease, heartbeat, Registry, reconciliation, invariant, race condition, transactional/atomic, rollback, cutover, provenance, telemetry, drift, backpressure, and control plane**. Once those click, most of what Orchestra reports stops sounding like infrastructure jargon and starts reading like ordinary operations.
