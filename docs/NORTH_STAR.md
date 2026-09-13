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

## Object Model

The system should support objects such as:

- Idea
- Action
- Project
- Reminder
- Commitment
- Person
- Reference
- Objective

Objects must be extensible.

Type classification should not destroy the original captured thought.

Every object should retain:

- original content
- source type: voice, text, or canvas
- creation timestamp
- context or location
- AI interpretation
- confidence
- relationships
- history
- status
- metadata

## AI Interpretation

When something is captured:

1. Attempt to understand it.
2. Determine whether enough information exists to classify and store it.
3. If confidence is high, automatically classify it.
4. If confidence is low or a consequential decision is required, put it into Review.
5. Never silently create a hard commitment from ambiguous input.

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

## Calendars

There are two calendars.

### Commitment Calendar

This represents external or hard time commitments.

Examples:

- appointments
- meetings
- scheduled calls
- deadlines
- events

This calendar should remain relatively fixed.

It should only change when the underlying commitment changes:

- cancellation
- reschedule
- no-show
- new appointment

### Execution Plan

This is a living plan.

It determines when the user should work on projects and actions based on:

- urgency
- deadline
- effort
- attention load
- available time
- dependencies
- strategic importance
- resource constraints
- eventually ROI

The execution plan is expected to move.

Do not treat the execution plan as a conventional static task list.

## Prioritization Model

Do not create one simplistic priority field and hide everything inside it.

Maintain independent dimensions:

- urgency
- deadline
- effort
- attention_load
- strategic_importance
- dependencies
- resource_cost
- roi
- status

Priority can then be calculated from these dimensions.

Important distinctions:

- Effort is how much time or work the thing requires.
- Attention load is how cognitively demanding or disruptive the thing is.
- Urgency is how soon it matters.

These are not the same variable.

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
- reminders
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

1. Fixed commitments today
2. Important upcoming commitments
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

## Technical Principles

Build this as a real product architecture, not a demo.

Separate:

- capture
- semantic object model
- AI interpretation
- review
- scheduling
- calendar commitments
- execution planning
- canvas
- persistence

The semantic model should be the central source of truth.

The UI is a projection of the underlying objects.

A calendar view, project view, review view, idea view, and canvas should all operate on the same underlying objects.

Do not create isolated databases for each interface.

## MVP

The first vertical slice should not attempt the entire vision.

Build:

1. Capture screen with text input, voice placeholder/interface, and optional context.
2. AI interpretation pipeline that classifies into Idea, Action, Reminder, or Project with confidence and suggested metadata.
3. Review screen for uncertain items, with confirm/edit classification.
4. Basic persistent object model.
5. Basic commitment calendar.
6. Basic infinite canvas with text nodes, arrows, containers, free positioning, and persistence.
7. Today screen with today's commitments and manually confirmed actions.

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
