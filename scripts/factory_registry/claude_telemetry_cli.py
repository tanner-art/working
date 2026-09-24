"""Ingest Claude Code structured output into the Factory Registry ledger."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .claude_telemetry import (
    ClaudeTelemetryError,
    parse_claude_json,
    parse_claude_stream_json,
    parse_claude_transcript,
)
from .repository import RegistryError
from .sqlite_registry import SQLiteRegistry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: str) -> bytes:
    return sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--invocation-id")
    parser.add_argument("--package-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--task-completed", action="store_true")
    parser.add_argument("--review-completed", action="store_true")


def _entry_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "worker_id": args.worker,
        "account_id": args.account,
        "invocation_id": args.invocation_id,
        "package_id": args.package_id,
        "attempt_id": args.attempt_id,
        "task_completed": args.task_completed,
        "review_completed": args.review_completed,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append Claude invocation telemetry to the Factory Registry"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest-json", "ingest-stream-json"):
        command = commands.add_parser(name)
        _common(command)
        command.add_argument("input", help="structured output file, or - for stdin")
        command.add_argument("--observed-at", default=None)
        command.add_argument("--model")
        command.add_argument("--cli-version")
    transcript = commands.add_parser("ingest-transcript")
    _common(transcript)
    transcript.add_argument("input", type=Path)
    transcript.add_argument(
        "--transcript-root",
        required=True,
        type=Path,
        help="verified Claude projects directory containing the transcript",
    )
    analytics = commands.add_parser("analytics")
    analytics.add_argument("--database", required=True, type=Path)
    analytics.add_argument("--worker", required=True)
    analytics.add_argument("--observed-at", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    registry = SQLiteRegistry(args.database)
    registry.initialize()
    try:
        if args.command == "analytics":
            print(
                json.dumps(
                    registry.usage_analytics(
                        args.worker, observed_at=args.observed_at or _now()
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "ingest-transcript":
            entry = parse_claude_transcript(
                args.input,
                transcript_root=args.transcript_root,
                **_entry_kwargs(args),
            )
        else:
            raw = _read(args.input)
            parse = (
                parse_claude_json
                if args.command == "ingest-json"
                else parse_claude_stream_json
            )
            entry = parse(
                raw,
                observed_at=args.observed_at or _now(),
                model=args.model,
                cli_version=args.cli_version,
                **_entry_kwargs(args),
            )
        write = registry.record_usage(entry)
        print(
            json.dumps(
                {
                    "entry_id": write.entry_id,
                    "inserted": write.inserted,
                    "source_added": write.source_added,
                    "outcome": entry.outcome,
                    "limit_signal": entry.limit_signal,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ClaudeTelemetryError, RegistryError, OSError) as error:
        print(f"claude telemetry error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
