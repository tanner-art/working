#!/usr/bin/env python3
"""Launchd-friendly, Registry-authoritative bounded-run stopper.

Install two independently scheduled invocations (primary and watchdog) for one
run.  The spec is an immutable expectation, never the source of the deadline or
dispatch scope.  A superseded guard must not stop a *different* bounded run.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import quote

from .repository import RegistryConflict
from .sqlite_registry import _bounded_run_scope


PRIMARY_MAX_AGE = timedelta(seconds=180)
PRIMARY_START_GRACE = timedelta(seconds=90)
FUTURE_SKEW = timedelta(seconds=5)
VALID_MODES = {"PAUSED", "LIVE", "STOPPING", "RECOVERY_REQUIRED"}


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _expected_scope(spec_path: pathlib.Path, run_id: str) -> dict[str, Any]:
    value = json.loads(spec_path.read_text(encoding="utf-8"))
    scope = _bounded_run_scope(value, active_parent_limit=3)
    if scope is None or scope["run_id"] != run_id:
        raise ValueError("bounded run spec identity mismatch")
    return scope


def read_authority(database: pathlib.Path) -> dict[str, Any]:
    """Read one consistent Registry snapshot without creating SQLite files."""
    if not database.is_absolute() or not database.is_file():
        raise ValueError("Registry database path is unavailable")
    uri = "file:" + quote(str(database), safe="/") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        control = connection.execute(
            "SELECT dispatch_mode, kill_switch_engaged, changed_at "
            "FROM factory_control WHERE singleton=1"
        ).fetchone()
        revision = connection.execute(
            "SELECT value FROM registry_metadata WHERE key='revision'"
        ).fetchone()
        limit = connection.execute(
            "SELECT value FROM registry_metadata WHERE key='active_parent_limit'"
        ).fetchone()
        scope_row = connection.execute(
            "SELECT value FROM registry_metadata WHERE key='bounded_run_scope'"
        ).fetchone()
        if control is None or revision is None or limit is None:
            raise ValueError("Registry control metadata is missing")
        scope = (
            _bounded_run_scope(json.loads(scope_row["value"]), active_parent_limit=int(limit["value"]))
            if scope_row is not None else None
        )
        mode = control["dispatch_mode"]
        if mode not in VALID_MODES or control["kill_switch_engaged"] not in (0, 1):
            raise ValueError("Registry control state is invalid")
        return {
            "mode": mode,
            "kill_switch_engaged": bool(control["kill_switch_engaged"]),
            "changed_at": _time(control["changed_at"]),
            "revision": int(revision["value"]),
            "scope": scope,
        }


def _heartbeat_path(state: pathlib.Path, run_id: str, role: str) -> pathlib.Path:
    return state / f"bounded-guard-{run_id}-{role}.json"


def _primary_failure(state: pathlib.Path, run_id: str, now: datetime,
                     live_since: datetime) -> str | None:
    try:
        heartbeat = json.loads(_heartbeat_path(state, run_id, "primary").read_text(encoding="utf-8"))
        if heartbeat.get("run_id") != run_id or heartbeat.get("role") != "primary":
            return "primary stopper identity mismatch"
        checked_at = _time(heartbeat.get("checked_at"))
        if checked_at > now + FUTURE_SKEW or now - checked_at > PRIMARY_MAX_AGE:
            return "primary stopper heartbeat stale"
        if heartbeat.get("action") not in {"observe", "standby"}:
            return "primary stopper health unknown"
        if heartbeat.get("observed_mode") != "LIVE" and now - live_since > PRIMARY_START_GRACE:
            return "primary stopper has not observed LIVE"
    except (OSError, ValueError, TypeError, KeyError):
        return "primary stopper heartbeat unavailable"
    return None


def _atomic_heartbeat(path: pathlib.Path, record: Mapping[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(record, output, separators=(",", ":"), sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def request_stop(database: pathlib.Path, reason: str, run_id: str | None) -> bool:
    command = [
        sys.executable, "-m", "scripts.factory_registry.operator_cli", "stop",
        "--database", str(database), "--reason", reason,
    ]
    if run_id is not None:
        command.extend(("--run-id", run_id))
    try:
        result = subprocess.run(
            command, cwd=pathlib.Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def guard_once(database: pathlib.Path, spec_path: pathlib.Path, state: pathlib.Path,
               run_id: str, role: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Perform one guard check; the caller schedules repeated invocations."""
    now = now or datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "run_id": run_id, "role": role,
        "checked_at": now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "observed_mode": "UNKNOWN", "registry_revision": None,
        "scope_matches": False, "deadline": None, "action": "unknown",
    }
    expected = None
    spec_error = None
    try:
        expected = _expected_scope(spec_path, run_id)
    except (OSError, ValueError, TypeError, KeyError, RegistryConflict) as error:
        spec_error = f"bounded run spec invalid: {type(error).__name__}"
    authority = None
    authority_error = None
    try:
        authority = read_authority(database)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, RegistryConflict) as error:
        authority_error = f"Registry health unknown: {type(error).__name__}"

    reason = None
    stop_run_id: str | None = None
    if authority is None:
        reason = authority_error or "Registry health unknown"
    else:
        mode = authority["mode"]
        scope = authority["scope"]
        record["observed_mode"] = mode
        record["registry_revision"] = authority["revision"]
        record["deadline"] = scope["deadline"] if scope else None
        record["scope_matches"] = bool(scope and expected and scope == expected)
        if mode == "LIVE":
            if scope is not None and scope["run_id"] != run_id:
                # A stale launchd job cannot kill a deliberately superseding run.
                record["action"] = "superseded"
            elif scope is None:
                reason = "LIVE Registry has no bounded run scope"
            else:
                stop_run_id = run_id
                if authority["kill_switch_engaged"]:
                    reason = "LIVE Registry kill switch state is invalid"
                elif authority["changed_at"] > now + FUTURE_SKEW:
                    reason = "LIVE Registry transition time is in the future"
                elif spec_error is not None:
                    reason = spec_error
                elif scope != expected:
                    reason = "authoritative bounded run scope mismatch"
                elif now >= _time(scope["deadline"]):
                    reason = "authoritative bounded run deadline reached"
                elif role == "watchdog":
                    reason = _primary_failure(state, run_id, now, authority["changed_at"])
                if reason is None:
                    record["action"] = "observe"
        elif not authority["kill_switch_engaged"]:
            reason = "non-LIVE Registry kill switch state is invalid"
        elif spec_error is not None:
            # Do not advertise a healthy preflight for an unreadable spec.
            record["action"] = "invalid-spec"
            record["reason"] = spec_error
        else:
            record["action"] = "standby"

    if reason is not None:
        record["reason"] = reason
        if request_stop(database, reason, stop_run_id):
            try:
                after = read_authority(database)
                if after["mode"] == "LIVE":
                    record["action"] = (
                        "superseded" if stop_run_id is not None and after["scope"]
                        and after["scope"]["run_id"] != stop_run_id else "stop-unverified"
                    )
                else:
                    record["action"] = "stop-requested"
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, RegistryConflict):
                record["action"] = "stop-unverified"
        else:
            record["action"] = "stop-failed"

    path = _heartbeat_path(state, run_id, role)
    try:
        _atomic_heartbeat(path, record)
    except OSError:
        # A running watchdog without durable health evidence is not healthy.
        if authority is not None and authority["mode"] == "LIVE" and record["action"] == "observe":
            request_stop(database, "bounded run guard heartbeat write failed", stop_run_id)
        raise
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("primary", "watchdog"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--spec", type=pathlib.Path, required=True)
    parser.add_argument("--database", type=pathlib.Path, required=True)
    parser.add_argument("--state", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,95}", args.run_id):
        parser.error("--run-id must be a bounded run identity")
    record = guard_once(args.database, args.spec, args.state, args.run_id, args.role)
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
    return 0 if record["action"] in {"observe", "standby", "stop-requested"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
