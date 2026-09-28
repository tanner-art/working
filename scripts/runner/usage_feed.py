#!/usr/bin/env python3
"""Safely collect local provider usage into the runner's usage.json schema.

This module deliberately stores only the fields accepted by ``usage_policy``.
It communicates with Codex through the local app-server protocol; credentials,
account identity, commands, and provider responses are never written or shown.
"""

import argparse
import datetime as _datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from usage_policy import UsagePolicyError, validate_usage


class UsageFeedError(RuntimeError):
    """A local observation failed without exposing provider details."""


def _timestamp(value: Optional[_datetime.datetime] = None) -> str:
    value = value or _datetime.datetime.now(_datetime.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=_datetime.timezone.utc)
    return value.astimezone(_datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _reset_timestamp(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return _timestamp(_datetime.datetime.fromtimestamp(value, _datetime.timezone.utc))
    except (OverflowError, OSError, ValueError):
        return None


def codex_record(payload: Any, model: str, observed_at: Optional[str] = None) -> Dict[str, Any]:
    """Reduce a Codex rate-limit reply to its most constrained valid window."""
    if not isinstance(model, str) or not model.strip():
        raise UsageFeedError("Codex model is required")
    if not isinstance(payload, dict):
        raise UsageFeedError("invalid Codex rate-limit reply")
    limits = payload.get("rateLimits", payload)
    if not isinstance(limits, dict):
        raise UsageFeedError("invalid Codex rate-limit reply")
    windows = [value for value in limits.values() if isinstance(value, dict)]
    selected = None
    for window in windows:
        used = window.get("used_percent")
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
            continue
        if selected is None or used > selected["used_percent"]:
            selected = {"used_percent": float(used), "reset_at": _reset_timestamp(window.get("resets_at"))}
    if selected is None:
        raise UsageFeedError("Codex did not report a usable rate-limit window")
    record = {"provider": "openai", "model": model.strip(),
              "used_percent": selected["used_percent"],
              "observed_at": observed_at or _timestamp()}
    if selected["reset_at"] is not None:
        record["reset_at"] = selected["reset_at"]
    return record


def read_codex_rate_limits(codex_home: str, timeout: float = 10.0,
                           executable: str = "codex") -> Any:
    """Request rate limits from one authenticated local CODEX_HOME."""
    environment = os.environ.copy()
    environment["CODEX_HOME"] = codex_home
    requests = "\n".join(json.dumps(item) for item in (
        {"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "threadline-usage-feed", "version": "1"}, "capabilities": {}}},
        {"method": "initialized", "params": {}},
        {"id": 2, "method": "account/rateLimits/read", "params": {}},
    )) + "\n"
    try:
        process = subprocess.Popen([executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                   env=environment)
        stdout, _ = process.communicate(requests, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if "process" in locals():
            process.kill()
            try:
                process.communicate()
            except subprocess.TimeoutExpired:
                pass
        raise UsageFeedError("Codex usage observation unavailable") from exc
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == 2 and "result" in message:
            return message["result"]
    raise UsageFeedError("Codex usage observation unavailable")


def _split_target(value: str) -> Tuple[str, str, str]:
    try:
        key, detail = value.split("=", 1)
        worker, account = key.split("/", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("target must be WORKER/ACCOUNT=VALUE") from exc
    if not worker or not account or not detail:
        raise argparse.ArgumentTypeError("target must be WORKER/ACCOUNT=VALUE")
    return worker, account, detail


def load_usage(path: pathlib.Path) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if not path.exists():
        return {}
    try:
        return validate_usage(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError, UsagePolicyError) as exc:
        raise UsageFeedError("existing usage feed is invalid") from exc


def configured_targets(path: pathlib.Path) -> Tuple[list, int]:
    """Read only worker/account/home/model routing from the runner config."""
    try:
        config = json.loads(path.read_text())
        agents = config["agents"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UsageFeedError("usage feed configuration is invalid") from exc
    if not isinstance(agents, dict):
        raise UsageFeedError("usage feed configuration is invalid")
    codex, claude = [], 0
    for worker, agent in agents.items():
        if not isinstance(worker, str) or not isinstance(agent, dict):
            raise UsageFeedError("usage feed configuration is invalid")
        provider, account, model = agent.get("provider"), agent.get("account"), agent.get("model")
        if provider == "anthropic":
            claude += 1
            continue
        if provider != "openai":
            continue
        environment = agent.get("env")
        home = environment.get("CODEX_HOME") if isinstance(environment, dict) else None
        if not all(isinstance(value, str) and value for value in (account, model, home)):
            raise UsageFeedError("usage feed configuration is invalid")
        codex.append((worker, account, home, model))
    return codex, claude


def atomic_write_usage(path: pathlib.Path, records: Mapping[str, Any]) -> None:
    """Publish validated data with a private fsynced temp file and replacement."""
    normalized = validate_usage(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(normalized, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh_codex_usage(existing: Dict[str, Dict[str, Dict[str, Any]]],
                        targets: Iterable[Tuple[str, str, str, str]], *, timeout: float = 10.0,
                        executable: str = "codex", observed_at: Optional[str] = None,
                        reader: Optional[Callable[[str], Any]] = None) -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], int, int]:
    result = {worker: dict(accounts) for worker, accounts in existing.items()}
    updated = unknown = 0
    for worker, account, home, model in targets:
        try:
            payload = reader(home) if reader else read_codex_rate_limits(home, timeout, executable)
            result.setdefault(worker, {})[account] = codex_record(payload, model, observed_at)
            updated += 1
        except Exception:
            unknown += 1
    return result, updated, unknown


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Atomically refresh sanitized local provider usage")
    parser.add_argument("--usage", required=True, type=pathlib.Path)
    parser.add_argument("--config", type=pathlib.Path,
                        help="runner config; discovers every configured Codex home")
    parser.add_argument("--codex-home", action="append", default=[], type=_split_target,
                        metavar="WORKER/ACCOUNT=CODEX_HOME")
    parser.add_argument("--codex-model", action="append", default=[], type=_split_target,
                        metavar="WORKER/ACCOUNT=MODEL")
    parser.add_argument("--claude", action="append", default=[], type=_split_target,
                        metavar="WORKER/ACCOUNT=DOCUMENTED_SOURCE")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.config and (args.codex_home or args.codex_model or args.claude):
        parser.error("--config cannot be combined with explicit provider targets")
    homes = {(worker, account): home for worker, account, home in args.codex_home}
    models = {(worker, account): model for worker, account, model in args.codex_model}
    if set(homes) != set(models):
        parser.error("each --codex-home needs exactly one matching --codex-model")
    try:
        existing = load_usage(args.usage)
        targets = [(worker, account, home, models[(worker, account)])
                   for (worker, account), home in homes.items()]
        configured_claude = 0
        if args.config:
            targets, configured_claude = configured_targets(args.config)
        records, updated, unknown = refresh_codex_usage(existing, targets, timeout=args.timeout,
                                                         executable=args.codex)
        # Claude has no documented authenticated percentage source in this slice.
        # It therefore contributes only an unknown result and cannot turn green.
        unknown += len(args.claude) + configured_claude
        # Do not rewrite a prior feed when every observation failed: that
        # preserves its exact valid records for the normal stale policy.
        if updated:
            atomic_write_usage(args.usage, records)
        print(json.dumps({"updated": updated, "unknown": unknown}, sort_keys=True))
        return 0
    except UsageFeedError:
        print("usage feed error: local usage feed unavailable", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
