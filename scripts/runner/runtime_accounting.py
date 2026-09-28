#!/usr/bin/env python3
"""Report-only accounting for explicitly supplied, sanitized runtime JSONL."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def _time(value: Any) -> float | None:
    if not isinstance(value, str): return None
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError: return None


def _read(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try: row = json.loads(line)
            except json.JSONDecodeError: continue
            if isinstance(row, dict): yield row


def collect(provider_paths: Iterable[str] = (), coordinator_paths: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Keep only lifecycle IDs/times; prompts, tool args, env and secrets never escape."""
    out: list[dict[str, Any]] = []
    for raw in provider_paths:
        for row in _read(Path(raw)):
            kind = row.get("type")
            if kind in {"thread.started", "item.completed", "turn.completed"}:
                out.append({"source": "codex", "type": kind, "sessionId": row.get("thread_id") if isinstance(row.get("thread_id"), str) else None, "parentId": row.get("parent_id") if isinstance(row.get("parent_id"), str) else None, "invocationId": row.get("invocation_id") if isinstance(row.get("invocation_id"), str) else None, "timestamp": row.get("timestamp") if _time(row.get("timestamp")) is not None else None, "durationMs": row.get("duration_ms") if isinstance(row.get("duration_ms"), (int, float)) else None})
            elif kind == "result" or isinstance(row.get("session_id"), str):
                out.append({"source": "claude", "type": "result", "sessionId": row.get("session_id") if isinstance(row.get("session_id"), str) else None, "parentId": row.get("parent_session_id") if isinstance(row.get("parent_session_id"), str) else None, "invocationId": row.get("invocation_id") if isinstance(row.get("invocation_id"), str) else None, "timestamp": row.get("timestamp") if _time(row.get("timestamp")) is not None else None, "durationMs": row.get("duration_ms") if isinstance(row.get("duration_ms"), (int, float)) else None})
    for raw in coordinator_paths:
        for row in _read(Path(raw)):
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if payload.get("type") in {"task_started", "task_complete"}:
                out.append({"source": "coordinator", "type": payload["type"], "sessionId": payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else None, "parentId": payload.get("parent_id") if isinstance(payload.get("parent_id"), str) else None, "invocationId": payload.get("invocation_id") if isinstance(payload.get("invocation_id"), str) else None, "timestamp": row.get("timestamp") if _time(row.get("timestamp")) is not None else None, "durationMs": payload.get("duration_ms") if isinstance(payload.get("duration_ms"), (int, float)) else None})
    return out


def _union(intervals: list[tuple[float, float]]) -> float:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if end <= start: continue
        if merged and start <= merged[-1][1]: merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else: merged.append((start, end))
    return sum(end - start for start, end in merged)


def report(events: Iterable[dict[str, Any]], *, window_start: str | None = None, window_end: str | None = None) -> dict[str, Any]:
    supplied = list(events); unique: list[dict[str, Any]] = []; seen = set(); duplicate_unknown = False
    for event in supplied:
        # Explicit invocation/session identity permits wrapper/provider dedup. Do not
        # use coincident timestamps: distinct concurrent child sessions are additive.
        identity = event.get("invocationId") or event.get("sessionId")
        if identity is None:
            duplicate_unknown = True; unique.append(event); continue
        key = (identity, event.get("type"), event.get("timestamp"), event.get("durationMs"))
        if key not in seen: seen.add(key); unique.append(event)
    starts: dict[str, float] = {}; coordinator = 0.0; provider_intervals: list[tuple[float, float]] = []; provider_seconds = 0.0; provider_partial = 0
    for event in unique:
        when = _time(event.get("timestamp")); session = event.get("sessionId")
        if event.get("source") == "coordinator":
            if event.get("type") == "task_started" and isinstance(session, str) and when is not None: starts[session] = when
            elif event.get("type") == "task_complete":
                if isinstance(event.get("durationMs"), (int, float)): coordinator += max(0, event["durationMs"]) / 1000
                elif isinstance(session, str) and when is not None and session in starts: coordinator += max(0, when - starts[session])
            continue
        if event.get("source") in {"codex", "claude"}:
            duration = event.get("durationMs")
            if when is None or not isinstance(duration, (int, float)) or duration < 0: provider_partial += 1; continue
            interval = (when - duration / 1000, when); provider_intervals.append(interval); provider_seconds += duration / 1000
    providers = [e for e in unique if e.get("source") in {"codex", "claude"}]
    return {"window": {"startAt": window_start, "endAt": window_end}, "eventCount": len(unique), "coordinatorTurnSeconds": coordinator if any(e.get("source") == "coordinator" for e in unique) else None, "identifiableWaitingSeconds": None, "providerChildSeconds": provider_seconds if provider_intervals and not provider_partial else None, "providerChildUnionSeconds": _union(provider_intervals) if provider_intervals else None, "providerPartialIntervalCount": provider_partial, "providerChildTelemetry": "partial: supplied provider intervals are incomplete" if provider_partial else "disabled: no provider child intervals supplied" if not providers else "observed", "providerEventCount": len(providers), "replayedEventCount": len(supplied) - len(unique), "duplicateCoverage": "unknown" if duplicate_unknown else "identified"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Report-only Factory runtime accounting")
    parser.add_argument("--provider-log", action="append", default=[]); parser.add_argument("--coordinator-log", action="append", default=[]); parser.add_argument("--window-start"); parser.add_argument("--window-end")
    args = parser.parse_args(); print(json.dumps(report(collect(args.provider_log, args.coordinator_log), window_start=args.window_start, window_end=args.window_end), sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
