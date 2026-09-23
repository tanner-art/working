# Friends-and-family beta: one-week runbook

This is a one-week pilot for the current Threadline MVP. It is a usability and
reliability check, not a production launch. Use the hosted build supplied by the
coordinator and keep real secrets, credentials, and private capture content out of
feedback channels.

## Before the week starts

- Install the hosted app as a PWA if your device supports installation. Otherwise,
  keep the hosted URL bookmarked. Do not uninstall an existing installation or clear
  site data during the pilot.
- Start with a fresh test account only if the coordinator asks you to test hosted
  account behavior. Existing local captures are valuable test data: signing in,
  signing out, refreshing, or installing must not delete them.
- If using account storage, remember the boundary: sign-in alone does not copy local
  data. In Settings → Data, choose an explicit local-data copy or account-data load
  only when asked, and export unsaved work before loading another account snapshot.
- Refresh once before the first session and after a release notice. A normal refresh
  should preserve local captures and the current saved workspace. Never use browser
  storage-clearing tools as a troubleshooting step during this pilot.

## Sign-in checks

Threadline supports email sign-in through either of the two paths below when the
hosted provider is configured:

1. Enter the test email and request a sign-in email.
2. Either open the email link in the browser, or enter the numeric code from the same
   email in the app. The code field accepts 6–10 digits; use the exact code received.
3. Confirm the app reports the signed-in state. Refresh once to check session restore.
4. Sign out only as a deliberate test, then confirm the local workspace is still
   available. Account data and device-local data are separate until an explicit copy
   or load action.

If a link is expired or a code fails, request a new email and retry once. Do not share
the link, code, email contents, or screenshots containing them. Report only the time,
path (link or code), device/browser, and the visible error.

## Ten-minute first-run path

Use a harmless, non-private sentence such as “Try a paper prototype next week” and
follow this path. The purpose is to exercise the whole visible loop, not to validate
unfinished automation.

| Minute | Surface | What to do | Expected observation |
| --- | --- | --- | --- |
| 0–2 | Capture | Capture the sample text and note the original wording. Refresh once if practical. | The capture remains present; later interpretation does not replace the source wording. |
| 2–4 | Review | Open the proposed interpretation, inspect its summary/kind/confidence, and make an explicit confirmation or correction. | Uncertain or consequential meaning stays reviewable. A suspected action is not treated as confirmed merely because confidence is high. |
| 4–5 | Calendar | Open Calendar and inspect the resulting date/commitment presentation. | Treat deadlines, commitments, and scheduled events as distinct. Do not expect a promise to invent a calendar event. |
| 5–7 | Canvas | Open Canvas/Bank, open the existing canvas or create a named test canvas, add or move one text node, then leave and reopen it. | The canvas and its saved geometry remain intact. Keep the test content non-private. |
| 7–9 | Organize | Open Organize and locate the captured item; inspect its current grouping/status and history where available. | Organization is a view of the same saved model; original capture evidence and later revisions remain recoverable. |
| 9–10 | Recovery note | Refresh, briefly go offline if safe, return online, and record any visible error without reloading over unsaved work. | The app either remains usable from its cached shell or clearly reports the unavailable operation. |

Do not interpret a missing future view, a placeholder, or a disabled control as a
failure of the current path. Record it as a limitation instead. In particular,
provider-backed interpretation is not enabled for this pilot; the built-in
deterministic interpreter is the behavior to test.

## Daily smoke check

Run this once per day in under five minutes, using test content or content you are
comfortable preserving locally:

- Launch the installed app or hosted URL and confirm the shell loads.
- Capture one short sentence, open Review, and confirm that its original wording is
  still visible after interpretation.
- Open Calendar, Canvas/Bank, and Organize; verify each loads without a blank state or
  unexpected loss of the test item.
- Reopen the named test canvas and confirm the last saved edit is present.
- Refresh once. If signed in, confirm the session state; if testing account data,
  perform only the explicitly requested load/import operation.
- Record device, browser/PWA, online/offline state, build date if shown, and pass or
  fail. Do not attach capture text or screenshots of private content.

## Deterministic versus provider-backed interpretation

For this beta, interpretation should be understood as deterministic, local product
behavior: the same input and app version should produce the same kind of suggestion,
confidence/rationale, and Review outcome without a network request to an AI provider.
Small changes after an edit or explicit re-review may be expected; unexplained
provider-style variability is not evidence that a hosted AI feature is live.

