#!/usr/bin/env python3
"""Provider-neutral, local usage policy for the runner.

This module only reads JSON files.  It deliberately has no provider SDK or
network dependency so the runner can make a decision before claiming work.
The canonical usage shape is::

    {"worker": {"account": {"provider": "...", "model": "...",
                              "used_percent": 12.5,
                              "observed_at": "2026-09-22T10:00:00Z"}}}
"""

import argparse
import datetime as _datetime
import json
import math
import pathlib
import sys
from typing import Any, Dict, Mapping, Optional

DEFAULT_SLOWDOWN_PERCENT = 70.0
DEFAULT_STOP_PERCENT = 80.0
DEFAULT_STALE_AFTER_SECONDS = 3600.0
DEFAULT_UNKNOWN_BEHAVIOR = "slow"


class UsagePolicyError(ValueError):
    """Raised when policy or local usage data is malformed."""


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UsagePolicyError("%s must be a number" % name)
    result = float(value)
    if not math.isfinite(result):
        raise UsagePolicyError("%s must be finite" % name)
    return result


def _timestamp(value: Any, name: str) -> _datetime.datetime:
    if not isinstance(value, str) or not value.strip():
        raise UsagePolicyError("%s must be an ISO-8601 timestamp" % name)
    text = value.strip().replace("Z", "+00:00")
    try:
        result = _datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise UsagePolicyError("%s must be an ISO-8601 timestamp" % name) from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=_datetime.timezone.utc)
    return result.astimezone(_datetime.timezone.utc)


def _now(value: Optional[_datetime.datetime] = None) -> _datetime.datetime:
    result = value or _datetime.datetime.now(_datetime.timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=_datetime.timezone.utc)
    return result.astimezone(_datetime.timezone.utc)


def _usage_root(data: Any) -> Mapping[str, Any]:
    if not isinstance(data, dict):
        raise UsagePolicyError("usage data must be an object")
    # The wrapper is accepted to make migration from other local tools safe;
    # it does not change the worker/account semantics.
    if set(data) == {"workers"}:
        data = data["workers"]
    if not isinstance(data, dict):
        raise UsagePolicyError("usage workers must be an object")
    return data


