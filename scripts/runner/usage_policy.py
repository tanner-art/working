#!/usr/bin/env python3
"""Provider-neutral, local capacity policy for the runner.

This module only reads JSON files.  It deliberately has no provider SDK or
network dependency so the runner can make a decision before claiming work.
The canonical usage shape is::

    {"worker": {"account": {"provider": "...", "model": "...",
                              "used_percent": 12.5,
                              "observed_at": "2026-09-22T10:00:00Z"}}}

Workers without percentage telemetry use an explicit provider-signal record
instead.  Provider/model names remain diagnostics and never select policy.
"""

import argparse
import datetime as _datetime
import json
import math
import pathlib
import sys
from typing import Any, Dict, Mapping, Optional

DEFAULT_CAUTION_PERCENT = 90.0
DEFAULT_CHECKPOINT_PERCENT = 95.0
DEFAULT_HARD_STOP_PERCENT = 98.0
DEFAULT_STALE_AFTER_SECONDS = 3600.0
DEFAULT_UNKNOWN_BEHAVIOR = "defer"

PACKAGE_SIZES = frozenset(("VERY_SMALL", "SMALL", "SUBSTANTIAL"))
PACKAGE_RISKS = frozenset(("BOUNDED", "UNCERTAIN", "EMERGENCY_RECOVERY"))
LIMIT_SIGNALS = frozenset((
    "NONE", "RATE_LIMIT", "EXHAUSTION", "THROTTLING", "CAPACITY_LAUNCH_FAILURE",
))


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

    Percentage records contain ``used_percent``. Provider-signal records
    contain explicit service/auth/live-invocation states and a normalized
    limit signal. Unknown fields are rejected to avoid accidentally persisting
    credentials or raw provider payloads.
    """
    root = _usage_root(data)
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    identity = {"provider", "model"}
    common = identity | {"observed_at"}
    percentage_allowed = common | {"capacity_mode", "used_percent", "reset_at"}
    scoped_percentage_allowed = identity | {"capacity_mode", "scopes"}
    signal_required = common | {
        "capacity_mode", "service_state", "authentication_state",
        "live_invocation_state", "limit_signal",
    }
    signal_allowed = signal_required | {"reset_at", "limit_observed_at"}
    for worker, accounts in root.items():
        if not isinstance(worker, str) or not worker.strip() or not isinstance(accounts, dict):
            raise UsagePolicyError("usage must be keyed by worker and account")
        result[worker] = {}
        for account, record in accounts.items():
            if not isinstance(account, str) or not account.strip() or not isinstance(record, dict):
                raise UsagePolicyError("usage must be keyed by worker and account")
            mode = str(record.get("capacity_mode", "percentage")).lower()
            if mode == "percentage":
                scoped = "scopes" in record
                if scoped:
                    if set(record) - scoped_percentage_allowed or not (identity | {"scopes"}) <= set(record):
                        raise UsagePolicyError("scoped percentage record has an invalid schema")
                elif set(record) - percentage_allowed or not (common | {"used_percent"}) <= set(record):
                    raise UsagePolicyError("percentage usage record has an invalid schema")
            elif mode == "provider_signal":
                if set(record) - signal_allowed or not signal_required <= set(record):
                    raise UsagePolicyError("provider-signal record has an invalid schema")
            else:
                raise UsagePolicyError("capacity_mode must be 'percentage' or 'provider_signal'")
            if not isinstance(record["provider"], str) or not record["provider"].strip():
                raise UsagePolicyError("provider must be a non-empty string")
            if not isinstance(record["model"], str) or not record["model"].strip():
                raise UsagePolicyError("model must be a non-empty string")
            normalized = dict(record)
            normalized["capacity_mode"] = mode
            if mode == "percentage":
                if "scopes" in record:
                    if not isinstance(record["scopes"], dict) or not record["scopes"]:
                        raise UsagePolicyError("scopes must be a non-empty object")
                    normalized_scopes = {}
                    for scope, observation in record["scopes"].items():
                        if not isinstance(scope, str) or not scope or not isinstance(observation, dict):
                            raise UsagePolicyError("capacity scopes must be named objects")
                        if set(observation) - {"used_percent", "observed_at", "reset_at"} or not {
                            "used_percent", "observed_at"
                        } <= set(observation):
                            raise UsagePolicyError("capacity scope has an invalid schema")
                        used = _number(observation["used_percent"], "used_percent")
                        if not 0 <= used <= 100:
                            raise UsagePolicyError("used_percent must be between 0 and 100")
                        scoped_value = dict(observation)
                        scoped_value["used_percent"] = used
                        scoped_value["observed_at"] = _timestamp(
                            observation["observed_at"], "observed_at"
                        ).isoformat()
                        if "reset_at" in observation:
                            scoped_value["reset_at"] = _timestamp(
                                observation["reset_at"], "reset_at"
                            ).isoformat()
                        normalized_scopes[scope] = scoped_value
                    normalized["scopes"] = normalized_scopes
                else:
                    observed = _timestamp(record["observed_at"], "observed_at")
                    normalized["observed_at"] = observed.isoformat()
                    used = _number(record["used_percent"], "used_percent")
                    if not 0 <= used <= 100:
                        raise UsagePolicyError("used_percent must be between 0 and 100")
                    normalized["used_percent"] = used
            else:
                observed = _timestamp(record["observed_at"], "observed_at")
                normalized["observed_at"] = observed.isoformat()
                if record["service_state"] not in ("healthy", "unhealthy"):
                    raise UsagePolicyError("service_state must be 'healthy' or 'unhealthy'")
                if record["authentication_state"] not in ("valid", "invalid"):
                    raise UsagePolicyError("authentication_state must be 'valid' or 'invalid'")
                if record["live_invocation_state"] not in ("succeeded", "failed"):
                    raise UsagePolicyError("live_invocation_state must be 'succeeded' or 'failed'")
                signal = str(record["limit_signal"]).upper()
                if signal not in LIMIT_SIGNALS:
                    raise UsagePolicyError("limit_signal is not recognized")
                normalized["limit_signal"] = signal
                if "limit_observed_at" in record:
                    normalized["limit_observed_at"] = _timestamp(
                        record["limit_observed_at"], "limit_observed_at"
                    ).isoformat()
            if "reset_at" in record and "scopes" not in record:
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
    if "slowdown_percent" in raw or "stop_percent" in raw:
        raise UsagePolicyError(
            "legacy slowdown_percent/stop_percent are unsupported; use caution_percent, "
            "checkpoint_percent, and hard_stop_percent"
        )
    caution = _number(raw.get("caution_percent", DEFAULT_CAUTION_PERCENT), "caution_percent")
    checkpoint = _number(
        raw.get("checkpoint_percent", DEFAULT_CHECKPOINT_PERCENT), "checkpoint_percent"
    )
    hard_stop = _number(
        raw.get("hard_stop_percent", DEFAULT_HARD_STOP_PERCENT), "hard_stop_percent"
    )
    stale = _number(raw.get("stale_after_seconds", DEFAULT_STALE_AFTER_SECONDS), "stale_after_seconds")
    unknown = raw.get("unknown_behavior", DEFAULT_UNKNOWN_BEHAVIOR)
    if not 0 <= caution < checkpoint < hard_stop <= 100:
        raise UsagePolicyError(
            "require 0 <= caution_percent < checkpoint_percent < hard_stop_percent <= 100"
        )
    if stale < 0:
        raise UsagePolicyError("stale_after_seconds must not be negative")
    if unknown not in ("defer", "stop"):
        raise UsagePolicyError("unknown_behavior must be 'defer' or 'stop'")
    return {"caution_percent": caution, "checkpoint_percent": checkpoint,
            "hard_stop_percent": hard_stop,
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
    raw_scopes = raw.get("capacity_scopes", ("default",))
    if not isinstance(raw_scopes, (list, tuple)):
        raise UsagePolicyError("agent capacity_scopes must be an array")
    settings = {"account": account, "model": raw.get("model"),
                "command": raw.get("command"),
                "fallback_model": raw.get("fallback_model"),
                "fallback_command": raw.get("fallback_command"),
                "capacity_mode": raw.get("capacity_mode", "percentage"),
                "capacity_scopes": tuple(raw_scopes)}
    if settings["capacity_mode"] not in ("percentage", "provider_signal"):
        raise UsagePolicyError("agent capacity_mode must be 'percentage' or 'provider_signal'")
    if (
        not settings["capacity_scopes"]
        or len(settings["capacity_scopes"]) != len(set(settings["capacity_scopes"]))
        or any(not isinstance(value, str) or not value for value in settings["capacity_scopes"])
    ):
        raise UsagePolicyError("agent capacity_scopes must be unique non-empty strings")
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
    """Return normal, caution, checkpoint, hard_stop, or unknown."""
    policy = validate_policy(config)
    records = validate_usage(usage)
    record = records.get(worker, {}).get(account)
    if record is None:
        return "unknown"
    if record["capacity_mode"] != agent_settings(config, worker)["capacity_mode"]:
        return "unknown"
    if record["capacity_mode"] == "provider_signal":
        observed = _timestamp(record["observed_at"], "observed_at")
        age = (_now(now) - observed).total_seconds()
        if age < 0 or age > policy["stale_after_seconds"]:
            return "unknown"
        healthy = (
            record["service_state"] == "healthy"
            and record["authentication_state"] == "valid"
            and record["live_invocation_state"] == "succeeded"
            and record["limit_signal"] == "NONE"
        )
        return "normal" if healthy else "hard_stop"
    expected_scopes = agent_settings(config, worker)["capacity_scopes"]
    if "scopes" in record:
        observations = [record["scopes"].get(scope) for scope in expected_scopes]
    elif expected_scopes == ("default",):
        observations = [record]
    else:
        return "unknown"
    rank = {"normal": 0, "caution": 1, "checkpoint": 2, "hard_stop": 3}
    result = "normal"
    for observation in observations:
        if observation is None:
            return "unknown"
        observed = _timestamp(observation["observed_at"], "observed_at")
        age = (_now(now) - observed).total_seconds()
        if age < 0 or age > policy["stale_after_seconds"]:
            return "unknown"
        used = float(observation["used_percent"])
        state = (
            "hard_stop" if used >= policy["hard_stop_percent"]
            else "checkpoint" if used >= policy["checkpoint_percent"]
            else "caution" if used >= policy["caution_percent"]
            else "normal"
        )
        if rank[state] > rank[result]:
            result = state
    return result


def _package_classification(package: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    raw = package or {}
    size = str(raw.get("capacity_size", "SUBSTANTIAL")).upper()
    risk = str(raw.get("capacity_risk", "UNCERTAIN")).upper()
    lane = str(raw.get("lane", "")).upper()
    kind = str(raw.get("kind", "PARENT")).upper()
    if size not in PACKAGE_SIZES:
        raise UsagePolicyError("capacity_size must be VERY_SMALL, SMALL, or SUBSTANTIAL")
    if risk not in PACKAGE_RISKS:
        raise UsagePolicyError(
            "capacity_risk must be BOUNDED, UNCERTAIN, or EMERGENCY_RECOVERY"
        )
    return {"capacity_size": size, "capacity_risk": risk, "lane": lane, "kind": kind}


def _new_work_allowed(state: str, package: Mapping[str, str]) -> bool:
    if state == "normal":
        return True
    if state in ("caution", "checkpoint"):
        if package["kind"] != "PARENT":
            return True
        return (
            package["capacity_size"] != "SUBSTANTIAL"
            and package["capacity_risk"] != "UNCERTAIN"
        )
    if state == "hard_stop":
        return (
            package["capacity_risk"] == "EMERGENCY_RECOVERY"
            or (
                package["capacity_size"] == "VERY_SMALL"
                and package["capacity_risk"] == "BOUNDED"
                and package["lane"] == "ASSURANCE"
            )
        )
    return False


def dispatch_decision(config: Mapping[str, Any], usage: Any, worker: str,
                     account: str = "default", now: Optional[_datetime.datetime] = None,
                     package: Optional[Mapping[str, Any]] = None, *,
                     in_flight: bool = False) -> Dict[str, Any]:
    """Return a safe, JSON-serializable dispatch decision."""
    policy = validate_policy(config)
    settings = agent_settings(config, worker)
    records = validate_usage(usage)
    record = records.get(worker, {}).get(account)
    state = worker_state(config, records, worker, account, now)
    classification = _package_classification(package)
    fallback = _fallback_model(config, worker, account, record.get("provider") if record else None)
    # Capacity changes never terminate healthy in-flight work.  CHECKPOINT is
    # explicit so callers can persist state and stop dispatching new substantial
    # parents after the current bounded package reaches a clean boundary.
    if in_flight and state in ("normal", "caution", "checkpoint"):
        decision = "checkpoint" if state == "checkpoint" else "continue"
    elif in_flight and state == "hard_stop" and record and record["capacity_mode"] == "percentage":
        decision = "checkpoint"
    elif state == "unknown":
        decision = "stop" if policy["unknown_behavior"] == "stop" else "defer"
    elif (
        state == "hard_stop"
        and record
        and record["capacity_mode"] == "provider_signal"
    ):
        # An observed provider limit/auth/service failure is real unavailability,
        # not a percentage threshold with a policy exception.
        decision = "stop"
    elif _new_work_allowed(state, classification):
        decision = "allow"
    else:
        decision = "stop" if state == "hard_stop" else "defer"
    effective_model = settings["model"] if decision in ("allow", "continue", "checkpoint") else None
    command = settings["command"] if decision in ("allow", "continue", "checkpoint") else None
    if decision == "stop":
        effective_model = None
        command = None
    if decision in ("allow", "continue", "checkpoint") and command is None:
        decision = "defer"
        effective_model = None
    return {"worker": worker, "account": account, "state": state,
            "decision": decision, "low_cost_only": False,
            "fallback_model": fallback, "effective_model": effective_model,
            "command": command, **classification,
            "capacity_mode": record.get("capacity_mode") if record else None,
            "limit_signal": record.get("limit_signal") if record else None}


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
