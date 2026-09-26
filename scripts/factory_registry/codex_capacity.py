"""Read-only Codex rate-limit collector and narrow Registry ingestion.

It starts no model turn: app-server only initializes and reads account identity
and rate limits. Configuration must explicitly supply each
account's CODEX_HOME and executable; account identity is hashed before any
record leaves the subprocess boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


class CapacityCollectorError(RuntimeError):
    pass


def _read_reply(process: subprocess.Popen[str], request_id: int, *, timeout: float) -> Mapping[str, Any]:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    pending = getattr(process, "_factory_reply_buffer", b"")
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            if b"\n" not in pending:
                if not selector.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise CapacityCollectorError("app-server closed before rate-limit response")
                pending += chunk
                if len(pending) > 1048576:
                    raise CapacityCollectorError("app-server response exceeds size limit")
                continue
            line, pending = pending.split(b"\n", 1)
            process._factory_reply_buffer = pending
            value = json.loads(line)
            if value.get("id") == request_id:
                if "error" in value:
                    raise CapacityCollectorError("rate-limit read failed")
                result = value.get("result")
                if not isinstance(result, Mapping):
                    raise CapacityCollectorError("rate-limit response is malformed")
                return result
    raise CapacityCollectorError("rate-limit response timed out")


def collect_rate_limits(executable: str, codex_home: str, *, timeout: float = 10,
                        account_environment: Mapping[str, str] | None = None) -> Mapping[str, Any]:
    """Return only sanitized primary/secondary bucket data from one read."""
    if not os.path.isabs(executable) or not os.path.isabs(codex_home):
        raise CapacityCollectorError("collector executable and CODEX_HOME must be absolute")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        raise CapacityCollectorError("collector timeout must be between zero and 30 seconds")
    environment = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "CODEX_HOME": codex_home}
    if account_environment:
        environment.update({key: value for key, value in account_environment.items()
                            if isinstance(key, str) and isinstance(value, str)})
    environment["CODEX_HOME"] = codex_home
    process = subprocess.Popen(
        [executable, "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, env=environment,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(json.dumps({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "threadline-factory-capacity", "version": "1"}
        }}, separators=(",", ":")) + "\n")
        process.stdin.flush()
        _read_reply(process, 1, timeout=timeout)
        process.stdin.write(json.dumps({"method": "initialized"}, separators=(",", ":")) + "\n")
        process.stdin.write(json.dumps({"id": 2, "method": "account/read", "params": {}}, separators=(",", ":")) + "\n")
        process.stdin.flush()
        account = _read_reply(process, 2, timeout=timeout)
        process.stdin.write(json.dumps({"id": 3, "method": "account/rateLimits/read", "params": {
            "excludeResetCreditDetails": True
        }}, separators=(",", ":")) + "\n")
        process.stdin.flush()
        result = _read_reply(process, 3, timeout=timeout)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    buckets = result.get("rateLimitsByLimitId") or {}
    selected = buckets.get("codex") if isinstance(buckets, Mapping) else None
    selected = selected if isinstance(selected, Mapping) else result.get("rateLimits")
    if not isinstance(selected, Mapping):
        raise CapacityCollectorError("rate-limit buckets are unavailable")
    nested_account = account.get("account") or {}
    account_id = result.get("accountId") or account.get("accountId") or nested_account.get("id")
    if not isinstance(account_id, str) or not account_id:
        raise CapacityCollectorError("account identity is unavailable")
    observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return {
        "account_identity_sha256": hashlib.sha256(str(account_id).encode()).hexdigest() if account_id else None,
        "ordinary_usage_allowed": result.get("ordinaryUsageAllowed"),
        "observed_at": observed_at, "primary": selected.get("primary"), "secondary": selected.get("secondary"),
    }


def normalize_buckets(worker_id: str, sample: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Keep original provider measurement timestamps; never re-date a cache."""
    observations = []
    if sample.get("ordinary_usage_allowed") is not True:
        raise CapacityCollectorError("provider has not allowed ordinary usage")
    if not sample.get("account_identity_sha256"):
        raise CapacityCollectorError("account identity is unavailable")
    # Provider slots are not semantic scopes: some accounts expose only a
    # weekly window in `primary`. Classify the reported duration instead.
    scopes_by_duration = {300: "short_window", 10080: "weekly_window"}
    seen_scopes = set()
    for bucket_name in ("primary", "secondary"):
        bucket = sample.get(bucket_name)
        if not isinstance(bucket, Mapping):
            continue
        duration = bucket.get("windowDurationMins")
        if isinstance(duration, bool) or duration not in scopes_by_duration:
            raise CapacityCollectorError("unrecognized rate-limit window duration")
        scope = scopes_by_duration[duration]
        if scope in seen_scopes:
            raise CapacityCollectorError("duplicate rate-limit window scope")
        seen_scopes.add(scope)
        used = bucket.get("usedPercent")
        measured_at = sample.get("observed_at")
        if not isinstance(used, (int, float)) or isinstance(used, bool) or not isinstance(measured_at, str):
            continue
        observations.append({
            "id": "codex-rate-limit:" + hashlib.sha256(
                f"{worker_id}:{scope}:{measured_at}:{used}".encode()
            ).hexdigest(),
            "worker_id": worker_id, "observed_at": measured_at,
            "reset_at": datetime.fromtimestamp(bucket["resetsAt"], timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z") if isinstance(bucket.get("resetsAt"), (int, float)) else None,
            "consumed_percent": float(used),
            "state": "HARD_STOP" if used >= 98 else "CHECKPOINT" if used >= 95 else "CAUTION" if used >= 90 else "NORMAL",
            "provider_diagnostics": {"capacity_mode": "percentage", "capacity_scope": scope,
                                     "capacity_pool": sample.get("account_identity_sha256"),
                                     "source": "codex app-server account/rateLimits/read"},
        })
    if not observations:
        raise CapacityCollectorError("no fresh timestamped rate-limit buckets")
    return tuple(observations)
