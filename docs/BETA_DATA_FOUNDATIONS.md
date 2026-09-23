# Beta data foundations

This slice defines serializable, UI-independent models for private personal statistics,
nested organization, collaboration settings and external-calendar setup intent. It does
not change `App.tsx`, global styles, the current account payload or any provider connection.

## Personal statistics

`src/personalStats.ts` calculates a snapshot from the validated canonical `PersistedState`.
The snapshot is explicitly account-owner-only, disables sharing, and does not calculate
rankings. It includes capture, current-object, completion, Review, canvas and recent-activity
counts, plus the source IDs used for provenance. A zero-action completion percentage is
`null`, not an invented zero-performance score.

The calculation is read-only. UI should calculate it after account data is loaded and keep
the result inside the signed-in account boundary. Ranking, comparison, public profiles and
analytics upload require a separate opt-in product decision and are outside this model.

## Nested folders and saved canvases

`src/organization.ts` stores folders as parent references, so nesting has no product depth
limit. Creation and movement reject missing parents, duplicate sibling names, cycles, and
placement inside a deleted folder. Canvas-file records hold identity, title, folder location
and capture references; they do not duplicate canvas content or immutable captures.

Folder and canvas deletion is a recoverable state transition:

1. Build a deletion preview. The preview lists every affected folder and canvas.
2. Show that impact and the returned exact confirmation text to the user.
3. Only after the user confirms, call the deletion function with the unchanged preview,
   exact confirmation text, timestamp and a unique operation ID.
4. The function recomputes impact and rejects stale previews before adding tombstones.
5. Recovery clears only tombstones from that operation. Capture references stay unchanged.

Deleting a folder tombstones its active descendants and their active canvas files together.
Nothing in this module permanently purges data. A future retention/purge policy needs its own
review, and must continue to protect captures referenced by interpretations.

## Sharing and calendar attendees

`src/collaborationSettings.ts` provides two honest draft models:

- a Threadline product-invite draft with `delivery: not-sent`;
- a calendar-attendee draft with `featureStatus: under-construction` and
  `invitation: not-created`.

Both normalize and validate recipient email addresses. Neither model has a sent state or a
network operation, so the Settings UI cannot accidentally claim an invitation was delivered.
The attendee section should render the exported under-construction copy and disabled send
behavior until a separately reviewed scheduling/invitation service exists.

## Google and Apple calendar foundation

`src/calendarConnectors.ts` describes Google Calendar and Apple Calendar as foundation-only
providers. A user can record a preferred provider and setup intent, but every connector
remains `not-connected`; sync and attendee invitations remain disabled. No OAuth, CalDAV,
credentials, access tokens, calendar IDs, events or invitations are created or stored.

Provider integration later needs separate security and lifecycle work: authorization,
encrypted secret handling outside the account document, scopes, revocation, sync cursors,
conflict handling, event provenance, and explicit invitation confirmation.

## UI and account integration docket

The later UI lane can integrate these modules without changing their safety rules:

1. Add a Stats view that calls `calculatePersonalStats` with the account's canonical model.
   Keep its privacy label visible; do not add rankings or sharing controls.
2. Render active folders as a recursive tree and active canvas files under their `folderId`.
   Use the create/move functions instead of editing parent IDs directly.
3. For delete actions, render the preview counts and require the exact confirmation text.
   Add a Recovery view that calls the matching restore function. Do not hard-delete records.
4. Render the Threadline invite as a draft-only setting. Render calendar attendees as under
   construction and never turn a draft into an invitation.
5. Render Google and Apple choices from `externalCalendarProviders`; requesting setup should
   update setup intent while continuing to say that the provider is not connected.
6. Introduce a versioned account-envelope migration that adds `organization`,
   `collaborationSettings`, and `calendarConnectors` beside the existing model/settings/digest
   fields. Validate each section with its exported validator before saving. This integration
   belongs in the account-storage lane so local import, revision conflicts and cross-device
   behavior remain one coherent transaction.

Until step 6 lands, these modules are domain foundations and are not persisted or visible in
the current application. Personal stats can already be calculated from existing account data;
the other states need the versioned account-envelope integration before UI launch.
