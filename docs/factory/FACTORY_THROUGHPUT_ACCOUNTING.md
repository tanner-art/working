# Factory throughput accounting

`scripts/runner/runtime_accounting.py` is a report-only collector. It reads only
the JSONL paths supplied on its command line, retaining event kind, timestamp,
session/invocation identifiers, parent linkage, and implementation/review kind.
It never scans a home directory, credentials, or prompts, and it does not write
the Registry or enable delegation.

After both control-plane changes are integrated, the coordinator may install a
non-live reporting hook such as:

```sh
python3 scripts/runner/runtime_accounting.py /explicit/provider-events.jsonl \
  --from 2026-09-27T00:00:00Z --to 2026-09-27T08:00:00Z
```

The report clips intervals to the requested window, unions overlapping parent
attempts, keeps identifiable child intervals additive, and reports waits only
when matching supplied events exist. Open intervals and absent child telemetry
remain unknown/disabled. Durations are observed wall-clock intervals, not
billable thinking time. Current A/B multi-agent policy is reported as disabled
or not observed; this module never creates child work.
