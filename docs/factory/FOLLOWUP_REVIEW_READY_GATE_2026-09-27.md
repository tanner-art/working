# Follow-up Review READY Gate — 2026-09-27

## Defect

On canonical `main22e7ec1`, `TASK329` is `BLOCKED` after its scoped test
implementation failed, while its dependent assurance review `TASK330` remains
`READY` with zero attempts. `SQLiteRegistry.register_followup_review` treated
every `READY` package as canary-contending work. It therefore rejected lawful
acceptance review registration for original `TASK173`, even though `TASK330`
cannot be claimed while its only declared parent dependency is `BLOCKED`.

## Scope and invariant

The follow-up registration exclusivity query now disregards exactly one case:
a `READY` `REVIEW` package with exactly one declared dependency, where that
dependency is a `PARENT` in `BLOCKED` state. All `ACTIVE` packages remain
exclusive. `READY` parents, independently eligible reviews, reviews with zero
or multiple dependencies, and reviews whose dependency has any other kind or
state remain exclusive. Paused control, kill switch, ownership, attempt, and
runtime preconditions are unchanged.

This change does not modify live SQLite data, task status/history/dependencies,
or scheduler claim gates. In particular, it does not complete, remove, or
otherwise alter `TASK330`.

## Focused tests

`scripts/factory_registry/test_registry.py` retains
`test_followup_registration_restores_global_ready_active_exclusivity`, proving
ordinary `READY` and `ACTIVE` work still returns `CANARY_NOT_EXCLUSIVE`. The
new blocked-parent fixture registers a lawful follow-up review successfully,
then verifies the blocked-parent review remains `READY` and retains its
original dependency.

## Rollback

Revert the follow-up registration predicate and its focused regression test.
No migration or persisted-data rollback is required.
