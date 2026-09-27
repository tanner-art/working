# Factory throughput accounting

The Registry projection is the one source consumed by both the hosted Control
Center and the local runner dashboard. It derives a conservative feature stage
and a recent 24-hour attempt window from authoritative Registry attempts.
"No worker attempt" means uncovered wall-clock time in that window, not idle
time. Open, missing, or malformed attempt bounds are counted as partial and
remain unknown.

| Criterion | Implementation | Focused evidence |
| --- | --- | --- |
| One stage source for both views | `control_center_projection.py` feature `stage`; React and local HTML only render it | Registry projection and UI contract tests |
| Review / retry / accepted counts | `factory.throughput` | Projection contract validation |
| Additive vs union timing | attempt intervals are summed by type; union is separately merged | Projection interval calculations |
| Coordinator timing | nullable unless supplied coordinator JSONL proves a turn | `runtime_accounting.py` |
| Provider child timing | report-only collector retains allowlisted IDs/times; missing child bounds remain unavailable | `runtime_accounting.py` |

Example (paths are supplied explicitly; the collector never searches a home,
state, or credential directory):

```sh
python3 scripts/runner/runtime_accounting.py \
  --provider-log /tmp/scoped-codex.jsonl \
  --provider-log /tmp/scoped-claude.jsonl \
  --coordinator-log /tmp/scoped-coordinator.jsonl \
  --window-start 2026-09-27T09:00:00Z --window-end 2026-09-27T10:00:00Z
```

Codex stream rows commonly have no per-line timestamp. They are retained only
as ID/type observations and do not create invented child intervals. Current
A/B lanes disable multi-agent fanout, so child compute is explicitly reported
as unavailable rather than zero. A coordinator may install a report-only hook
after the relevant Registry changes are integrated; this package performs no
persistence, dispatch, Registry status writes, or delegation.
