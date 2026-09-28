#!/usr/bin/env python3
"""Safe, report-only runtime accounting for explicitly supplied Factory logs.

This is intentionally not a dispatcher or persistence adapter.  It accepts only
paths passed by the caller, keeps allowlisted lifecycle fields, and reports
unknown/partial coverage rather than guessing at provider or child timing.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _time(value: Any) -> float | None:
    if not isinstance(value, str): return None
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError: return None

def _read(path: Path) -> Iterable[dict[str, Any]]:
    """Read JSONL only from a caller-supplied file, ignoring malformed rows."""
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict): yield item

def collect(provider_paths: Iterable[str] = (), coordinator_paths: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Normalize a deliberately tiny allowlist; no transcript/prompt fields escape."""
    result: list[dict[str, Any]] = []
    for raw in provider_paths:
        for item in _read(Path(raw)):
            kind = item.get("type")
            # Codex JSONL supplies IDs but commonly no per-line timestamp.
            if kind in {"thread.started", "item.completed", "turn.completed"}:
                result.append({"source": "codex", "type": kind, "sessionId": item.get("thread_id") if isinstance(item.get("thread_id"), str) else None, "parentId": item.get("parent_id") if isinstance(item.get("parent_id"), str) else None, "timestamp": item.get("timestamp") if _time(item.get("timestamp")) is not None else None, "durationMs": item.get("duration_ms") if isinstance(item.get("duration_ms"), (int, float)) else None})
            # Claude result logs provide a session and optional bounded duration.
            elif kind == "result" or isinstance(item.get("session_id"), str):
                result.append({"source": "claude", "type": "result", "sessionId": item.get("session_id") if isinstance(item.get("session_id"), str) else None, "parentId": item.get("parent_session_id") if isinstance(item.get("parent_session_id"), str) else None, "timestamp": item.get("timestamp") if _time(item.get("timestamp")) is not None else None, "durationMs": item.get("duration_ms") if isinstance(item.get("duration_ms"), (int, float)) else None})
    for raw in coordinator_paths:
        for outer in _read(Path(raw)):
            payload = outer.get("payload") if isinstance(outer.get("payload"), dict) else {}
            if payload.get("type") not in {"task_started", "task_complete"}: continue
            result.append({"source": "coordinator", "type": payload["type"], "sessionId": payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else None, "parentId": payload.get("parent_id") if isinstance(payload.get("parent_id"), str) else None, "timestamp": outer.get("timestamp") if _time(outer.get("timestamp")) is not None else None, "durationMs": payload.get("duration_ms") if isinstance(payload.get("duration_ms"), (int, float)) else None})
    return result

def report(events: Iterable[dict[str, Any]], *, window_start: str | None = None, window_end: str | None = None) -> dict[str, Any]:
    """Deduplicate replayed envelopes and calculate only proven coordinator turns.

    Provider events without both real timestamps are reported as unavailable;
    duration_ms is never converted into invented child start/end bounds.
    """
    supplied = list(events)
    unique, seen = [], set()
    for event in supplied:
        key = (event.get("source"), event.get("type"), event.get("sessionId"), event.get("parentId"), event.get("timestamp"), event.get("durationMs"))
        if key not in seen: seen.add(key); unique.append(event)
    starts: dict[str, float] = {}
    coordinator_seconds = 0.0
    for event in unique:
        if event["source"] != "coordinator" or not event.get("sessionId"): continue
        when = _time(event.get("timestamp"))
        if event["type"] == "task_started" and when is not None: starts[event["sessionId"]] = when
        elif event["type"] == "task_complete":
            if isinstance(event.get("durationMs"), (int, float)): coordinator_seconds += max(0, event["durationMs"]) / 1000
            elif when is not None and event["sessionId"] in starts: coordinator_seconds += max(0, when - starts[event["sessionId"]])
    provider = [event for event in unique if event["source"] in {"codex", "claude"}]
    return {"window": {"startAt": window_start, "endAt": window_end}, "eventCount": len(unique), "coordinatorTurnSeconds": coordinator_seconds if any(event["source"] == "coordinator" for event in unique) else None, "identifiableWaitingSeconds": None, "providerChildSeconds": None, "providerChildTelemetry": "unavailable: supplied provider logs do not prove child start/end intervals", "providerEventCount": len(provider), "replayedEventCount": len(supplied) - len(unique)}

def main() -> int:
    parser = argparse.ArgumentParser(description="Report-only Factory runtime accounting from supplied sanitized JSONL logs")
    parser.add_argument("--provider-log", action="append", default=[])
    parser.add_argument("--coordinator-log", action="append", default=[])
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    args = parser.parse_args()
    events = collect(args.provider_log, args.coordinator_log)
    print(json.dumps(report(events, window_start=args.window_start, window_end=args.window_end), sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
