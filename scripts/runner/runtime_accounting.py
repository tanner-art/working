#!/usr/bin/env python3
"""Report-only accounting for explicitly supplied, sanitized session logs.

This module does not discover files, persist data, start children, or ingest
prompts.  A coordinator may invoke it after writing an allowlisted JSONL log:
``python scripts/runner/runtime_accounting.py LOG --from ISO --to ISO``.
Supported events contain only ``kind``, ``at``, ``session_id``, optional
``parent_session_id`` and optional ``attempt_kind`` (implementation/review).
``multi_agent`` is reported as disabled unless actual child identifiers and
intervals are supplied.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_KINDS = {"session_started", "session_completed", "task_started", "task_complete", "wait_started", "wait_complete"}
_ALLOWED = {"kind", "at", "session_id", "parent_session_id", "attempt_kind", "invocation_id", "multi_agent"}

def _time(value: Any) -> datetime | None:
    if not isinstance(value, str): return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None

def _clip(start: datetime, end: datetime, lower: datetime, upper: datetime) -> tuple[datetime, datetime] | None:
    start, end = max(start, lower), min(end, upper)
    return (start, end) if end > start else None

def _union_seconds(intervals: Iterable[tuple[datetime, datetime]]) -> float:
    ordered = sorted(intervals)
    total = 0.0; current: tuple[datetime, datetime] | None = None
    for interval in ordered:
        if current is None: current = interval; continue
        if interval[0] <= current[1]: current = (current[0], max(current[1], interval[1]))
        else: total += (current[1] - current[0]).total_seconds(); current = interval
    return total + ((current[1] - current[0]).total_seconds() if current else 0.0)

def collect_events(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Read only caller-supplied JSONL paths and retain the tiny allowlist."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for raw_path in paths:
        for line in Path(raw_path).read_text(encoding="utf-8").splitlines():
            try: raw = json.loads(line)
            except json.JSONDecodeError: continue
            if not isinstance(raw, dict) or raw.get("kind") not in _KINDS or _time(raw.get("at")) is None or not isinstance(raw.get("session_id"), str): continue
            event = {key: raw[key] for key in _ALLOWED if key in raw and isinstance(raw[key], (str, bool))}
            # A runner wrapper and provider event may carry the same session or
            # invocation identity.  Treat either identity as one observation.
            key = (event["kind"], event["at"], event.get("invocation_id") or event["session_id"], None)
            if key not in seen: seen.add(key); result.append(event)
    return sorted(result, key=lambda item: (item["at"], item["kind"], item["session_id"]))

def report(events: Iterable[dict[str, Any]], *, start: str, end: str) -> dict[str, Any]:
    lower, upper = _time(start), _time(end)
    if lower is None or upper is None or upper <= lower: raise ValueError("window timestamps must be ordered ISO-8601 values")
    starts: dict[tuple[str, str], tuple[datetime, str | None, str]] = {}; intervals: list[tuple[str, str | None, str, datetime, datetime]] = []
    waits: list[tuple[datetime, datetime]] = []
    for event in sorted(events, key=lambda item: str(item.get("at", ""))):
        at = _time(event.get("at")); session = event.get("invocation_id") or event.get("session_id"); kind = event.get("kind")
        if at is None or not isinstance(session, str) or kind not in _KINDS: continue
        category = "wait" if kind.startswith("wait_") else "session" if kind.startswith("session_") else "task"
        key = (session, category)
        if kind.endswith("started"):
            starts[key] = (at, event.get("parent_session_id") if isinstance(event.get("parent_session_id"), str) else None, event.get("attempt_kind") if event.get("attempt_kind") in {"implementation", "review"} else "unknown")
        elif kind.endswith("completed") or kind.endswith("complete"):
            opened = starts.pop(key, None)
            if opened is not None:
                opened_at, parent_session, attempt_kind = opened
                clipped = _clip(opened_at, at, lower, upper)
                if clipped:
                    if category == "wait": waits.append(clipped)
                    else: intervals.append((session, parent_session, attempt_kind, *clipped))
    # A child interval is additive only when it has its own session ID; parent
    # wrapper intervals are unioned independently, preventing double counting.
    parent_intervals = [(a, b) for _, parent, _, a, b in intervals if parent is None]
    child_intervals = [(a, b) for _, parent, _, a, b in intervals if parent is not None]
    implementation = _union_seconds((a, b) for _, _, kind, a, b in intervals if kind == "implementation")
    review = _union_seconds((a, b) for _, _, kind, a, b in intervals if kind == "review")
    parent_sum = sum((b-a).total_seconds() for a, b in parent_intervals)
    union = _union_seconds(parent_intervals)
    return {
        "window": {"start": lower.isoformat().replace("+00:00", "Z"), "end": upper.isoformat().replace("+00:00", "Z")},
        "parentAttemptSeconds": parent_sum, "parentUnionSeconds": union,
        "knownAdditiveChildSeconds": _union_seconds(child_intervals),
        "implementationSeconds": implementation, "reviewSeconds": review,
        "coordinatorTurnSeconds": _union_seconds((a, b) for session, _, _, a, b in intervals if session.startswith("coordinator")),
        "identifiableWaitSeconds": _union_seconds(waits),
        "noAttemptSeconds": max(0.0, (upper-lower).total_seconds() - union),
        "billableThinkingTime": None,
        "childTelemetry": "observed" if child_intervals else "unknown_or_disabled",
        "multiAgent": "disabled_or_not_observed",
        "note": "Durations are observed intervals, not billable thinking time.",
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Report sanitized runtime accounting from supplied JSONL paths")
    parser.add_argument("logs", nargs="+"); parser.add_argument("--from", dest="start", required=True); parser.add_argument("--to", dest="end", required=True)
    args = parser.parse_args(); print(json.dumps(report(collect_events(args.logs), start=args.start, end=args.end), sort_keys=True))

if __name__ == "__main__": main()
