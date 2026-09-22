# Threadline Functional Design Priority

Updated: 2026-09-21, Europe/Madrid

Release status on 2026-09-22: Review editing/history and the first Canvas Bank document slice are on main. The Canvas Bank's duplicate/archive/restore controls remain open. Calendar Week/Day plus commitment entry is the next product slice. Installed-app code login is also on main but still needs a real-device verification.

Product direction: visible, usable product features move ahead of runner and process work. Infrastructure work continues only where it directly blocks the hosted app, user data, authentication, or feature activation.

## Release blockers that run alongside the feature queue

- Installed iPhone app authentication: TASK-057 explicitly approved on 2026-09-21. Add email-code verification inside the PWA so Safari does not own the only session. Preserve all local data and retain the browser magic-link option.
- Finish production account/RLS cross-device validation.
- Activate provider-backed interpretation only after server-key and Preview validation.

These do not replace the feature sequence below.

## 1. Review editing and thought history

- Make every Review item directly editable on mobile and desktop.
- Use one obvious `Edit thought` action rather than hiding revision behind an object-detail path.
- Preserve the immutable original capture.
- Store each revision as a new version with time, source, and the user gesture that authorized it.
- Show a readable progression log: original capture, AI interpretations, user corrections, confirmations, reversals, and current meaning.
- Let the user revise current meaning or correct the original transcript/text without silently overwriting evidence.

Acceptance: a user can open any Review item, edit it, save it, and see both the current version and the complete preserved history.

## 2. Canvas Bank and canvas document lifecycle

- Rename the Canvas landing surface to `Bank`.
- Put a prominent `Think visually` / `Create canvas` button above the Bank.
- Opening the tab shows a visual gallery/list of named canvases rather than immediately opening the last canvas.
- Create a blank canvas, give it a title, autosave it, exit it, and return to Bank.
- Open, rename, duplicate, archive, restore, and visually select canvases.
- Migrate the existing single canvas into the Bank without losing any nodes, geometry, links, or viewport state.
- Persist canvases locally and in account storage with the existing guarded save behavior.

Acceptance: the user can safely maintain several permanent canvases and move between them in a Google Docs/MindNode-style document flow.

## 3. Calendar daily/weekly views and commitment entry

- Add Month, Week, and Day controls.
- Week view uses day columns and a vertical time grid; Day view expands one day into a full time grid.
- Navigation and current-time indicators should feel familiar to Google Calendar users while retaining Threadline styling.
- Add commitments from the Calendar tab.
- Keep a Commitment and a scheduled CalendarEvent separate in the data model; explicitly confirm the obligation and explicitly choose whether/when to schedule it.
- Show unscheduled commitments without inventing a time.

Acceptance: the calendar visibly redraws between month/week/day, and a user can create a commitment and optionally schedule its related event without leaving Calendar.

## 4. Mobile canvas navigation and manipulation

- Make the workspace effectively unbounded with a broad zoom range and `Fit canvas` / `Fit selection` controls.
- Grow the useful canvas area with the project and minimize mobile toolbar dead space.
- Improve one-finger/two-finger pan, zoom, and selection so the view is maneuverable on a phone.
- Gesture contract:
  - quick tap selects a block or places the text caret;
  - long-press then drag moves the block;
  - long-press without meaningful movement for about 1.5 seconds opens the edit menu;
  - movement cancels the edit menu;
  - resize controls appear only after the edit menu/explicit edit mode is opened.
- The edit menu controls shape, color, size, and internal text.

Acceptance: phone users can reliably select, edit, move, resize, pan, and zoom without accidental menus or obstructive controls.

## 5. Canvas branches, nodes, lists, and editable connections

- Add an organic branch action for rapidly growing child nodes from an existing node.
- A child can remain a mind-map node, take a chosen shape, or become an item in a bulleted work list.
- Let an arrow's start slide around the source shape perimeter.
- Let the arrowhead move freely through 360 degrees and lengthen/shorten while preventing it from terminating inside or pointing back into its source shape.
- Add one draggable curve control in the connection's middle.
- Follow with an experiment using two fixed curve controls for S-curves; do not commit that interaction until mobile testing shows it is usable.

