# Threadline North Star

We are building an AI-native personal thought-to-execution system.

Do not begin by building a generic notes app, task manager, Notion clone, or calendar clone.

## Fundamental Problem

The user captures a very high volume of thoughts, ideas, reminders, actions, and project concepts.
Capture is easy.
The difficult problem is understanding, storing, resurfacing, evaluating, prioritizing, and turning those thoughts into execution without forcing structure too early.

## Core Product Principle

The system has two fundamental ways of thinking.

### Raw Capture

Voice or text is used to capture raw consciousness quickly.
The user should be able to say or write something without deciding what type of thing it is.

### Visual Formulation

The user needs an infinite canvas where they can spatially construct thoughts.
They can:

- create text blocks
- draw freehand
- create shapes
- connect things with arrows
- create containers and groups
- move things freely
- create nested structures
- arrange ideas spatially

The canvas is not simply a presentation layer.
It is an input method for thinking.

Everything eventually feeds into the same underlying semantic system.

## Preserving Expression and Meaning

Voice, text, and canvas input create or reference an immutable CaptureRecord: a record of what the user originally expressed. Later corrections and edits preserve the earlier expression rather than overwriting it.

The semantic flow is:

Capture → Interpretation(s) → Semantic Objects → Relationships → Views / Plans

One capture can support multiple interpretations and multiple objects. Semantic objects reference their captures; they do not each own a duplicate of the original content.

The system should support extensible semantic objects such as:

- Idea
- Action
- Project
- Commitment
- Person
- Reference
- Objective

An Action represents executable work. Work merely suspected by AI stays a proposed interpretation (a ProposedAction) until the user confirms it. Confidence alone must not silently turn a suggestion into an Action.

A Commitment represents an obligation or promise. A CalendarEvent represents something scheduled at a time. A commitment may have a calendar event, but a promise can exist without a scheduled event, and an event does not itself establish an obligation.

Reminders are scheduling/notification instructions attached to an Action, Commitment, Project, Idea, or other object. Asking to be reminded about an idea does not turn it into a task or commitment.

## AI Interpretation

When something is captured:

1. Attempt to understand it.
2. Determine whether enough information exists to classify and store it.
3. If confidence is high, automatically organize non-consequential meaning where appropriate; inferred work remains proposed until confirmed.
4. If confidence is low or a consequential decision is required, put it into Review.
5. Never silently create an Action from AI-suspected work or a hard commitment from ambiguous input.
6. Preserve provenance and allow interpretations to be rejected, changed, or reversed without changing the original capture.

Examples:

- "Ahmed Monday convo" may imply a person, Monday conversation context, and a possible prepare/contact action.
- "AI sales training" may imply an idea, software topic, and potential project candidate.
- "Give marketing guys access" may imply an action with marketing context.
- "Screws for monitor / selling arm things / better keyboard" may imply a project or task cluster containing multiple actions and ideas.

## Review

Review is a deliberate decision interface.

It should show uncertain or consequential items and let the user confirm or modify:

- object type
- project
- context
- timing
- action
- commitment
- relationships

AI should propose interpretations rather than simply asking blank questions.

The user should be able to say:

- "Yes"
- "Change this"
- "Put it under Carvers"
- "That's an idea, not an action"
- "Remind me Tuesday"

## Calendars and Planning

### Calendar

The calendar shows scheduled events such as appointments, meetings, and calls. Events may link to semantic commitments. Unscheduled promises remain visible as commitments without inventing a calendar time.

A deadline is a constraint, not automatically a calendar event. It may be displayed alongside events as a distinct due-date marker.

Fixed calendar events should only move through an explicit cancellation or rescheduling decision, not because a flexible work plan is recalculated.

### Adaptive Plan

The Adaptive Plan continuously recalculates how available time and attention can be allocated to confirmed executable work. Its work allocations are flexible and distinct from fixed calendar events.

It considers urgency, deadlines, effort, attention load, available time, dependencies, strategic importance, and resource constraints, with optional ROI later.

The plan should explain recommendations and adapt when capacity, estimates, constraints, or priorities change. It is a living allocation of work, not a conventional static task list.

## Prioritization Model

Do not hide everything inside one simplistic priority field.

Keep these estimates and value judgments separate:

- effort: how much time or work is required
- attention load: how cognitively demanding or disruptive the work is
- strategic importance: contribution to meaningful objectives
- resource cost: required money, people, or other resources
- optional ROI: expected return relative to investment

Urgency describes how soon something matters and may be derived partly from its deadline and remaining work. A deadline is a constraint/input, not another interchangeable priority score.

Dependencies are graph constraints that determine what can proceed and in what order. They are not scalar scoring dimensions. Available time, attention capacity, and other resource limits also constrain feasible plans; status determines whether work is eligible.

