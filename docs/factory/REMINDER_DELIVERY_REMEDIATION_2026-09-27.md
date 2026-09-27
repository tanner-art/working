# Reminder delivery stale-action remediation

## Finding

The active-reminder projection previously called the synchronous App state updater directly. A duplicate click or stale cross-device row reaches the workflow after its instruction is already handled or dismissed. The workflow correctly rejects that invalid transition, but the exception escaped the event handler and could crash the Review surface.

## Remediation

Each reminder row now records an in-flight action before invoking the callback, disables both actions while it is pending, and catches synchronous stale-state errors. The instruction and its audit history remain unchanged on failure; the visible, recoverable message asks the user to refresh and try again. A normal single handled or dismissed action continues to append exactly one lifecycle event and removes only the active projection.

## Evidence and rollback

Focused workflow tests cover normal handled/dismissed lifecycle transitions and a stale duplicate action that retains the first state and yields recoverable feedback. Roll back by reverting this bounded reminder delivery remediation together with its Reminder workflow/projection additions; no live data migration or notification provider state is changed.
