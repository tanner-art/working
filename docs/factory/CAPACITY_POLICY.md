# Factory capacity policy

This policy is provider-neutral. Provider and model names are diagnostic data;
they do not grant eligibility. The Registry stores the normalized observations
and package classification used by the scheduler.

## Percentage-observed workers

Every configured percentage scope must be fresh and valid. Missing, stale,
future, malformed, or unmapped scopes constrain the worker. The most
restrictive fresh scope governs a new dispatch:

- below 90%: `NORMAL`; new eligible work may start;
- 90% to below 95%: `CAUTION`; do not start a substantial or uncertain parent;
- 95% to below 98%: `CHECKPOINT`; healthy in-flight work may reach a clean
  commit/push checkpoint, but no substantial or uncertain parent may start;
- 98% or above: `HARD_STOP`; only emergency recovery or a very small, bounded
  ASSURANCE package may start.

Crossing 95% does not interrupt healthy work. A live runner invocation is not
terminated by a later observation; it checkpoints and stops further
substantial dispatch. An actual provider failure can still end the invocation.

Package policy is explicit Registry data:

- `capacity_size`: `VERY_SMALL`, `SMALL`, or `SUBSTANTIAL`;
- `capacity_risk`: `BOUNDED`, `UNCERTAIN`, or `EMERGENCY_RECOVERY`.

The conservative migration defaults are `SUBSTANTIAL` and `UNCERTAIN`.
Provider/model selection never substitutes for this classification.

## Provider-signal workers

A worker may use `provider_signal` capacity mode when its provider supplies no
programmatic percentage. It is normally eligible when the observation is fresh,
service state is healthy, authentication is valid, a live invocation succeeds,
and `limit_signal` is `NONE`.

Observed `RATE_LIMIT`, `EXHAUSTION`, `THROTTLING`, or
`CAPACITY_LAUNCH_FAILURE` signals constrain the worker. They are retained as
observations for later calibration. No percentage or ceiling is inferred from
their absence.

## Orchestra reserve

Orchestra retains at least 20% in every configured percentage scope. Missing or
non-percentage Orchestra evidence cannot prove that reserve and fails closed.

## Authority boundary

The installed runner remains the live dispatcher until controlled restart is
separately approved. Shadow decisions remain read-only. This policy change does
not authorize broad dispatch, registry cutover, service restart, or queue
mutation.