Prioritization should compare feasible work using these distinct inputs without conflating effort, attention, urgency, or value.

## Resource Model

Eventually the system should reason about limited resources.

Initial resource dimensions:

- time
- attention and cognitive capacity
- money
- people and capacity

The system should eventually be able to answer:

- "What is the best use of my next 3 hours?"
- "What should I finish this week?"
- "What am I spending attention on that has little value?"
- "What can wait?"
- "What has the highest expected ROI?"

ROI should initially be optional and future-facing rather than required for every item.

## Ideas

Ideas should not be treated like tasks.

An idea can exist indefinitely without becoming an obligation.

Ideas should be grouped progressively.

Example:

Initially:

- Software Ideas

As volume grows:

- Software
- Internal Tools
- Customer Products
- AI Products
- Automation

AI should propose increasingly specific organization only when sufficient information density exists.

Do not create hundreds of folders or tags immediately.

The organizing principle is: organization should emerge as raw load increases.

## Projects

A project is a container for a meaningful outcome.

Projects can contain:

- actions
- ideas
- commitments
- people
- references
- dependencies
- objectives

Projects should have:

- desired outcome
- status
- target timeframe
- estimated effort
- attention requirements
- dependencies
- resource requirements
- strategic importance
- optional ROI

Reminders may attach to the project or its objects without becoming project content types.

Projects are living systems.

The user currently has major entities and objectives such as:

- Carver Corp
- LinguaTrip
- Ludus
- marketing agency concepts
- Carvers

Do not hardcode these into the product.
They are examples of contexts and projects.

## Objectives

The system should support high-level objectives.

An objective can constrain project priority.

Example:

"Carvers must accomplish X within four months."

Projects and actions can then be evaluated against that objective.

## Morning Digest

The system should have a 7 AM morning digest.

It should include:

1. Fixed calendar events today and their linked commitments
2. Important upcoming commitments and deadlines, including unscheduled obligations
3. Recommended execution for today
4. Items that require user decisions
5. Major project or objective status when relevant

The digest should optimize attention, not maximize the number of tasks displayed.

## Canvas

Build the canvas as a foundational feature.

Required:

- infinite pan and zoom
- text nodes
- arbitrary positioning
- containers and groups
- arrows and connectors
- freehand drawing
- shape creation
- selection
- drag and drop
- resizing
- multi-select
- grouping
- undo and redo
- persistent state

The architecture must allow AI to interpret canvas content.

A future AI operation should be able to analyze:

- spatial proximity
- containment
- arrows
- labels
- text
- drawing
- grouping

and infer semantic relationships.

Never destroy or overwrite the original canvas structure when generating semantic interpretations.

## Sources of Truth and Reversibility

Immutable captures and preserved canvas revisions are the source of truth for what the user actually expressed. The semantic graph is the source of truth for the system's current interpretation.

Interpretations must remain reversible. Changing meaning must not rewrite the original expression or erase the user's canvas structure.

Calendar, project, review, idea, and planning views share the semantic graph. The canvas also preserves its own visual expression: a text block or shape can exist without becoming an Idea, Action, or Project, and may optionally link to semantic meaning.

Entity boundaries, provenance, and flows are described in [ARCHITECTURE.md](ARCHITECTURE.md). These describe the intended architecture; the current MVP has not yet implemented all of these boundaries.

## MVP

The first vertical slice should not attempt the entire vision.

Build:

1. Capture screen with text input, voice placeholder/interface, and optional context.
2. AI interpretation pipeline that proposes Ideas, Actions, Projects, and other meaning with confidence and provenance; suspected work requires confirmation before becoming an Action.
3. Review screen for uncertain items, with confirm/edit classification.
4. Persistent captures with reversible interpretations and semantic objects that reference them.
5. Basic calendar that distinguishes scheduled events from semantic commitments and deadlines.
6. Basic infinite canvas with text nodes, arrows, containers, free positioning, and persistence.
7. Today screen with today's events, relevant commitments and deadlines, and manually confirmed actions.

Do not implement sophisticated ROI optimization or autonomous scheduling yet.

The architecture should make those possible later.

## Development Approach

Before writing large amounts of code:

1. Inspect the existing repository.
2. Explain the current stack.
3. Propose the architecture.
4. Define the data model.
5. Define the first vertical slice.
6. Implement incrementally.
7. Keep the system testable.
8. Do not add unnecessary frameworks.

When making product decisions that are ambiguous, prefer preserving user intent and reversibility over automation.

The long-term goal is:

Capture -> Understand -> Classify -> Review -> Evaluate -> Prioritize -> Plan -> Execute -> Adapt

The system should preserve the original thought while continuously building higher-level structure around it.