Provider-backed interpretation would require a configured server-only provider key,
successful endpoint checks, Preview evaluation, and explicit promotion. That work is
not complete here. Do not report a network-generated result as a shipped feature, and
do not paste prompts, keys, response payloads, or private captures into feedback.

## Feedback without exposing private captures

Use the agreed private feedback channel and report:

- date/time and timezone;
- device model, OS, browser or installed PWA, and online/offline state;
- the surface and action (for example, “Review → confirm suggestion”);
- expected result versus observed result;
- whether it reproduced after one refresh;
- a short sanitized test label such as `sample-capture-3`, never the capture text.

For a visual issue, describe the control, location, and visible error. If a private
capture is necessary to reproduce the problem, keep it on the device and ask the
coordinator for a safe redaction path; do not upload it to a general chat or issue.

## Offline and PWA update recovery

- Offline use is for checking the cached shell and local work only. Network-dependent
  sign-in, account reads/writes, and other provider operations may fail or remain
  unavailable.
- If the app is blank or appears stale, return online and do one normal browser/PWA
  refresh. Wait for it to finish before trying the action again.
- If an update still does not appear, close and reopen the installed app, then revisit
  the hosted URL in the browser. Do not uninstall the PWA, clear site data, or delete
  local storage during the beta.
- Before loading account data or changing devices, export unsaved work if the UI
  offers that option. A stale account snapshot or revision conflict should stop and
  offer recovery; it must not silently overwrite local work.
- Report the recovery steps and whether local captures returned. Do not repeatedly
  retry a save when the app reports an offline, permission, or stale-revision error.

## Known limitations

- This is still an MVP with a local-first browser/PWA experience. A signed-in session
  does not by itself migrate or synchronize local captures.
- Account persistence is explicit snapshot import/load, not realtime collaboration;
  two devices must explicitly load the latest account version, and conflicts require
  recovery rather than automatic merge.
- The interpreter is deterministic and provider-backed AI interpretation is disabled.
- Calendar does not make every commitment a scheduled event; broader calendar
  planning and event-entry behavior should not be assumed live.
- Durable capture/revision boundaries and some future semantic distinctions remain
  incomplete in the current MVP, even though the product preserves available source
  text, history, and canvas state within its current model.
- Voice capture, advanced canvas gestures/zoom, richer organization/search, adaptive
  planning, notifications, and broad production email delivery are not beta promises.
- Real-device sign-in, two-account isolation, and two-device sync still require the
  coordinator’s independent hosted validation. Treat a successful local smoke test
  as useful evidence, not certification.

## Stop and escalate

Stop the test and contact the coordinator immediately if any of these occur:

- a capture, canvas edit, or saved local workspace disappears unexpectedly;
- one account can see or change another account’s data, or an account load appears
  without an explicit user action;
- a sign-in link or numeric code is exposed, sent to the wrong person, or appears in
  a screenshot/log;
- a save, load, refresh, or conflict path would overwrite unsaved work;
- the app reports a permissions/security error, repeated data corruption, or an
  unrecoverable blank screen;
- an external notification, calendar change, or other consequential action occurs
  without explicit confirmation;
- a provider-backed result appears unexpectedly, or the app requests a credential or
  secret that the runbook did not provide.

Do not “fix” these by clearing storage, changing environment variables, retrying
destructive actions, or inventing credentials. Preserve the visible error and the
sanitized reproduction details.

## End-of-week success scorecard

The coordinator should mark each row with evidence from the daily notes. A beta is
successful only when no stop criterion occurred and every required row is either
passed or explicitly accepted as a known limitation.

| Area | Success measure | Evidence |
| --- | --- | --- |
| Install/refresh | At least one normal refresh and, where applicable, PWA reopen preserve local work. | |
| Sign-in link | Test users can complete the email-link path and recover from one expired/invalid attempt without exposing the link. | |
| Numeric code | Test users can complete the 6–10 digit code path and recover by requesting a new email. | |
| Local preservation | Sign-in, sign-out, refresh, and offline recovery do not delete local captures; import/load is always explicit. | |
| First run | Capture → Review → Calendar → Canvas → Organize completed on the agreed device/browser. | |
| Daily reliability | Daily smoke checks complete for the planned days with issues recorded and triaged. | |
| Interpretation boundary | Testers can distinguish deterministic local suggestions from unavailable provider-backed AI and report no false claim that AI is live. | |
| Privacy | Feedback contains no private capture content, credentials, sign-in links, or numeric codes. | |
| Recovery | At least one offline/PWA recovery exercise is documented without clearing storage or losing work. | |
| Escalation | Any stop event was halted promptly, preserved safely, and handed to the coordinator. | |