Acceptance: users can create structured and organic branches and manipulate connection endpoints and curves without breaking source-shape boundaries.

## 6. Pen, lasso, smoothing, and shape recognition

- Add a pen tool for freehand doodling.
- Preserve the raw stroke as source expression.
- Holding at the end of a stroke offers reversible smoothing or shape recognition.
- Lassoing one or more strokes and holding offers the same refinement action.
- Let users keep the original, accept a smoothed stroke, or convert a recognized drawing into a canvas shape.

Acceptance: drawing feels direct on mobile, and any automatic cleanup is previewed, reversible, and provenance-preserving.

## 7. Context-aware capture interpretation and safe grouping

- Interpret a new capture with relevant prior captures, conversations, projects, topics, and temporal/spatial proximity.
- Recognize the current set of requests as a `Threadline features / ideation` cluster rather than isolated thoughts.
- In Review, propose coherent groupings and a combined document/summary.
- A merge is always a proposal. The user confirms it before the combined document becomes current meaning.
- Keep every original capture accessible after grouping or merging.

Acceptance: related mind-dump captures receive a useful grouped proposal with citations back to every source capture, and rejection leaves the originals unchanged.

## 8. Organize log, universal search, and bulk actions

- Add a chronological capture log that remains available after review.
- Add universal search across captures, current thoughts, revision history, canvases, commitments, calendar events, projects, and titles.
- Date searches can offer `Open Day view` for the matched date.
- Add multi-select in Review for bulk delete/reject, assign to folder/context, group, or copy/move to a canvas.
- Destructive bulk actions require a preview and confirmation; original capture retention follows the product's evidence rules.

Acceptance: users can retrieve information across the app and safely act on several Review items at once.

## 9. Voice capture and second-brain analysis

- Record and retain the raw voice note. Default retention is 14 days; a user may explicitly save an individual recording or choose a longer retention setting.
- Produce a transcript without replacing the audio.
- Summarize key ideas, proposed actions, commitments, people, projects, and references.
- Link proposals to existing topics and nearby captures using the same safe Review flow.
- Let transcript corrections and later interpretation revisions preserve the raw audio and earlier versions.
- Show the expiration date before deletion, provide a save control, and never delete saved audio. Derived text/history must state when its source audio has expired.

Acceptance: a voice note produces a source-linked analysis and topic connections while the original recording remains available and protected.

## 10. Canvas presentation frames

- Let the author draw/save a presentation frame containing canvas coordinates, bounds, zoom, and order.
- Present frames sequentially to guide an audience through the canvas.
- Show when later canvas edits make a saved frame empty, clipped, or misleading.
- Offer explicit re-fit/update while retaining the last saved frame definition.

Acceptance: a canvas can be presented as an ordered sequence of saved views, and edits never silently change the author's framing.

## 11. Settings insights and private analytics

- Show thought count, average capture length, commitment count, completion rate, and average completion time.
- Define denominators and missing-data behavior so the metrics are honest.
- Cross-user rankings are opt-in only. They require minimum cohort sizes, aggregation, anti-identification controls, a clear description of the compared population, and a reversible opt-out before implementation.

Acceptance: personal metrics are accurate and understandable; cross-user comparisons appear only after explicit consent and can be disabled without losing personal statistics.

## 12. Daily/weekly intelligence and external activity summaries

- Improve Day and Week calendar views with a compact summary distinct from Morning Digest.
- Add optional connected-source summaries such as flights, entertainment releases, fantasy activity, and other user-selected feeds.
- Each integration needs explicit connection authorization, source labeling, refresh/failure states, and controls to disconnect/delete imported data.

Acceptance: the calendar summary helps orient the user without mixing external information into commitments or captures without attribution.

## Delivery rule

Each numbered section is an epic, not one oversized PR. Ship the smallest complete vertical slice, validate it on a physical phone and desktop, preserve local/account data, run the full checks, obtain independent review, and use a reviewed PR. Advanced work must not bypass the existing confirmation, provenance, or recovery boundaries.
