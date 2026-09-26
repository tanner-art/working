"""Explicit operator command for a read-only Codex capacity observation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .codex_capacity import collect_rate_limits, normalize_buckets
from .sqlite_registry import SQLiteRegistry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--codex-home", required=True)
    args = parser.parse_args()
    sample = collect_rate_limits(args.codex, args.codex_home)
    observations = normalize_buckets(args.worker, sample)
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    SQLiteRegistry(args.database).record_worker_capacity_observations(
        args.worker, observations, recorded_at=recorded_at
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
