# Factory throughput accounting

The Registry projection is the only stage and throughput source for both dashboard
surfaces. Its recent 24-hour window clips every event-derived count. Incomplete,
open, or malformed intervals are partial, never idle or zero.

| Criterion | Implementing function | Regression coverage | Actual validation |
| --- | --- | --- | --- |
| Conservative lifecycle stage and reason | `_feature_stage` | `test_control_center_projection.py` | Passed non-loopback focused class (2026-09-27) |
| Windowed attempts, review waits and retries | `_throughput` | `test_control_center_projection.py` | Passed non-loopback focused class (2026-09-27) |
| Wrapper/provider identity dedup; concurrent child arithmetic | `runtime_accounting.report` | `test_runtime_accounting.py` | Passed: 3 tests (2026-09-27) |
| Hosted schema and rendering | `parseFactoryProjection`, `PublicBuildDashboard` | `factoryControl.test.ts`, `PublicBuildDashboard.test.tsx` | Passed: focused Vitest (46 tests, 2026-09-27) |

`acceptedCount` is `null` unless a Registry snapshot explicitly supplies exact
integration/acceptance evidence. A DONE feature or an unrelated approval is not
acceptance proof. Review wait means requested-to-decision, while an active reviewer
is separately marked requested-to-observation. Coordinator time is separate from
worker sums and union. Provider child collection is optional and uses only explicit
log paths; it never reads prompts, tool arguments, environment values, or secrets.

Remaining unknowns: the current Registry snapshot does not include a general
integration evidence record, so accepted totals are deliberately unavailable; a
hosted signed transport and actual optional child collector remain operational work.