def validate_usage(data: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Validate and return local usage keyed by worker and account.

    Records contain only provider, model, used_percent, observed_at, and the
    optional reset_at.  Unknown fields are rejected to avoid accidentally
    persisting credentials or provider response payloads.
    """
    root = _usage_root(data)
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    required = {"provider", "model", "used_percent", "observed_at"}
    allowed = required | {"reset_at"}
    for worker, accounts in root.items():
        if not isinstance(worker, str) or not worker.strip() or not isinstance(accounts, dict):
            raise UsagePolicyError("usage must be keyed by worker and account")
        result[worker] = {}
        for account, record in accounts.items():
            if not isinstance(account, str) or not account.strip() or not isinstance(record, dict):
                raise UsagePolicyError("usage must be keyed by worker and account")
            if set(record) - allowed or not required <= set(record):
                raise UsagePolicyError("usage record has an invalid schema")
            if not isinstance(record["provider"], str) or not record["provider"].strip():
                raise UsagePolicyError("provider must be a non-empty string")
            if not isinstance(record["model"], str) or not record["model"].strip():
                raise UsagePolicyError("model must be a non-empty string")
            used = _number(record["used_percent"], "used_percent")
            if not 0 <= used <= 100:
                raise UsagePolicyError("used_percent must be between 0 and 100")
            observed = _timestamp(record["observed_at"], "observed_at")
            normalized = dict(record)
            normalized["used_percent"] = used
            normalized["observed_at"] = observed.isoformat()
            if "reset_at" in record:
                normalized["reset_at"] = _timestamp(record["reset_at"], "reset_at").isoformat()
            result[worker][account] = normalized
    return result


def validate_policy(config: Any) -> Dict[str, Any]:
    """Extract and validate policy settings from a runner config."""
    if not isinstance(config, dict):
        raise UsagePolicyError("config must be an object")
    raw = config.get("usage_policy", config.get("usage", {}))
    if not isinstance(raw, dict):
        raise UsagePolicyError("usage_policy must be an object")
    slowdown = _number(raw.get("slowdown_percent", DEFAULT_SLOWDOWN_PERCENT), "slowdown_percent")
    stop = _number(raw.get("stop_percent", DEFAULT_STOP_PERCENT), "stop_percent")
    stale = _number(raw.get("stale_after_seconds", DEFAULT_STALE_AFTER_SECONDS), "stale_after_seconds")
    unknown = raw.get("unknown_behavior", DEFAULT_UNKNOWN_BEHAVIOR)
    if not 0 <= slowdown < stop or stop > 80 or stop < 0:
        raise UsagePolicyError("require 0 <= slowdown_percent < stop_percent <= 80")
    if stale < 0:
        raise UsagePolicyError("stale_after_seconds must not be negative")
    if unknown not in ("slow", "stop"):
        raise UsagePolicyError("unknown_behavior must be 'slow' or 'stop'")
    return {"slowdown_percent": slowdown, "stop_percent": stop,
            "stale_after_seconds": stale, "unknown_behavior": unknown,
            "fallback_models": raw.get("fallback_models", config.get("fallback_models", {}))}


def _agent_config(config: Mapping[str, Any], worker: str) -> Mapping[str, Any]:
    agents = config.get("agents", {})
    if not isinstance(agents, dict) or not isinstance(agents.get(worker, {}), dict):
        return {}
    return agents[worker]


def agent_settings(config: Mapping[str, Any], worker: str) -> Dict[str, Any]:
    """Return the non-secret, worker-specific dispatch settings."""
    raw = _agent_config(config, worker)
    account = raw.get("account", "default")
    if not isinstance(account, str) or not account.strip():
        raise UsagePolicyError("agent account must be a non-empty string")
    settings = {"account": account, "model": raw.get("model"),
                "command": raw.get("command"),
                "fallback_model": raw.get("fallback_model"),
                "fallback_command": raw.get("fallback_command")}
    for key in ("model", "fallback_model"):
        if settings[key] is not None and (not isinstance(settings[key], str) or not settings[key].strip()):
            raise UsagePolicyError("%s must be a non-empty string" % key)
    for key in ("command", "fallback_command"):
        if settings[key] is not None and (not isinstance(settings[key], list) or
                                          not settings[key] or
                                          any(not isinstance(item, str) or not item for item in settings[key])):
            raise UsagePolicyError("%s must be a non-empty command list" % key)
    return settings


def _fallback_model(config: Mapping[str, Any], worker: str, account: str,
                    provider: Optional[str] = None) -> Optional[str]:
    settings = agent_settings(config, worker)
    if settings["fallback_model"] is not None:
        return settings["fallback_model"]
    policy = validate_policy(config)
    choices = policy["fallback_models"]
    if not isinstance(choices, dict):
        raise UsagePolicyError("fallback_models must be an object")
    candidates = [choices.get(worker, {}).get(account) if isinstance(choices.get(worker), dict) else None,
                  choices.get(worker) if isinstance(choices.get(worker), str) else None,
                  choices.get(provider) if provider else None, choices.get("default")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def recommended_fallback_model(config: Mapping[str, Any], worker: str,
                               account: str = "default", provider: Optional[str] = None) -> Optional[str]:
    return _fallback_model(config, worker, account, provider)


def worker_state(config: Mapping[str, Any], usage: Any, worker: str,
                 account: str = "default", now: Optional[_datetime.datetime] = None) -> str:
    """Return green, slow, stop, or unknown for one worker/account."""
    policy = validate_policy(config)
    records = validate_usage(usage)
    record = records.get(worker, {}).get(account)
    if record is None:
        return "unknown"
    observed = _timestamp(record["observed_at"], "observed_at")
    age = (_now(now) - observed).total_seconds()
    if age < 0 or age > policy["stale_after_seconds"]:
        return "unknown"
    used = float(record["used_percent"])
    if used >= policy["stop_percent"]:
        return "stop"
    if used >= policy["slowdown_percent"]:
        return "slow"
    return "green"


def dispatch_decision(config: Mapping[str, Any], usage: Any, worker: str,
                     account: str = "default", now: Optional[_datetime.datetime] = None) -> Dict[str, Any]:
    """Return a safe, JSON-serializable dispatch decision."""
    policy = validate_policy(config)
    settings = agent_settings(config, worker)
    records = validate_usage(usage)
    record = records.get(worker, {}).get(account)
    state = worker_state(config, records, worker, account, now)
    fallback = _fallback_model(config, worker, account, record.get("provider") if record else None)
    if state == "green":
        decision, low_cost_only = "allow", False
    elif state == "slow":
        decision, low_cost_only = "fallback", True
    elif state == "stop":
        decision, low_cost_only = "stop", False
    elif policy["unknown_behavior"] == "stop":
        decision, low_cost_only = "stop", True
    else:
        decision, low_cost_only = "fallback", True
    effective_model = settings["model"] if state == "green" else fallback
    command = settings["command"] if state == "green" else settings["fallback_command"]
    if decision == "fallback" and command is None:
        decision = "defer"
        effective_model = None
    if decision == "stop":
        effective_model = None
        command = None
    if decision in ("allow", "fallback") and command is None:
        decision = "defer"
        effective_model = None
    return {"worker": worker, "account": account, "state": state,
            "decision": decision, "low_cost_only": low_cost_only,
            "fallback_model": fallback, "effective_model": effective_model,
            "command": command}


def evaluate(config: Mapping[str, Any], usage: Any, worker: str,
             account: str = "default", now: Optional[_datetime.datetime] = None) -> Dict[str, Any]:
    """Import-friendly alias for runner integration."""
    return dispatch_decision(config, usage, worker, account, now)


def _read_json(path: str) -> Any:
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise UsagePolicyError("could not read local JSON input") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Report local worker usage policy")
    parser.add_argument("--config", required=True)
    parser.add_argument("--usage", required=True)
    parser.add_argument("--worker", required=True, help="worker or worker/account")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        worker, separator, account = args.worker.partition("/")
        if not worker or (separator and not account):
            raise UsagePolicyError("invalid worker")
        config = _read_json(args.config)
        usage = _read_json(args.usage)
        records = validate_usage(usage)
        accounts = [account] if separator else sorted(records.get(worker, {"default": {}}))
        report = [dispatch_decision(config, records, worker, item) for item in accounts]
        output = report[0] if separator or len(report) == 1 else {"worker": worker, "accounts": report}
        if args.as_json:
            print(json.dumps(output, sort_keys=True))
        else:
            for item in report:
                print("%s/%s: %s (%s; fallback=%s)" %
                      (item["worker"], item["account"], item["decision"], item["state"],
                       item["fallback_model"] or "none"))
        return 0
    except UsagePolicyError as exc:
        print("usage policy error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
